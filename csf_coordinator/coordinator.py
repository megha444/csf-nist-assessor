"""
csf-coordinator — dispatches to every Function that currently has a real
specialist agent (csf_specialists.agents.AGENTS), not just Govern. Full 6-agent
fan-out still depends on the other 4 Function agents existing (Phase 3 / Aug 22
per govern_build_tasks.md) — this generalizes the mechanism now so it needs no
further coordinator changes as more agents land, just a new AGENTS entry.

Composes CreateRunStep -> DispatchStep(s) -> CollectResultsStep -> AggregateStep(s)
as a SequentialAgent (ADK's agent-composition primitive for deterministic,
non-LLM-backed workflow steps), run through the same ADK Runner/session pattern
used by csf_specialists.agent_base. Functions are dispatched sequentially within
one ADK run, not across concurrent worker processes — real parallel dispatch
needs one worker process per Function (see csf_specialists/worker.py --function),
which is a deployment concern deferred to Phase 3, not a limit of this code.

NOTE: SequentialAgent is deprecated in google-adk 2.6.3 in favor of a new
`Workflow`/FunctionNode API, but still fully functional and part of the public
`google.adk.agents` surface. Using it here rather than the newer (much less
documented) Workflow API to keep this proportionate; revisit alongside Phase 3.
"""
from __future__ import annotations

import logging
import uuid

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud.firestore import AsyncClient
from google.genai import types

from csf_coordinator.config import get_settings
from csf_coordinator.steps import AggregateStep, CollectResultsStep, CreateRunStep, DispatchStep
from csf_gateway.app.schema import TierResult
from csf_specialists.agents import AGENTS
from csf_specialists.loaders import load_rubric

log = logging.getLogger("csf-coordinator")

ADK_APP_NAME = "csf-coordinator"
ADK_USER_ID = "csf-assessor"


async def run_assessment(
    session_id: str,
    functions: list[str] | None = None,
) -> tuple[str, dict[str, TierResult]]:
    """
    Run a full assessment for a session across every Function passed (default:
    every Function with a registered agent — today, govern + identify). Category
    ids per Function are auto-derived from that Function's loaded rubric, not
    hand-typed by the caller.

    One shared run_id across all dispatched Functions — this is one assessment,
    not N unrelated runs. Requires csf_specialists/worker.py --function <fn>
    running (one process per Function) to actually consume the dispatches.

    Returns (run_id, {function: TierResult}) for whichever Functions completed.
    """
    functions = functions or list(AGENTS.keys())
    unknown = [f for f in functions if f not in AGENTS]
    if unknown:
        raise ValueError(f"no registered agent for function(s) {unknown} — see csf_specialists.agents.AGENTS")

    run_id = str(uuid.uuid4())
    print(f"[coordinator] run_id={run_id} functions={functions}")

    sub_agents: list[BaseAgent] = [
        CreateRunStep(
            name="create_run", run_id=run_id, session_id=session_id, expected_agents=len(functions),
        ),
    ]
    for function in functions:
        category_ids = list(load_rubric(function).categories.keys())
        sub_agents.append(DispatchStep(
            name=f"dispatch_{function}", run_id=run_id, session_id=session_id,
            function=function, category_ids=category_ids,
        ))
    sub_agents.append(CollectResultsStep(
        name="collect_results", session_id=session_id, run_id=run_id, expected_count=len(functions),
    ))
    for function in functions:
        sub_agents.append(AggregateStep(
            name=f"aggregate_{function}", session_id=session_id, run_id=run_id, function=function,
        ))

    agent = SequentialAgent(name="csf_coordinator", sub_agents=sub_agents)

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=ADK_APP_NAME, session_service=session_service)

    adk_session_id = str(uuid.uuid4())
    await session_service.create_session(app_name=ADK_APP_NAME, user_id=ADK_USER_ID, session_id=adk_session_id)

    async for event in runner.run_async(
        user_id=ADK_USER_ID,
        session_id=adk_session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=f"run_assessment session={session_id} functions={functions}")]),
    ):
        if event.content and event.content.parts:
            text = "".join(p.text for p in event.content.parts if p.text)
            if text:
                log.info("[coordinator] %s: %s", event.author, text)

    s = get_settings()
    client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    run_ref = client.collection("sessions").document(session_id).collection("runs").document(run_id)

    results: dict[str, TierResult] = {}
    for function in functions:
        snap = await run_ref.collection("tiers").document(function).get()
        if snap.exists:
            results[function] = TierResult.model_validate(snap.to_dict())
        else:
            log.warning("[%s] no tier persisted for run_id=%s — Function may not have completed", function, run_id)

    return run_id, results
