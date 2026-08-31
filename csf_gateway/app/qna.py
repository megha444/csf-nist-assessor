"""
Q&A document upload — turns an already-completed questionnaire (PDF/DOCX/XLSX)
into pre-answered evidence for a session, via one LLM extraction call.

Distinct from documents.py's ingest pipeline: no chunking/embedding/Qdrant —
this is direct answers to attach to `sessions/{sid}/answers/`, not searchable
document evidence.

Contract:
  POST /sessions/{sid}/qna  multipart, one file -> {records_extracted, by_function}
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from csf_gateway.app.model_armor import ModelArmorBlocked
from csf_specialists.qna_extractor import extract_qna
from csf_specialists.scripts.preseed_govern import preseed

from .ingest import docx_parser, pdf_parser, xlsx_parser
from .sessions import _client_get, get_session

log = logging.getLogger("csf-gateway.qna")

router = APIRouter(prefix="/sessions/{session_id}/qna", tags=["qna"])

_ALLOWED_EXTS = frozenset({".pdf", ".docx", ".doc", ".xlsx"})

# xlsx_parser.xlsx_to_markdown emits one "## SheetName" heading per worksheet.
# A multi-sheet questionnaire covering all 6 Functions (~240 Q&A pairs) blows
# past extract_qna's single-call output budget and truncates mid-JSON — proven
_SHEET_HEADING_RE = re.compile(r"^## ", re.MULTILINE)


def _split_by_sheet(markdown: str) -> list[str]:
    if not _SHEET_HEADING_RE.search(markdown):
        return [markdown]
    return [p for p in re.split(r"(?=^## )", markdown, flags=re.MULTILINE) if p.strip()]


async def _record_questionnaire(session_id: str, filename: str, records_extracted: int) -> None:
    """Note that this questionnaire was provided, at sessions/{sid}/questionnaires/{id}.

    Extracted answers land in `answers/` keyed by question, which loses the fact
    that a file was ever uploaded — before this, a questionnaire left no filename
    anywhere in the system, so the PDF report's appendix (which lists what the
    client actually handed over) silently omitted it. Deliberately a bare record,
    not a DocumentSummary: nothing is chunked, embedded or stored in GCS on this
    path, so most of that model would be empty fields.

    Best-effort — a bookkeeping write must never fail an upload whose answers were
    already extracted and preseeded successfully.
    """
    try:
        client = _client_get()
        await (
            client.collection("sessions").document(session_id)
            .collection("questionnaires").document(uuid.uuid4().hex)
            .set({
                "filename": filename,
                "records_extracted": records_extracted,
                "uploaded_at": datetime.now(timezone.utc),
            })
        )
    except Exception:
        log.exception(
            "[%s] failed to record questionnaire %r — continuing", session_id, filename)


@router.post("", summary="Upload a completed Q&A questionnaire; extract + attach as pre-answered evidence.")
async def post_qna(session_id: str, file: Annotated[UploadFile, File(description="One completed Q&A document.")]) -> dict:
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail=f"session {session_id} not found")

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"{filename!r}: unsupported extension {ext!r}. Allowed: {sorted(_ALLOWED_EXTS)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{filename!r} is empty")

    if ext in (".docx", ".doc"):
        text = docx_parser.docx_to_markdown(data)
    elif ext == ".xlsx":
        text = xlsx_parser.xlsx_to_markdown(data)
    else:
        text = await pdf_parser.pdf_to_markdown(data)

    if not text.strip():
        raise HTTPException(
            status_code=422, detail=f"{filename!r} produced no extractable text")

    sections = _split_by_sheet(text) if ext == ".xlsx" else [text]

    # Cap extraction at 3 concurrent Gemini calls — the worker uses the same cap
    # (csf_specialists/worker.py MAX_CONCURRENT_CATEGORIES) after observing 429
    # RESOURCE_EXHAUSTED at 6 concurrent. return_exceptions so one sheet's
    # failure doesn't discard every other sheet's successfully extracted answers
    # — before this, a single 429 on one worksheet threw away all six and
    # returned a 500 for the whole upload.
    sem = asyncio.Semaphore(3)

    async def _extract_capped(section: str):
        async with sem:
            return await extract_qna(section)

    results = await asyncio.gather(
        *(_extract_capped(section) for section in sections), return_exceptions=True)

    blocked = next((r for r in results if isinstance(r, ModelArmorBlocked)), None)
    if blocked is not None:
        # Model Armor flagged the uploaded questionnaire as a prompt-injection /
        # jailbreak attempt and block-on-injection is enabled — reject at the
        # door, whole document, even if other sheets extracted cleanly.
        raise HTTPException(
            status_code=400,
            detail=(
                f"{filename!r} rejected — content flagged as a potential prompt-injection / "
                f"jailbreak attempt (confidence {blocked.confidence}). The document was not ingested."
            ),
        )

    extracted = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    for exc in failures:
        log.warning("[%s] %s: one section's extraction failed: %r", session_id, filename, exc)
    if failures and not extracted:
        raise HTTPException(
            status_code=502,
            detail=(
                f"{filename!r}: extraction failed for all {len(failures)} section(s) "
                f"({failures[0]!r}) — wait a moment and retry."
            ),
        )
    records = [r for batch in extracted for r in batch]
    if not records:
        log.info("[%s] %s: no Q&A pairs identified", session_id, filename)
        return {"records_extracted": 0, "by_function": {}}

    await preseed(session_id, records)
    await _record_questionnaire(session_id, filename, len(records))

    by_function: dict[str, int] = {}
    for r in records:
        by_function[r.function] = by_function.get(r.function, 0) + 1

    log.info("[%s] %s: extracted %d Q&A pairs (%s), %d section(s) failed",
             session_id, filename, len(records), by_function, len(failures))
    return {
        "records_extracted": len(records),
        "by_function": by_function,
        "sections_failed": len(failures),
    }
