"""
csf-coordinator — Govern-only stub (Sun Aug 16 scope; full 6-agent fan-out is
Phase 3 / Aug 22, per govern_build_tasks.md).

Composes DispatchStep -> CollectResultsStep -> AggregateStep as a
SequentialAgent (ADK's agent-composition primitive for deterministic,
non-LLM-backed workflow steps), then runs it through the same ADK
Runner/session pattern used by csf_specialists.agent_base.

NOTE: SequentialAgent is deprecated in google-adk 2.6.3 in favor of a new
`Workflow`/FunctionNode API, but still fully functional and part of the public
`google.adk.agents` surface. Using it here rather than the newer (much less
documented) Workflow API to keep this stub's risk/effort proportionate;
revisit if/when the fleet grows to the full 6-agent fan-out in Phase 3.
"""
from __future__ import annotations

import logging
import uuid

from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud.firestore import AsyncClient
from google.genai import types

from csf_coordinator.config import get_settings
from csf_coordinator.steps import AggregateStep, CollectResultsStep, DispatchStep
from csf_gateway.app.schema import TierResult

log = logging.getLogger("csf-coordinator")

ADK_APP_NAME = "csf-coordinator"
ADK_USER_ID = "csf-assessor"


async def run_govern_only(session_id: str, category_ids: list[str]) -> TierResult:
    """
    Dispatch Govern-only scoring for a session, wait for the specialist's
    completion message, aggregate to a Tier. Requires csf_specialists/worker.py
    (or an equivalent consumer) to be pulling csf-dispatch-govern concurrently.
    """
    run_id = str(uuid.uuid4())

    agent = SequentialAgent(
        name="csf_coordinator",
        sub_agents=[
            DispatchStep(
                name="dispatch", run_id=run_id, session_id=session_id,
                function="govern", category_ids=category_ids,
            ),
            CollectResultsStep(
                name="collect_results", session_id=session_id, run_id=run_id, expected_count=1,
            ),
            AggregateStep(
                name="aggregate", session_id=session_id, run_id=run_id, function="govern",
            ),
        ],
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=ADK_APP_NAME, session_service=session_service)

    adk_session_id = str(uuid.uuid4())
    await session_service.create_session(app_name=ADK_APP_NAME, user_id=ADK_USER_ID, session_id=adk_session_id)

    async for event in runner.run_async(
        user_id=ADK_USER_ID,
        session_id=adk_session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=f"run_govern_only session={session_id}")]),
    ):
        if event.content and event.content.parts:
            text = "".join(p.text for p in event.content.parts if p.text)
            if text:
                log.info("[coordinator] %s: %s", event.author, text)

    s = get_settings()
    client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    tier_ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
        .collection("tiers").document("govern")
    )
    snap = await tier_ref.get()
    return TierResult.model_validate(snap.to_dict())
