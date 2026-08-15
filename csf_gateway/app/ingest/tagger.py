"""
E6 — Chunk → candidate CSF Category tagger.

Cheap deterministic keyword match against the precomputed KEYWORD_INDEX. No
LLM cost, no per-doc latency to speak of. First-pass tags for the Interview
Director coverage map and for Vector Search bias.

Uses `\\b` word-boundary regex (not naive substring) so short keywords like
"sso" or "rto" don't match inside unrelated words. Patterns are compiled once
at module load — 191 patterns, ~10 μs per chunk in practice.
"""
from __future__ import annotations

import re

from ..csf_catalog import KEYWORD_INDEX

# Pre-compile one word-boundary regex per keyword.
_PATTERNS: list[tuple[re.Pattern[str], set[str]]] = [
    (re.compile(rf"\b{re.escape(keyword)}\b"), cat_codes)
    for keyword, cat_codes in KEYWORD_INDEX.items()
]


def tag_chunk(text: str) -> list[str]:
    """
    Return a sorted list of candidate Category codes whose keywords appear as
    whole words (case-insensitive) in the chunk text.
    """
    tl = text.lower()
    hits: set[str] = set()
    for pattern, cat_codes in _PATTERNS:
        if pattern.search(tl):
            hits |= cat_codes
    return sorted(hits)
