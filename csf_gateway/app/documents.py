"""
Document upload + status endpoints.

Contract:
- POST /sessions/{sid}/documents  multipart upload; validates per-file, dedupes
  by content hash within the session, uploads raw to GCS, writes Firestore
  document row (pending), spawns background ingest task, returns 202 immediately.
- GET  /sessions/{sid}/documents               list all
- GET  /sessions/{sid}/documents/{did}/status  single-doc poll for progress

Validation policy (all pre-checked before any side effect):
- files length must equal doc_types length (if doc_types provided)
- extension in {.pdf, .docx, .doc, .xlsx}
- size <= settings.max_upload_bytes
- doc_type must be a member of DocType
- session must exist
Any validation failure returns 4xx and NO files are ingested (atomic batch).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .config import get_settings
from .doctype_taxonomy import DocType
from .ingest import dedupe, firestore_writer, orchestrator, storage
from .schema import (
    DocumentSummary,
    DocumentStatusResponse,
    DocumentUploadResponse,
    IngestStatus,
    UploadedFile,
)
from .sessions import get_session

log = logging.getLogger("csf-gateway.documents")

router = APIRouter(prefix="/sessions/{session_id}/documents", tags=["documents"])

# ingest_status → coarse progress percent for the polling client
_PROGRESS_PCT: dict[str, int] = {
    IngestStatus.pending.value:   0,
    IngestStatus.parsing.value:   20,
    IngestStatus.chunking.value:  45,
    IngestStatus.embedding.value: 70,
    IngestStatus.ready.value:     100,
    IngestStatus.failed.value:    0,
}

_CONTENT_TYPES: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_ALLOWED_EXTS = frozenset(_CONTENT_TYPES.keys())


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=202,
    summary="Upload one or more documents for ingestion (async).",
)
async def post_documents(
    session_id: str,
    files: Annotated[list[UploadFile], File(description="One or more PDF/DOCX/XLSX files.")],
    doc_types: Annotated[
        list[str] | None,
        Form(
            description=(
                "Parallel list of DocType values, one per file. "
                "Accepts either separate form entries (`-F doc_types=A -F doc_types=B`) "
                "or a single comma-separated string (Swagger UI does this). "
                "Defaults to 'Other' for every file. Valid values: "
                + ", ".join(t.value for t in DocType)
            ),
        ),
    ] = None,
) -> DocumentUploadResponse:
    """
    Accept a batch of files. Validate all up front (atomic). For each new file:
    upload raw to GCS, write Firestore doc (pending), spawn background ingest.
    Duplicates (same content hash within session) are skipped and the existing
    doc_id is returned instead.
    """
    s = get_settings()

    # 0. Session must exist
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    org_id = session.org_id or ""   # legacy sessions may have blank org_id

    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    # 1. Normalize + validate doc_types
    if doc_types is None:
        doc_types = [DocType.other.value] * len(files)
    # Swagger UI sends multi-value form arrays as one comma-joined string.
    # If we got a single entry that contains commas AND we have multiple files, split it.
    if len(doc_types) == 1 and "," in doc_types[0] and len(files) > 1:
        doc_types = [dt.strip() for dt in doc_types[0].split(",")]
    if len(doc_types) != len(files):
        raise HTTPException(
            status_code=400,
            detail=(
                f"doc_types has {len(doc_types)} entries, expected {len(files)} (one per file). "
                "Send as multiple form entries or a single comma-separated string."
            ),
        )
    typed_doctypes: list[DocType] = []
    for dt_str in doc_types:
        try:
            typed_doctypes.append(DocType(dt_str))
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"unknown doc_type '{dt_str}'. Valid values: {[t.value for t in DocType]}",
            ) from e

    # 2. Read + validate each file (all-or-nothing at this stage)
    prepared: list[tuple[str, bytes, DocType, str, str]] = []  # (filename, data, doc_type, ext, content_type)
    for upload, dt in zip(files, typed_doctypes):
        filename = upload.filename or ""
        ext = Path(filename).suffix.lower()
        if ext not in _ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"{filename!r}: unsupported extension {ext!r}. Allowed: {sorted(_ALLOWED_EXTS)}",
            )
        data = await upload.read()
        if len(data) > s.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{filename!r} is {len(data)} bytes, exceeds max {s.max_upload_bytes}",
            )
        if len(data) == 0:
            raise HTTPException(status_code=400, detail=f"{filename!r} is empty")
        prepared.append((filename, data, dt, ext, _CONTENT_TYPES[ext]))

    # 3. For each file: dedupe → upload → write doc row → spawn ingest
    fw_client = firestore_writer.get_client()
    result_files: list[UploadedFile] = []

    for filename, data, dt, ext, content_type in prepared:
        content_hash = dedupe.compute_content_hash(data)

        existing = await dedupe.find_existing_doc_id(session_id, content_hash, fw_client)
        if existing is not None:
            log.info("dedupe hit for %s in session %s → doc_id=%s", filename, session_id, existing)
            result_files.append(UploadedFile(filename=filename, doc_id=existing, was_duplicate=True))
            continue

        doc_id = str(uuid.uuid4())

        # Sync GCS upload — small files (<20MB), acceptable in the request path
        gcs_uri = storage.upload_raw(session_id, doc_id, filename, data, content_type)

        # Create the Firestore doc row in "pending" so subsequent status polls have something to read
        doc_row = DocumentSummary(
            doc_id=doc_id,
            filename=filename,
            doc_type=dt,
            org_id=org_id,
            uploaded_at=datetime.now(timezone.utc),
            ingest_status=IngestStatus.pending,
            gcs_uri=gcs_uri,
            content_hash=content_hash,
        )
        await firestore_writer.write_document(session_id, doc_row)

        # Fire-and-forget: the orchestrator drives the pipeline to completion / failure.
        asyncio.create_task(
            orchestrator.ingest_one(session_id, doc_id, filename, dt, data, org_id=org_id),
            name=f"ingest:{session_id[:8]}:{doc_id[:8]}",
        )

        result_files.append(UploadedFile(filename=filename, doc_id=doc_id, was_duplicate=False))

    status = "complete" if all(f.was_duplicate for f in result_files) else "processing"
    return DocumentUploadResponse(files=result_files, status=status)


@router.get(
    "",
    response_model=list[DocumentSummary],
    summary="List all documents in a session with current ingest status.",
)
async def list_documents(session_id: str) -> list[DocumentSummary]:
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    raw = await firestore_writer.list_documents(session_id)
    return [DocumentSummary.model_validate(r) for r in raw]


@router.get(
    "/{doc_id}/status",
    response_model=DocumentStatusResponse,
    summary="Poll a single document's ingest status. Cheap enough for 1-2s polling.",
)
async def get_document_status(session_id: str, doc_id: str) -> DocumentStatusResponse:
    row = await firestore_writer.get_document(session_id, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"document {doc_id} not found in session {session_id}")
    status = row.get("ingest_status", "pending")
    return DocumentStatusResponse(
        doc_id=doc_id,
        ingest_status=IngestStatus(status),
        progress_pct=_PROGRESS_PCT.get(status, 0),
        failure_reason=row.get("failure_reason"),
    )
