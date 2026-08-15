"""
E6 — Chunk → candidate CSF Category tagger.

Cheap deterministic keyword match against the precomputed KEYWORD_INDEX. No
LLM cost, no per-doc latency to speak of. First-pass tags for the Interview
Director coverage map and for Vector Search bias.
"""
from __future__ import annotations

from ..csf_catalog import KEYWORD_INDEX


def tag_chunk(text: str) -> list[str]:
    """
    Return a sorted list of candidate Category codes whose keywords appear in
    the chunk text (lowercase substring match).
    """
    tl = text.lower()
    hits: set[str] = set()
    for keyword, cat_codes in KEYWORD_INDEX.items():
        if keyword in tl:
            hits |= cat_codes
    return sorted(hits)
