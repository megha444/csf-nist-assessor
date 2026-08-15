"""
E9 — Firestore writer for documents + chunks.

Owns the `ingest_status` state machine for a document row and batch-writes
chunk rows (Firestore commit limit = 500 per batch; we chunk defensively).
"""
from __future__ import annotations

import logging
from typing import Any

from google.cloud.firestore import AsyncClient

from ..config import get_settings
from ..schema import ChunkRecord, DocumentSummary, IngestStatus

log = logging.getLogger("csf-gateway.ingest.firestore")

BATCH_SIZE = 400  # under Firestore's 500-op commit limit for headroom

_client: AsyncClient | None = None


def get_client() -> AsyncClient:
    """Shared AsyncClient for ingest-side Firestore access."""
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncClient(project=s.google_cloud_project, database=s.firestore_database)
    return _client


# Backwards-compat alias for the private-looking name used elsewhere in this module
_client_get = get_client


def _doc_ref(session_id: str, doc_id: str):
    return (
        _client_get()
        .collection("sessions")
        .document(session_id)
        .collection("documents")
        .document(doc_id)
    )


async def write_document(session_id: str, doc: DocumentSummary) -> None:
    """Create the document row (called at ingest start, before parsing)."""
    await _doc_ref(session_id, doc.doc_id).set(doc.model_dump())
    log.info("created documents/%s (session=%s)", doc.doc_id, session_id)


async def update_document_status(
    session_id: str,
    doc_id: str,
    status: IngestStatus,
    **fields: Any,
) -> None:
    """Advance the ingest_status state machine + optional side fields."""
    payload: dict[str, Any] = {"ingest_status": status.value, **fields}
    await _doc_ref(session_id, doc_id).update(payload)
    log.info("documents/%s status → %s (%s)", doc_id, status.value, ", ".join(fields))


async def write_chunks(session_id: str, doc_id: str, chunks: list[ChunkRecord]) -> None:
    """Batch-write chunk rows under `documents/{doc_id}/chunks/{chunk_id}`."""
    client = _client_get()
    chunks_ref = _doc_ref(session_id, doc_id).collection("chunks")

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = client.batch()
        for chunk in chunks[i : i + BATCH_SIZE]:
            batch.set(chunks_ref.document(chunk.chunk_id), chunk.model_dump())
        await batch.commit()
        log.info(
            "wrote chunks batch %d-%d (doc=%s)",
            i, i + min(BATCH_SIZE, len(chunks) - i), doc_id,
        )


async def list_documents(session_id: str) -> list[dict[str, Any]]:
    """Read all documents in a session (for the GET /documents route)."""
    coll = (
        _client_get()
        .collection("sessions")
        .document(session_id)
        .collection("documents")
    )
    return [snap.to_dict() async for snap in coll.stream()]


async def get_document(session_id: str, doc_id: str) -> dict[str, Any] | None:
    snap = await _doc_ref(session_id, doc_id).get()
    return snap.to_dict() if snap.exists else None
