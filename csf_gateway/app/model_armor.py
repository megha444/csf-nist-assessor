"""
Model Armor — managed LLM-boundary threat screening (real GCP service).

Companion to pii_scrubber.py. The regex scrubber de-identifies PII *values*;
Model Armor is the managed Google threat gate at the same boundary, screening for
the things regex fundamentally cannot: prompt injection / jailbreak, malicious
URLs, and responsible-AI violations. One `sanitize_user_prompt` call per LLM
boundary against a regional template (the `us` multi-region template
`my-test-template`: PI/jailbreak + malicious-URI + RAI + SDP-basic,
INSPECT_AND_BLOCK). Model Armor is a Security Command Center product.

Two deliberate design choices:

1. **Fail-OPEN on screening errors.** A screening failure (API down, quota,
   creds, oversized prompt) must never break scoring — the regex scrubber still
   de-identifies PII regardless, so a Model Armor outage degrades to "no injection
   screening on this call," logged, never a crash. screen_prompt() therefore never
   raises on an API error.

2. **We do NOT block on PII.** Our evidence legitimately contains PII (that's the
   whole point — we're scoring a company's real documents), and the template's SDP
   is in *basic* mode (detect/flag, no de-identified text returned). So PII
   findings are logged for the audit trail only (counts + info-types, never raw
   values); the regex scrubber does the actual value redaction. The block-worthy
   signal is prompt injection / jailbreak — and even that is hard-blocked only when
   settings.model_armor_block_on_injection is True (default: log a security warning
   and proceed, so a false positive never sinks a live run). Turn the flag on to
   demonstrate a live block against a crafted injection.

Runs the sync REST client under asyncio.to_thread — deliberately avoiding a
grpc.aio async client, whose event-loop binding has repeatedly caused
"Event loop is closed" errors elsewhere in this codebase (see memory_bank.py).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from csf_gateway.app.tracing import get_tracer

log = logging.getLogger("csf-gateway.model_armor")
_tracer = get_tracer("csf-gateway")

_client = None  # lazy singleton (sync ModelArmorClient, REST transport)
_client_failed = False  # once import/init fails, stop retrying every call


class ModelArmorBlocked(Exception):
    """Raised only as a deliberate policy action: a confirmed prompt-injection /
    jailbreak while settings.model_armor_block_on_injection is True. Never raised
    on a screening *failure* (that path fails open)."""

    def __init__(self, context: str, confidence: str):
        self.context = context
        self.confidence = confidence
        super().__init__(f"Model Armor blocked prompt [{context}]: injection/jailbreak ({confidence})")


@dataclass
class ModelArmorVerdict:
    """Result of one screening call. `available=False` means the call did not
    complete (disabled, or a fail-open error) — treat as 'not screened', not
    'clean'."""

    available: bool = False
    injection_match: bool = False
    injection_confidence: str | None = None
    malicious_uri: bool = False
    rai_match: bool = False
    pii_findings: dict[str, int] = field(default_factory=dict)

    @property
    def threat(self) -> bool:
        """Any block-worthy threat (injection / malicious URL / RAI). PII is not a
        threat here — it's expected in evidence and handled by the scrubber."""
        return self.injection_match or self.malicious_uri or self.rai_match


def _get_client():
    """Build the sync Model Armor REST client once. Returns None if the library
    isn't installed or the client can't be constructed (fail-open)."""
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import modelarmor_v1

        from csf_gateway.app.config import get_settings

        s = get_settings()
        endpoint = f"modelarmor.{s.model_armor_location}.rep.googleapis.com"
        _client = modelarmor_v1.ModelArmorClient(
            transport="rest",
            client_options=ClientOptions(api_endpoint=endpoint),
        )
    except Exception:
        _client_failed = True
        log.warning("Model Armor client unavailable — screening disabled (fail-open)", exc_info=True)
        return None
    return _client


