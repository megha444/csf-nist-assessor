"""
E2 — Content-hash dedupe.

Prevents re-ingesting the same file twice per session. Same-file uploads across
different sessions are still distinct (session isolation is a first principle).
"""
from __future__ import annotations

import hashlib

from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter


def compute_content_hash(data: bytes) -> str:
    """SHA-256 hex digest of the file bytes."""
    return hashlib.sha256(data).hexdigest()


async def find_existing_doc_id(
    session_id: str,
    content_hash: str,
    client: AsyncClient,
) -> str | None:
    """Return doc_id if a document with this content hash already exists in the session."""
    coll = (
        client.collection("sessions")
        .document(session_id)
        .collection("documents")
    )
    query = coll.where(filter=FieldFilter("content_hash", "==", content_hash)).limit(1)
    async for snap in query.stream():
        return snap.id
    return None
