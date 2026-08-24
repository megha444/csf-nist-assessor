"""
E8 — Qdrant upsert / query wrapper.

Intentionally thin so that per ADR-0001 the backend can be swapped to Vertex
AI Vector Search later with a one-file change.
"""
from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
)

from ..config import get_settings

log = logging.getLogger("csf-gateway.ingest.vector")

_client: QdrantClient | None = None


def _client_get() -> QdrantClient:
    global _client
    if _client is None:
        s = get_settings()
        # check_compatibility=False silences the cosmetic client-1.16 vs server-1.19
        # warning; the API surface we use is stable across that range. See ingest_tasks.md
        # follow-ups.
        _client = QdrantClient(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            timeout=30.0,
            check_compatibility=False,
        )
    return _client


def upsert_chunks(points: list[PointStruct]) -> None:
    """Upsert a batch of chunk vectors + payloads into the shared collection."""
    if not points:
        return
    s = get_settings()
    _client_get().upsert(collection_name=s.qdrant_collection, points=points)
    log.info("upserted %d points to '%s'", len(points), s.qdrant_collection)


def _search(
    filter_: Filter,
    query_vector: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    s = get_settings()
    hits = _client_get().query_points(
        collection_name=s.qdrant_collection,
        query=query_vector,
        query_filter=filter_,
        limit=top_k,
    ).points
    return [{"id": h.id, "score": h.score, "payload": h.payload} for h in hits]


def search_session(
    session_id: str,
    query_vector: list[float],
    top_k: int = 5,
    doc_type_filter: list[str] | None = None,
    doc_id_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Vector search within a single session. This is what the specialists use
    during a Run — the current assessment's docs only.

    doc_id_filter (added 2026-08-24) scopes to specific documents by their
    real Firestore doc_id, not the coarse doc_type label — most real uploads
    share doc_type="Other" (the taxonomy has ~14 entries, real packages have
    35+ distinct document concepts), so doc_type alone can't isolate one
    specific document the way an evidence-taxonomy lookup needs to.
    """
    must = [FieldCondition(key="session_id", match=MatchValue(value=session_id))]
    if doc_type_filter:
        must.append(FieldCondition(key="doc_type", match=MatchAny(any=doc_type_filter)))
    if doc_id_filter:
        must.append(FieldCondition(key="doc_id", match=MatchAny(any=doc_id_filter)))
    return _search(Filter(must=must), query_vector, top_k)


def search_org(
    org_id: str,
    query_vector: list[float],
    top_k: int = 5,
    doc_type_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Vector search across ALL sessions of a given org. Useful for future
    features: "show me all evidence about MFA that Acme has ever provided",
    historical Tier deltas, dedupe candidates.

    Not used by specialists during a Run (they stay session-scoped for audit).
    """
    must = [FieldCondition(key="org_id", match=MatchValue(value=org_id))]
    if doc_type_filter:
        must.append(FieldCondition(key="doc_type", match=MatchAny(any=doc_type_filter)))
    return _search(Filter(must=must), query_vector, top_k)


def delete_by_session(session_id: str) -> None:
    """Delete every point in a session. Used for hard resets / test cleanup."""
    s = get_settings()
    _client_get().delete(
        collection_name=s.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
        ),
    )


def delete_by_org(org_id: str) -> None:
    """Delete every point belonging to an org. Post-hackathon cleanup helper."""
    s = get_settings()
    _client_get().delete(
        collection_name=s.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="org_id", match=MatchValue(value=org_id))]
        ),
    )
