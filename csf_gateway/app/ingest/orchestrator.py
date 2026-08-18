"""
E10 — Async ingest orchestrator.

Glues together storage → parse → chunk → tag → embed → upsert → firestore
writes, driving the `ingest_status` state machine. Called by the POST
/documents route via `asyncio.create_task(ingest_one(...))`.

Failure mode contract: any exception is caught, `ingest_status` is set to
`failed` with a `failure_reason`, and the exception is logged with a full
traceback. Other in-flight ingests for the same session are unaffected.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client.http.models import PointStruct

from ..doctype_taxonomy import DocType
from ..schema import ChunkRecord, IngestStatus
from . import chunker, docx_parser, embedder, firestore_writer, pdf_parser, tagger, vector_store, xlsx_parser

log = logging.getLogger("csf-gateway.ingest.orch")


async def ingest_one(
    session_id: str,
    doc_id: str,
    filename: str,
    doc_type: DocType,
    data: bytes,
    org_id: str = "",
) -> None:
    """
    Full ingest pipeline for one document. Assumes:
      - Raw file already uploaded to GCS by the route handler (storage.upload_raw)
      - Firestore document row already created with ingest_status=pending
    Updates status as it progresses; sets `failed` on any exception.
    """
    short = doc_id[:8]

    async def _update(status: IngestStatus, **fields: Any) -> None:
        try:
            await firestore_writer.update_document_status(session_id, doc_id, status, **fields)
        except Exception:
            log.exception("[%s] failed to update status → %s", short, status.value)

    try:
        # --- 1. Parse ---
        await _update(IngestStatus.parsing)
        lower = filename.lower()
        if lower.endswith(".pdf"):
            log.info("[%s] parsing PDF (%s)", short, filename)
            markdown = await pdf_parser.pdf_to_markdown(data)
        elif lower.endswith((".docx", ".doc")):
            log.info("[%s] parsing DOCX (%s)", short, filename)
            markdown = docx_parser.docx_to_markdown(data)
        elif lower.endswith(".xlsx"):
            log.info("[%s] parsing XLSX (%s)", short, filename)
            markdown = xlsx_parser.xlsx_to_markdown(data)
        else:
            raise ValueError(f"unsupported file extension: {filename}")

        if not markdown.strip():
            raise ValueError("parser produced empty markdown")

        # --- 2. Chunk ---
        await _update(IngestStatus.chunking)
        raw_chunks = chunker.chunk_markdown(markdown)
        log.info("[%s] produced %d chunks (%d chars markdown)", short, len(raw_chunks), len(markdown))

        if not raw_chunks:
            raise ValueError("chunker produced no chunks")

        # --- 3. Tag + convert to ChunkRecord ---
        chunk_records: list[ChunkRecord] = []
        for c in raw_chunks:
            chunk_id = str(uuid.uuid4())
            chunk_records.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    text=c.text,
                    section_title=c.section_title,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    chunk_index=c.chunk_index,
                    token_count=c.token_count,
                    vector_datapoint_id=chunk_id,
                    candidate_categories=tagger.tag_chunk(c.text),
                )
            )

        # --- 4. Embed ---
        await _update(IngestStatus.embedding)
        vectors = await embedder.embed_texts([r.text for r in chunk_records])
        assert len(vectors) == len(chunk_records), "embedding count mismatch"

        # --- 5. Vector upsert (Qdrant) ---
        points = [
            PointStruct(
                id=r.chunk_id,
                vector=v,
                payload={
                    "org_id": org_id,
                    "session_id": session_id,
                    "doc_id": doc_id,
                    "chunk_id": r.chunk_id,
                    "doc_type": doc_type.value,
                    "candidate_categories": r.candidate_categories,
                    "page_start": r.page_start,
                    "page_end": r.page_end,
                    "section_title": r.section_title,
                    "text": r.text,
                },
            )
            for r, v in zip(chunk_records, vectors)
        ]
        vector_store.upsert_chunks(points)

        # --- 6. Firestore chunk writes + finalize status ---
        await firestore_writer.write_chunks(session_id, doc_id, chunk_records)
        await _update(IngestStatus.ready, chunk_count=len(chunk_records))
        log.info("[%s] READY — %d chunks", short, len(chunk_records))

    except Exception as e:
        log.exception("[%s] FAILED: %s", short, e)
        reason = f"{type(e).__name__}: {e}"[:500]
        await _update(IngestStatus.failed, failure_reason=reason)