def _parse(resp) -> ModelArmorVerdict:
    """Defensively extract the verdict from a SanitizeUserPromptResponse. Any
    shape surprise degrades to 'available but empty' rather than raising."""
    v = ModelArmorVerdict(available=True)
    try:
        results = resp.sanitization_result.filter_results
    except Exception:
        return v

    def _get(key):
        # filter_results behaves like a mapping; be tolerant of proto MapField.
        try:
            return results[key] if key in results else None
        except Exception:
            try:
                return dict(results).get(key)
            except Exception:
                return None

    pj = _get("pi_and_jailbreak")
    if pj is not None:
        try:
            r = pj.pi_and_jailbreak_filter_result
            if r.match_state.name == "MATCH_FOUND":
                v.injection_match = True
                v.injection_confidence = getattr(r.confidence_level, "name", None)
        except Exception:
            pass

    mu = _get("malicious_uris")
    if mu is not None:
        try:
            if mu.malicious_uri_filter_result.match_state.name == "MATCH_FOUND":
                v.malicious_uri = True
        except Exception:
            pass

    rai = _get("rai")
    if rai is not None:
        try:
            if rai.rai_filter_result.match_state.name == "MATCH_FOUND":
                v.rai_match = True
        except Exception:
            pass

    sdp = _get("sdp")
    if sdp is not None:
        try:
            for f in sdp.sdp_filter_result.inspect_result.findings:
                it = getattr(f, "info_type", "PII") or "PII"
                v.pii_findings[it] = v.pii_findings.get(it, 0) + 1
        except Exception:
            pass

    return v


async def screen_prompt(text: str, *, context: str) -> ModelArmorVerdict:
    """Screen a single assembled prompt (one Model Armor call).

    NOTE ON GRANULARITY: an injection embedded in a large assembled prompt is
    diluted below threshold by the surrounding *trusted* scaffolding — verified
    live (a raw answer flags at confidence 2–3 alone, but is missed inside the full
    interview prompt even at LOW). For reliable injection detection, screen the raw
    untrusted inputs with screen_untrusted() at their point of entry. This function
    is kept for the scoring/judge boundaries (PII-detection audit) pending the
    ingest-time move of evidence screening.

    Fail-open (never raises on a screening error); raises ModelArmorBlocked only on
    a confirmed injection when settings.model_armor_block_on_injection is True.
    No-op when settings.model_armor_enabled is False.
    """
    from csf_gateway.app.config import get_settings

    if not get_settings().model_armor_enabled or not text:
        return ModelArmorVerdict(available=False)
    with _tracer.start_as_current_span("csf.model_armor") as span:
        verdict = await _sanitize_once(text)
        _emit_and_block(span, context, verdict)
        return verdict


# Injection confidence labels, ranked so the aggregate keeps the most severe.
_CONFIDENCE_RANK = {"LOW": 1, "LOW_AND_ABOVE": 1, "MEDIUM": 2, "MEDIUM_AND_ABOVE": 2, "HIGH": 3}


def _merge(a: ModelArmorVerdict, b: ModelArmorVerdict) -> ModelArmorVerdict:
    """Combine two per-item verdicts: any-match wins, highest injection confidence
    survives, PII finding counts sum."""
    out = ModelArmorVerdict(
        available=a.available or b.available,
        injection_match=a.injection_match or b.injection_match,
        malicious_uri=a.malicious_uri or b.malicious_uri,
        rai_match=a.rai_match or b.rai_match,
    )
    labels = [c for c in (a.injection_confidence, b.injection_confidence) if c]
    if labels:
        out.injection_confidence = max(labels, key=lambda c: _CONFIDENCE_RANK.get(c, 0))
    for src in (a.pii_findings, b.pii_findings):
        for k, n in src.items():
            out.pii_findings[k] = out.pii_findings.get(k, 0) + n
    return out


