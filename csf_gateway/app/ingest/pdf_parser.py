"""
E3 — PDF → structured markdown via Gemini 3.5 Flash multimodal.

Per ADR-0003: one Gemini call replaces a pypdf + pdfplumber + PyMuPDF + OCR
stack. Handles narrative text, tables, and figure descriptions in one pass.
"""
from __future__ import annotations

import logging

from google import genai
from google.genai import types

from ..config import get_settings

log = logging.getLogger("csf-gateway.ingest.pdf")

_client: genai.Client | None = None


def _client_get() -> genai.Client:
    global _client
    if _client is None:
        s = get_settings()
        _client = genai.Client(
            vertexai=True,
            project=s.google_cloud_project,
            location=s.google_cloud_location,   # 'global' for Gemini 3.x
        )
    return _client


PROMPT = """\
Convert this PDF into clean, structured Markdown for a downstream text retrieval system.

Rules:
- Preserve heading hierarchy: use `#` for the highest-level headings, `##` for the next, etc.
- Preserve every body paragraph. Do not summarize.
- Render tables as GitHub-flavored markdown tables.
- For each chart, diagram, or embedded image, insert a placeholder line describing what it shows: `[Figure: <one-line description of the visual content>]`.
- Insert a marker `<!-- page N -->` before the content of each page N (N = 1, 2, 3, …). This is mandatory — the chunker relies on these markers.
- Preserve numbering (e.g. "3.2", "3.2.1") in headings.
- Do NOT add any commentary, preamble, or explanation. Output the markdown only.
"""


async def pdf_to_markdown(pdf_bytes: bytes) -> str:
    """
    Convert a PDF file to structured markdown.

    Returns the raw markdown text. Empty string on unexpected empty response.
    """
    s = get_settings()
    client = _client_get()

    response = await client.aio.models.generate_content(
        model=s.gemini_flash_model,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            PROMPT,
        ],
        config=types.GenerateContentConfig(
            max_output_tokens=32000,
            temperature=0.1,
        ),
    )

    text = response.text or ""
    usage = response.usage_metadata
    log.info(
        "pdf→md: input=%d bytes, output=%d chars, tokens in=%s out=%s thoughts=%s",
        len(pdf_bytes),
        len(text),
        getattr(usage, "prompt_token_count", "?"),
        getattr(usage, "candidates_token_count", "?"),
        getattr(usage, "thoughts_token_count", 0),
    )
    return text
