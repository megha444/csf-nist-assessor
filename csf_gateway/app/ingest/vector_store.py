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
        _client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=30.0)
    return _client


def upsert_chunks(points: list[PointStruct]) -> None:
    """Upsert a batch of chunk vectors + payloads into the shared collection."""
    if not points:
        return
    s = get_settings()
    _client_get().upsert(collection_name=s.qdrant_collection, points=points)
    log.info("upserted %d points to '%s'", len(points), s.qdrant_collection)


def search_session(
    session_id: str,
    query_vector: list[float],
    top_k: int = 5,
    doc_type_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Vector search within a session. Returns list of {id, score, payload} dicts.
    Optional doc_type_filter narrows to specific doc types (for the specialist
    agents' Function-scoped retrieval).
    """
    s = get_settings()
    must = [FieldCondition(key="session_id", match=MatchValue(value=session_id))]
    if doc_type_filter:
        must.append(
            FieldCondition(
                key="doc_type",
                match=MatchValue(any=doc_type_filter),   # noqa (any= is supported)
            )
        )
    hits = _client_get().query_points(
        collection_name=s.qdrant_collection,
        query=query_vector,
        query_filter=Filter(must=must),
        limit=top_k,
    ).points
    return [{"id": h.id, "score": h.score, "payload": h.payload} for h in hits]


def delete_by_session(session_id: str) -> None:
    """Delete every point in a session. Used for hard resets / test cleanup."""
    s = get_settings()
    _client_get().delete(
        collection_name=s.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
        ),
    )
