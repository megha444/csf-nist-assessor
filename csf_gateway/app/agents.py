"""
Agent Registry — discoverability endpoint (Fortified component).

Each SpecialistAgent self-registers its own metadata into Firestore on
construction (see csf_specialists/agent_base.py::_register) — this endpoint
just reads that back, so the registry is something a judge (or a teammate)
can actually query, not a Firestore doc nobody ever looks at.

Contract:
  GET /agents  -> [{function, capabilities, rubric_version, iam_identity, registered_at}, ...]
"""
from __future__ import annotations

from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from .config import get_settings

router = APIRouter(tags=["agents"])

_firestore_client: AsyncClient | None = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


@router.get("/agents", summary="List every registered specialist agent and its capabilities.")
async def list_agents() -> list[dict]:
    client = _get_firestore_client()
    docs = [d.to_dict() async for d in client.collection("agents").stream()]
    return sorted(docs, key=lambda d: d.get("function", ""))
