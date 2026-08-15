"""
E4 — DOCX → markdown via python-docx.

DOCX is authored (not scanned), so python-docx handles it well without needing
a multimodal LLM. Walks paragraphs first, then tables, in the order they appear
in the document body.
"""
from __future__ import annotations

import logging
from io import BytesIO

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph

log = logging.getLogger("csf-gateway.ingest.docx")


def _iter_block_items(doc: DocumentType):
    """Yield Paragraphs and Tables in document order."""
    parent_elm = doc.element.body
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield DocxTable(child, doc)


def _paragraph_to_md(para: Paragraph) -> str:
    text = para.text.strip()
    if not text:
        return ""
    style_name = (para.style.name or "").strip()
    if style_name.startswith("Heading"):
        parts = style_name.split()
        try:
            level = int(parts[-1])
        except ValueError:
            level = 1
        level = max(1, min(level, 6))
        return f"{'#' * level} {text}"
    if style_name.lower() in {"title"}:
        return f"# {text}"
    return text


def _table_to_md(table: DocxTable) -> str:
    lines: list[str] = []
    for i, row in enumerate(table.rows):
        cells = [cell.text.strip().replace("|", "\\|").replace("\n", " ") for cell in row.cells]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n".join(lines)


def docx_to_markdown(docx_bytes: bytes) -> str:
    """Convert a .docx file (bytes) to markdown. Preserves headings, paragraphs, and tables."""
    doc = Document(BytesIO(docx_bytes))
    out: list[str] = []
    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            md = _paragraph_to_md(block)
            out.append(md)
        elif isinstance(block, DocxTable):
            out.append("")
            out.append(_table_to_md(block))
            out.append("")
    text = "\n".join(out).strip()
    log.info("docx→md: %d bytes → %d chars", len(docx_bytes), len(text))
    return text
