"""
E5 — Section-aware chunker with tiktoken token counts.

Primary strategy: cut at heading boundaries (regex over markdown ATX headings
and common policy-doc heading conventions). Fallback: sliding token window with
overlap when a section is larger than `max_tokens`.

Also parses `<!-- page N -->` markers emitted by `pdf_parser.py` to preserve
page ranges in chunk metadata for citations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

# Markdown-style headings emitted by the PDF/DOCX parsers, plus common policy
# heading conventions found in SANS templates ("1. Purpose", "SECTION 3", etc.)
HEADING_RE = re.compile(
    r"^\s*(?:"
    r"#{1,6}\s+.+"                             # markdown ATX heading
    r"|SECTION\s+\d+[:\.\s].*"                 # "SECTION 3:"
    r"|\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{0,120}"   # "3.2 Access Control"
    r")\s*$",
    re.MULTILINE,
)

PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)


_encoder: "tiktoken.Encoding | None" = None


def _get_encoder() -> "tiktoken.Encoding":
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")  # reasonable approx for Gemini
    return _encoder


def token_count(text: str) -> int:
    return len(_get_encoder().encode(text))


@dataclass
class Chunk:
    text: str
    section_title: str
    chunk_index: int
    token_count: int
    page_start: int
    page_end: int


def _strip_heading_marker(line: str) -> str:
    """Reduce a heading line to just its title text."""
    line = line.strip()
    line = re.sub(r"^#{1,6}\s+", "", line)
    return line.strip()


def _split_into_sections(md: str) -> list[tuple[str, str]]:
    """Split markdown by heading lines. Returns [(section_title, body_text), ...]."""
    lines = md.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current: list[str] = []
    for line in lines:
        if HEADING_RE.match(line):
            if current:
                sections.append((current_title, current))
            current_title = _strip_heading_marker(line)
            current = []
        else:
            current.append(line)
    if current:
        sections.append((current_title, current))

    return [(title, "\n".join(body).strip()) for title, body in sections if any(l.strip() for l in body)]


def _pages_in(text: str, current_page: int) -> tuple[int, int, int]:
    """
    Extract page range covered by `text`. Returns (page_start, page_end, page_after_text).
    If no markers are present, uses `current_page` as both start and end.
    """
    matches = list(PAGE_MARKER_RE.finditer(text))
    if not matches:
        return current_page, current_page, current_page
    pages = [int(m.group(1)) for m in matches]
    start = min(pages[0], current_page)
    end = max(pages[-1], current_page)
    return start, end, end


def chunk_markdown(
    md: str,
    target_tokens: int = 800,
    overlap_tokens: int = 100,
    max_tokens: int = 1200,
) -> list[Chunk]:
    """
    Split markdown into chunks.

    Section-aware: prefer heading boundaries. Fallback: sliding token window
    with overlap. Page numbers are extracted from `<!-- page N -->` markers if
    present (produced by pdf_parser).
    """
    enc = _get_encoder()
    sections = _split_into_sections(md)
    chunks: list[Chunk] = []
    idx = 0
    running_page = 1

    for section_title, body in sections:
        if not body:
            continue

        # Update running_page from any leading markers
        first_page_match = PAGE_MARKER_RE.search(body)
        if first_page_match:
            running_page = int(first_page_match.group(1))

        # Strip page markers from the text we embed (keep pages in metadata)
        clean_body = PAGE_MARKER_RE.sub("", body).strip()
        if not clean_body:
            continue

        tokens = enc.encode(clean_body)

        if len(tokens) <= max_tokens:
            p_start, p_end, running_page = _pages_in(body, running_page)
            chunks.append(Chunk(
                text=clean_body,
                section_title=section_title,
                chunk_index=idx,
                token_count=len(tokens),
                page_start=p_start,
                page_end=p_end,
            ))
            idx += 1
            continue

        # Section too large — slide with overlap
        step = max(target_tokens - overlap_tokens, 100)
        for start in range(0, len(tokens), step):
            window = tokens[start : start + target_tokens]
            if not window:
                break
            text = enc.decode(window)
            p_start, p_end, running_page = _pages_in(text, running_page)
            chunks.append(Chunk(
                text=text.strip(),
                section_title=section_title,
                chunk_index=idx,
                token_count=len(window),
                page_start=p_start,
                page_end=p_end,
            ))
            idx += 1
            if start + target_tokens >= len(tokens):
                break

    return chunks
