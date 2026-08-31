"""
Agent Runtime — asynchronous assessment execution.

Starts an assessment as a real backgrounded task inside the gateway process
and returns a run_id immediately, instead of the caller blocking for however
long the coordinator sequence takes (dispatch -> collect -> aggregate ->
judge, several minutes with 6 Functions). Same asyncio.create_task
fire-and-forget pattern documents.py already uses for ingest — this is the
7th Fortified component (previously untracked, see docs/HANDOFF.md §7.9),
and closes a real bug: the prior synchronous call blocked Streamlit's own
connection long enough that the browser's live connection could go stale
before the automatic rerun fired, leaving the UI showing a stuck spinner
after the backend had already finished (confirmed live 2026-08-21).

The gateway is deployed with --no-cpu-throttling (infra/deploy_gateway.sh),
so a plain in-process background task keeps running after the HTTP response
is sent — no need to route this through a separate Cloud Run Job the way
csf-worker's actual scoring compute is (DispatchStep triggers that
separately, per Function, once dispatch actually happens).

TWO HOSTS, one contract (COORDINATOR_MODE, see config.py). "Agent Runtime"
means two different things in this repo and both are real:
  - inprocess — the background task described above, built Aug 23 (9e9a6af)
    as the Fortified "Agent Runtime" component (asynchronous execution).
  - native    — Google's Agent Runtime: the Coordinator hosted on Vertex AI
    Agent Engine (reasoningEngines/…), invoked over async_stream_query.
Both call the same run_assessment() and write the same Firestore docs, so
everything downstream of this module — status polling, the UI fragment, the
report surfaces — is identical either way. Switching hosts is an env flip,
not a code change, which is what makes it safe to demo.

Status polling reads the same runs/{run_id} Firestore doc CreateRunStep /
CollectResultsStep / AggregateStep already write to (status: dispatched ->
partial -> ready_for_report) — no new status model.

Contract:
  POST /sessions/{sid}/run                    -> {run_id, status: "started"}
  GET  /sessions/{sid}/runs/{run_id}/status    -> {run_id, status, completed_agents, expected_agents}
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from google.cloud.firestore import AsyncClient

from csf_coordinator.coordinator import run_assessment
from csf_gateway.app.config import get_settings
from csf_specialists.agents import AGENTS

from .sessions import get_session

log = logging.getLogger("csf-gateway.runs")

router = APIRouter(tags=["run"])

# Agent Engine scopes its managed sessions by user_id. Every gateway-initiated
# run shares one, since our real session identity is the CSF session_id carried
# in the message — the engine session is just the invocation channel.
_ENGINE_USER = "csf-gateway"

_firestore_client: AsyncClient | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


async def _run_via_agent_runtime(session_id: str, functions: list[str], run_id: str) -> None:
    """Drive the assessment on the Coordinator deployed to Vertex AI Agent Engine
    (GEAP Agent Runtime) instead of executing it inside this container.

    The caller's run_id is passed through in the message — coordinator_engine's
    adapter parses `run=` and hands it to the same run_assessment() the
    in-process path calls, so the hosted run writes the exact Firestore doc the
    UI is already polling. Without that, the engine would mint its own run_id
    and the UI would poll a document that never appears.

    Only orchestration moves. The 6 specialists still consume Pub/Sub as
    csf-worker Cloud Run Jobs, and Firestore stays the source of truth — the
    streamed events are progress logs, not the result. That's what makes a
    dropped stream survivable: the engine keeps running server-side and the
    status endpoint keeps reporting from Firestore either way.

    The invocation runs ENTIRELY off the event loop, in a worker thread.

    This used to call vertexai.init()/agent_engines.get() directly and then hold
    `async_stream_query` for the whole run. Despite the async surface, that
    pinned the event loop for the assessment's full duration (~7 min), so the
    gateway could not serve ANY request while a run was in flight -- including
    the `/runs/{rid}/status` poll the UI depends on. Observed locally
    2026-08-28: /health timed out for the entire run.

    Deployed, Cloud Run's max-instances=3 mostly hid this by routing polls to a
    second instance, which is why it showed up only as occasional empty poll
    responses rather than an outright hang. With min-instances=0 a poll landing
    on the blocked instance would still stall, so this was a latent production
    bug, not just a local-dev annoyance.

    Using the SYNC client inside asyncio.to_thread is both simpler and correct:
    the blocking happens on a worker thread and the event loop stays free.
    """
    s = get_settings()
    if not s.reasoning_engine_resource:
        raise RuntimeError("COORDINATOR_MODE=native but REASONING_ENGINE_RESOURCE is unset")

    message = f"session={session_id} functions={','.join(functions)} run={run_id}"
    log.info("[%s] run_id=%s invoking Agent Runtime %s", session_id, run_id, s.reasoning_engine_resource)

    def _invoke_blocking() -> None:
        import vertexai
        from vertexai import agent_engines

        # Agent Engine is regional; Gemini stays on `global` (see config.py).
        vertexai.init(project=s.google_cloud_project, location=s.agent_engine_location)
        app = agent_engines.get(s.reasoning_engine_resource)

        remote = app.create_session(user_id=_ENGINE_USER)
        remote_id = remote["id"] if isinstance(remote, dict) else getattr(remote, "id", remote)

        for event in app.stream_query(
            user_id=_ENGINE_USER, session_id=remote_id, message=message
        ):
            for part in (event.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    log.info("[%s] run_id=%s agent-runtime: %s", session_id, run_id, part["text"])

    await asyncio.to_thread(_invoke_blocking)


async def _run_exists(session_id: str, run_id: str) -> bool:
    """Has CreateRunStep written the run doc yet? Used to decide whether the
    hosted Coordinator already owns this run (see _run_and_log_errors)."""
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
    )
    return (await ref.get()).exists


async def _run_and_log_errors(session_id: str, functions: list[str], run_id: str) -> None:
    """Execute one assessment, preferring whichever host COORDINATOR_MODE names.

    Falling back to in-process is only safe *before* the hosted Coordinator has
    taken ownership of the run. Once CreateRunStep has written
    sessions/{sid}/runs/{rid}, the engine is already dispatching — it runs
    server-side and does not stop just because our event stream dropped. Re-running
    the same run_id here would publish every Pub/Sub dispatch a second time,
    trigger duplicate csf-worker executions, and race CollectResultsStep against
    itself. So a late failure is logged and left alone (the engine finishes and
    the status endpoint reports it from Firestore); only an early failure —
    engine unreachable, mid-redeploy, bad resource name — falls through.
    """
    s = get_settings()
    if s.coordinator_mode == "native":
        try:
            await _run_via_agent_runtime(session_id, functions, run_id)
            return
        except Exception:
            log.exception("[%s] run_id=%s Agent Runtime invocation failed", session_id, run_id)
            try:
                owned = await _run_exists(session_id, run_id)
            except Exception:
                log.exception("[%s] run_id=%s could not check run ownership", session_id, run_id)
                owned = True  # assume owned: a duplicate run is worse than a stalled one
            if owned:
                log.warning(
                    "[%s] run_id=%s hosted Coordinator already dispatched — NOT re-running "
                    "in-process (would double-dispatch); it continues server-side",
                    session_id, run_id,
                )
                return
            log.warning(
                "[%s] run_id=%s failed before dispatch — falling back to in-process",
                session_id, run_id,
            )

    try:
        await run_assessment(session_id, functions=functions, run_id=run_id)
    except Exception:
        log.exception("[%s] run_id=%s run_assessment failed", session_id, run_id)


@router.post("/sessions/{session_id}/run", summary="Start an assessment run asynchronously.")
async def start_run(session_id: str) -> dict:
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    functions = list(AGENTS.keys())
    run_id = str(uuid.uuid4())
    # Fire-and-forget: same pattern documents.py uses for ingest. The caller
    # polls GET .../status instead of waiting on this coroutine.
    asyncio.create_task(
        _run_and_log_errors(session_id, functions, run_id),
        name=f"run_assessment:{session_id[:8]}:{run_id[:8]}",
    )
    return {"run_id": run_id, "status": "started", "functions": functions}


@router.get("/sessions/{session_id}/runs/{run_id}/status", summary="Poll an assessment run's status.")
async def get_run_status(session_id: str, run_id: str) -> dict:
    client = _get_firestore_client()
    ref = (
        client.collection("sessions").document(session_id)
        .collection("runs").document(run_id)
    )
    snap = await ref.get()
    if not snap.exists:
        # CreateRunStep hasn't written the doc yet — a client polling right
        # after the POST response can beat it by a beat or two.
        return {"run_id": run_id, "status": "pending"}
    d = snap.to_dict()
    return {
        "run_id": run_id,
        "status": d.get("status"),
        "completed_agents": d.get("completed_agents"),
        "expected_agents": d.get("expected_agents"),
        "failure_reason": d.get("failure_reason"),
    }
