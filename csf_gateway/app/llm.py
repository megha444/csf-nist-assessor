"""
Shared Gemini model wrapper with retry/backoff, for every ADK LlmAgent in the
system (specialist scoring, interview, judge, Q&A extraction).

Passing a bare model name string to LlmAgent(model=...) resolves via ADK's
LLMRegistry to a plain Gemini(model=name) with retry_options=None — zero
retries. A single transient 429 RESOURCE_EXHAUSTED then kills the whole call
immediately. Real trigger (Aug 20): adding the Protect agent (one more
concurrent worker per "Run assessment") and wiring in the Judge step (roughly
doubles LLM calls per Function) landed the same week, pushing total request
volume past what the project's Vertex AI quota tolerates without backing off.

Use gemini_model(name) in place of the bare name everywhere an LlmAgent is
constructed — same model, now with retry.
"""
from __future__ import annotations

from google.adk.models import Gemini
from google.genai import types

_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=5,
    initial_delay=2.0,
    max_delay=30.0,
    exp_base=2.0,
    jitter=1.0,
    # 429 and 5xx are ADK's own defaults when http_status_codes is left unset —
    # explicit here so the retryable set is visible without reading ADK source.
    http_status_codes=[408, 429, 500, 502, 503, 504],
)


def gemini_model(model_name: str) -> Gemini:
    """Wrap a Gemini model name with retry/backoff for transient errors.
    Pass the RESULT as LlmAgent(model=...) — not the bare model name string."""
    return Gemini(model=model_name, retry_options=_RETRY_OPTIONS)
