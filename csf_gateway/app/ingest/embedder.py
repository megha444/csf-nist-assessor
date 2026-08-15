"""
E7 — Batch embedder via Vertex AI text-embedding-004.

Uses the google-genai SDK (same client as pdf_parser). Text embedding is a
sync API; async here just means the caller doesn't block the event loop while
each batch flies to Vertex.

Batching: text-embedding-004 accepts up to 250 inputs per request; we play it
safe at 100 to leave headroom for retries.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from google import genai
from google.genai import types

from ..config import get_settings

log = logging.getLogger("csf-gateway.ingest.embed")

TaskType = Literal[
    "RETRIEVAL_QUERY",
    "RETRIEVAL_DOCUMENT",
    "SEMANTIC_SIMILARITY",
    "CLASSIFICATION",
    "CLUSTERING",
]

_client: genai.Client | None = None


def _client_get() -> genai.Client:
    global _client
    if _client is None:
        s = get_settings()
        _client = genai.Client(
            vertexai=True,
            project=s.google_cloud_project,
            location=s.google_cloud_location,
        )
    return _client


async def embed_texts(
    texts: list[str],
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    batch_size: int = 100,
) -> list[list[float]]:
    """
    Batch embed a list of texts. Returns 768-dim vectors, one per input, in order.
    """
    s = get_settings()
    client = _client_get()
    results: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = await client.aio.models.embed_content(
            model=s.embedding_model,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=s.embedding_dim,
            ),
        )
        results.extend([emb.values for emb in response.embeddings])
        log.info("embedded batch %d-%d (%d vectors)", i, i + len(batch), len(batch))

    return results


async def embed_query(text: str) -> list[float]:
    """Convenience for single-query embedding at retrieval time."""
    [vec] = await embed_texts([text], task_type="RETRIEVAL_QUERY")
    return vec
