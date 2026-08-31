"""
Shared Gemini model wrapper with retry/backoff AND per-request model fallback,
for every ADK LlmAgent in the system (specialist scoring, interview, judge,
Q&A extraction).

Passing a bare model name string to LlmAgent(model=...) resolves via ADK's
LLMRegistry to a plain Gemini(model=name) with retry_options=None — zero
retries. A single transient 429 RESOURCE_EXHAUSTED then kills the whole call
immediately. Real trigger (Aug 20): adding the Protect agent (one more
concurrent worker per "Run assessment") and wiring in the Judge step (roughly
doubles LLM calls per Function) landed the same week, pushing total request
volume past what the project's Vertex AI quota tolerates without backing off.

Retry alone was not enough (Aug 31). Sustained load exhausted the
`gemini-3.7-flash` quota specifically: 30 calls in one hour drew 18 429s, the
5-attempt backoff ran out, and `_ResourceExhaustedError` propagated out of
JudgeStep and killed a whole assessment 10 minutes in — with 22 scores and 6
Tiers already persisted. Meanwhile `gemini-3.5-flash` took zero 429s in the
same window, because the two model tiers hold separate quota.

So gemini_model() now also takes a fallback. The policy is deliberately
PER REQUEST and STATELESS:

  * every call tries the primary model first — no circuit breaker, no cooldown,
    no sticky "we're in fallback mode" flag;
  * only after the primary's own retry budget is exhausted with a 429 does that
    ONE request go to the fallback model;
  * the next request starts over at the primary.

Statelessness is the point. A sticky breaker would silently strand the whole
run on the weaker model long after the quota recovered, and the Judge's
accuracy numbers are measured on the primary — we want to be back on it the
moment there is headroom, and we want the logs to show exactly which requests
were not.

Use gemini_model(name) in place of the bare name everywhere an LlmAgent is
constructed — same model, now with retry and fallback.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator

from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError

log = logging.getLogger("csf-gateway.llm")

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


class _FallbackGemini(Gemini):
    """A Gemini that retries a 429-exhausted request once on a second model.

    Only 429 triggers it. Every other ClientError (400 bad request, 403, 404 on
    a bad model name) propagates untouched — those are bugs, and silently
    re-running them on a different model would hide the bug and double the cost.
    """

    fallback_model: str | None = None

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        emitted = False
        try:
            async for response in super().generate_content_async(llm_request, stream=stream):
                emitted = True
                yield response
            return
        except ClientError as ce:
            # `emitted` is the load-bearing guard. generate_content_async is an
            # async GENERATOR: under stream=True the primary can fail partway
            # through, after we have already handed responses to the caller.
            # Restarting on the fallback would then emit a second, overlapping
            # copy of the same answer. Only a request that produced nothing at
            # all is safe to retry.
            if ce.code != 429 or not self.fallback_model or emitted:
                raise
            log.warning(
                "429 on %s after %d retries — failing this ONE request over to %s "
                "(the next request retries %s first)",
                self.model, _RETRY_OPTIONS.attempts, self.fallback_model, self.model,
            )

        async for response in Gemini(
            model=self.fallback_model, retry_options=_RETRY_OPTIONS
        ).generate_content_async(llm_request, stream=stream):
            yield response


def gemini_model(model_name: str, fallback_model: str | None = None) -> Gemini:
    """Wrap a Gemini model name with retry/backoff and optional 429 fallback.
    Pass the RESULT as LlmAgent(model=...) — not the bare model name string.

    fallback_model is only reached when the primary returns 429 *after* its own
    retries. Pass None (the default) to keep the old fail-hard behaviour."""
    if not fallback_model or fallback_model == model_name:
        return Gemini(model=model_name, retry_options=_RETRY_OPTIONS)
    return _FallbackGemini(
        model=model_name,
        fallback_model=fallback_model,
        retry_options=_RETRY_OPTIONS,
    )
