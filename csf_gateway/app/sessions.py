"""
Session lifecycle — Firestore data access + FastAPI router.

A "session" is one CSF assessment run. It carries: uploaded docs, pre-seed
answers, live chat transcript, and (once the user hits "Run assessment") a
frozen snapshot the specialists work from.

Firestore path: `sessions/{session_id}`. Full schema in `docs/lld.md §1`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from google.cloud.firestore import AsyncClient

from .config import get_settings
from .schema import CreateSessionRequest, SessionState, slugify_org

log = logging.getLogger("csf-gateway.sessions")

SESSIONS_COLLECTION = "sessions"

_client: AsyncClient | None = None


def _client_get() -> AsyncClient:
    """Lazy-init a module-level AsyncClient. Reused across requests."""
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
        log.info(
            "Firestore async client initialized: project=%s database=%s",
            s.google_cloud_project, s.firestore_database,
        )
    return _client


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------


async def create_session(
    target_org: str = "Northwind Financial",
    org_id: str | None = None,
) -> SessionState:
    """
    Create a new session document in Firestore and return the state.

    org_id: if omitted, derived from target_org via slugification. Pass explicitly
    to guarantee cross-session consistency for the same tenant.
    """
    session_id = str(uuid.uuid4())
    resolved_org_id = org_id or slugify_org(target_org)
    state = SessionState(
        session_id=session_id,
        target_org=target_org,
        org_id=resolved_org_id,
        created_at=datetime.now(timezone.utc),
    )
    doc_ref = _client_get().collection(SESSIONS_COLLECTION).document(session_id)
    await doc_ref.set(state.model_dump())
    log.info(
        "created session %s (target=%s, org_id=%s)",
        session_id, target_org, resolved_org_id,
    )
    return state


async def get_session(session_id: str) -> SessionState | None:
    """Read a session from Firestore. Returns None if not found."""
    doc_ref = _client_get().collection(SESSIONS_COLLECTION).document(session_id)
    snap = await doc_ref.get()
    if not snap.exists:
        return None
    return SessionState.model_validate(snap.to_dict())


async def list_sessions(limit: int = 50) -> list[SessionState]:
    """Most-recent-first session list, for the UI's session picker."""
    query = (
        _client_get().collection(SESSIONS_COLLECTION)
        .order_by("created_at", direction="DESCENDING")
        .limit(limit)
    )
    return [SessionState.model_validate(snap.to_dict()) async for snap in query.stream()]


# ---------------------------------------------------------------------------
# HTTP router — mounted at /sessions in main.py
# ---------------------------------------------------------------------------


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionState, status_code=201)
async def post_session(payload: CreateSessionRequest | None = None) -> SessionState:
    """
    Create a new assessment session.

    Body is optional — omit it to use the demo default (`Northwind Financial`).
    Send `{"target_org": "Acme Corp"}` (or any other name) to assess a different org.
    """
    payload = payload or CreateSessionRequest()
    return await create_session(target_org=payload.target_org, org_id=payload.org_id)


@router.get("", response_model=list[SessionState])
async def list_sessions_endpoint(limit: int = 50) -> list[SessionState]:
    """Most-recent-first session list — backs the UI's session picker."""
    return await list_sessions(limit=limit)


@router.get("/{session_id}", response_model=SessionState)
async def get_session_endpoint(session_id: str) -> SessionState:
    """Read the current state of a session, including doc_ids, chat_state, etc."""
    state = await get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return state
