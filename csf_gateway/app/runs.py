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

_firestore_client: AsyncClient | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


async def _run_and_log_errors(session_id: str, functions: list[str], run_id: str) -> None:
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
    }
