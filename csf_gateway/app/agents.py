"""
Agent Registry — discoverability endpoint (Fortified component).

Two registries, deliberately, and the difference matters:

  * **Google's native Agent Registry** (`agentregistry.googleapis.com`) is the
    authoritative catalogue. The Coordinator is in it **automatically** — Agent
    Runtime registers what it hosts, so `csf-coordinator` carries the native URN
    `urn:agent:...:aiplatform:reasoningEngines:4356...` plus platform-supplied
    attributes we could never set by hand (its Agent-Runtime service identity,
    framework, and a live RuntimeReference). The 6 specialists and this gateway
    are registered manually by infra/register_agent_registry.py.

  * **Firestore `agents/{function}`** holds the domain metadata the native
    registry has no field for under a NO_SPEC registration: which CSF Categories
    each specialist covers and the content hash of the rubric it scored against.
    Written by csf_specialists/agent_base.py::_register at construction.

This endpoint merges the two so one URL answers "what agents exist, what can
they do, and are they really in Google's registry." The native call is
best-effort: any error or timeout degrades to Firestore-only rather than
failing, because a preview API must never hang a judge-facing route.

Contract:
  GET /agents            -> {source, native_registry, agents: [...]}
  GET /agents/{function} -> one agent's descriptor

NOTE ON /agents/{function}: this is a **descriptor** endpoint. It returns what an
agent is and what it covers. It is NOT an invocation endpoint — you cannot POST
here to run a scoring job (specialists are Cloud Run Jobs consuming Pub/Sub, with
no HTTP surface of their own). It exists because Agent Registry requires every
registered Service to carry an `Interface.url`, and this is the honest one.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException
from google.cloud.firestore import AsyncClient

from .config import get_settings

log = logging.getLogger("csf-gateway.agents")

router = APIRouter(tags=["agents"])

_firestore_client: AsyncClient | None = None
_creds = None


def _get_firestore_client() -> AsyncClient:
    global _firestore_client
    if _firestore_client is None:
        s = get_settings()
        _firestore_client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _firestore_client


def _access_token() -> str:
    """Blocking — call via asyncio.to_thread. Credentials are cached and only
    refreshed when actually expired, so the steady-state cost is nil."""
    global _creds
    import google.auth
    from google.auth.transport.requests import Request

    if _creds is None:
        _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds.token


async def _native_registry() -> dict:
    """Fetch the native catalogue. Returns a dict that always includes
    `reachable`; on failure it carries the reason instead of raising, so callers
    can render a degraded-but-honest response."""
    s = get_settings()
    if not s.agent_registry_enabled:
        return {"reachable": False, "error": "disabled by config", "agents": []}

    loc = s.agent_registry_location
    url = (
        f"https://agentregistry.googleapis.com/v1/projects/"
        f"{s.google_cloud_project}/locations/{loc}/agents?pageSize=100"
    )
    try:
        token = await asyncio.to_thread(_access_token)
        async with httpx.AsyncClient(timeout=s.agent_registry_timeout_seconds) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return {
            "reachable": True,
            "location": loc,
            "agents": resp.json().get("agents", []),
        }
    except Exception as e:
        # Degrade, never fail: Firestore still answers the question.
        log.warning("native Agent Registry unreachable (%s) — serving Firestore only", e)
        return {"reachable": False, "location": loc, "error": f"{type(e).__name__}: {e}", "agents": []}


def _match_native(fn: str, native_agents: list[dict]) -> dict | None:
    """Match a Firestore function to its native entry by registered interface
    URL (…/agents/{fn}) rather than display name — the URL is what we actually
    registered, so it can't drift if a display name is edited."""
    suffix = f"/agents/{fn}"
    for a in native_agents:
        for proto in a.get("protocols") or []:
            for iface in proto.get("interfaces") or []:
                if str(iface.get("url", "")).endswith(suffix):
                    return a
    return None


def _summarize_native(a: dict) -> dict:
    attrs = a.get("attributes") or {}
    runtime_ref = attrs.get("agentregistry.googleapis.com/system/RuntimeReference") or {}
    identity = attrs.get("agentregistry.googleapis.com/system/RuntimeIdentity") or {}
    framework = attrs.get("agentregistry.googleapis.com/system/Framework") or {}

    # EVERY entry carries a RuntimeReference, so its presence proves nothing —
    # what differs is where it points. A manually registered Service references
    # itself (//agentregistry.googleapis.com/...); an agent the platform hosts
    # and registered on its own references the real runtime
    # (//aiplatform.googleapis.com/.../reasoningEngines/...). Checking mere
    # presence would label our hand-registered specialists as platform-hosted,
    # which is false.
    uri = str(runtime_ref.get("uri") or "")
    hosted_on_agent_runtime = uri.startswith("//aiplatform.googleapis.com/")

    return {
        "agent_id": a.get("agentId"),
        "display_name": a.get("displayName"),
        "location": a.get("location"),
        "registration": "automatic" if hosted_on_agent_runtime else "manual",
        "hosted_on_agent_runtime": hosted_on_agent_runtime,
        # Only ever set by the platform, so these stay absent on manual entries.
        "runtime_identity": identity.get("principal"),
        "framework": framework.get("framework"),
        "runtime_reference": uri or None,
    }


@router.get("/agents", summary="List every registered agent, merging Firestore metadata with Google's native Agent Registry.")
async def list_agents() -> dict:
    client = _get_firestore_client()
    docs = [d.to_dict() async for d in client.collection("agents").stream()]
    docs.sort(key=lambda d: d.get("function", ""))

    native = await _native_registry()
    native_agents = native.get("agents", [])

    agents = []
    for d in docs:
        fn = d.get("function", "")
        match = _match_native(fn, native_agents)
        agents.append({**d, "native_registry": _summarize_native(match) if match else None})

    # The Coordinator has no Firestore doc — it isn't a scoring specialist — but
    # it is the most important entry, so surface it from the native side. Select
    # it by the one property nothing else here has: the platform hosts it, so its
    # RuntimeReference points at aiplatform rather than back at the registry.
    coordinator = next(
        (a for a in native_agents if _summarize_native(a)["hosted_on_agent_runtime"]),
        None,
    )

    return {
        "source": "firestore+agent_registry" if native["reachable"] else "firestore",
        "native_registry": {
            "reachable": native["reachable"],
            "location": native.get("location"),
            "error": native.get("error"),
            "total_agents_visible": len(native_agents),
        },
        "coordinator": _summarize_native(coordinator) if coordinator else None,
        "agents": agents,
    }


@router.get("/agents/{function}", summary="Descriptor for one specialist agent (metadata only — not an invocation endpoint).")
async def get_agent(function: str) -> dict:
    client = _get_firestore_client()
    snap = await client.collection("agents").document(function).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"no registered agent for function '{function}'")

    d = snap.to_dict() or {}
    native = await _native_registry()
    match = _match_native(function, native.get("agents", []))
    return {
        **d,
        "endpoint_kind": "descriptor",  # metadata only; scoring is dispatched over Pub/Sub
        "native_registry": _summarize_native(match) if match else None,
    }