async def _sanitize_once(text: str) -> ModelArmorVerdict:
    """One sanitize_user_prompt call on one string. Fail-open: returns
    available=False (never raises) on empty text / missing client / API error."""
    if not text or not text.strip():
        return ModelArmorVerdict(available=False)
    client = _get_client()
    if client is None:
        return ModelArmorVerdict(available=False)
    try:
        from google.cloud import modelarmor_v1

        from csf_gateway.app.config import get_settings

        s = get_settings()
        template = (
            f"projects/{s.google_cloud_project}"
            f"/locations/{s.model_armor_location}"
            f"/templates/{s.model_armor_template_id}"
        )
        req = modelarmor_v1.SanitizeUserPromptRequest(
            name=template,
            user_prompt_data=modelarmor_v1.DataItem(text=text),
        )
        resp = await asyncio.to_thread(client.sanitize_user_prompt, request=req)
        return _parse(resp)
    except Exception:
        # Fail-open: screening is best-effort; the scrubber still protects PII.
        log.warning("Model Armor screening failed — proceeding unscreened (fail-open)", exc_info=True)
        return ModelArmorVerdict(available=False)


def _emit_and_block(span, context: str, verdict: ModelArmorVerdict) -> None:
    """Record the verdict on the span + audit log (counts/verdicts only, never raw
    PII), then raise ModelArmorBlocked if an injection was found and blocking is on."""
    from csf_gateway.app.config import get_settings

    span.set_attribute("csf.model_armor.context", context)
    span.set_attribute("csf.model_armor.available", verdict.available)
    span.set_attribute("csf.model_armor.injection", verdict.injection_match)
    span.set_attribute("csf.model_armor.malicious_uri", verdict.malicious_uri)
    span.set_attribute("csf.model_armor.rai", verdict.rai_match)
    span.set_attribute("csf.model_armor.pii_findings", sum(verdict.pii_findings.values()))
    if verdict.injection_confidence:
        span.set_attribute("csf.model_armor.injection_confidence", verdict.injection_confidence)

    if verdict.injection_match:
        log.warning("[%s] Model Armor: PROMPT INJECTION / JAILBREAK detected (confidence=%s)",
                    context, verdict.injection_confidence)
    if verdict.malicious_uri:
        log.warning("[%s] Model Armor: malicious URI detected", context)
    if verdict.rai_match:
        log.warning("[%s] Model Armor: responsible-AI filter matched", context)
    if verdict.pii_findings:
        log.info("[%s] Model Armor: PII detected (audit) %s",
                 context, ", ".join(f"{k}={n}" for k, n in sorted(verdict.pii_findings.items())))

    if verdict.injection_match and get_settings().model_armor_block_on_injection:
        span.set_attribute("csf.model_armor.blocked", True)
        raise ModelArmorBlocked(context, verdict.injection_confidence or "unknown")


async def screen_untrusted(items: list[str], *, context: str) -> ModelArmorVerdict:
    """Screen raw untrusted user inputs (interview answers, uploaded document text,
    evidence chunks) for injection at their natural granularity — EACH item on its
    own — so an embedded injection isn't diluted below threshold by a large trusted
    prompt. This is the failure mode that makes screening the assembled prompt miss
    what screening the raw input catches. Aggregates to the highest-severity verdict.

    Fail-open (never raises on a screening error); raises ModelArmorBlocked once, on
    a confirmed injection in any item, when settings.model_armor_block_on_injection
    is True. No-op when settings.model_armor_enabled is False.
    """
    from csf_gateway.app.config import get_settings

    if not get_settings().model_armor_enabled:
        return ModelArmorVerdict(available=False)
    candidates = [i for i in items if i and i.strip()]
    if not candidates:
        return ModelArmorVerdict(available=False)
    with _tracer.start_as_current_span("csf.model_armor") as span:
        span.set_attribute("csf.model_armor.items", len(candidates))
        agg = ModelArmorVerdict(available=False)
        for item in candidates:
            agg = _merge(agg, await _sanitize_once(item))
        _emit_and_block(span, context, agg)
        return agg
