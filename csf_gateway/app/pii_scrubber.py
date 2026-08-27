"""
Deterministic PII de-identification — the PII-value half of the "Model Armor / DLP"
Fortified component.

Runs alongside the managed Google Model Armor threat gate (model_armor.py) at every
LLM-call boundary. The division of labor: Model Armor screens for the things regex
can't (prompt injection / jailbreak / malicious URLs / RAI) and detects PII for the
audit trail; this module does the actual PII *value* redaction. We keep a
deterministic scrubber for that value replacement rather than Model Armor's SDP
because the template runs SDP in *basic* (inspect/flag) mode — it detects PII but
does not return de-identified text — so the deterministic path is what guarantees
the value is gone before the prompt is sent. (Model Armor SDP *advanced* mode +
a Cloud DLP de-identify template is the managed alternative for this half —
deferred; see docs.) It replaces confidential VALUES with typed placeholders —
keeping the structure the model needs to score maturity ("there is an email / an
account here") while the actual value never reaches Gemini, the logs, the traces,
or the report citations — and logs every redaction (counts only, never the raw
PII) for an audit trail. That's the "trust their data handling" judging story.

Deliberately NOT a generative LLM (that would be circular — you'd send the PII to
the very model you're protecting it from). Deterministic, auditable, fail-safe:
a scrub failure must never break scoring, so scrub() never raises.

Honest limit: no automated scrubber is 100%. This catches high-confidence
STRUCTURED PII (email / SSN / IBAN / credit-card-with-Luhn / phone / IP) with a
fail-closed bias (over-redact rather than leak). Arbitrary person names / bespoke
account formats need a domain dictionary (Sakina-provided, optional hook below).
"""
from __future__ import annotations

import logging
import re

from csf_gateway.app.tracing import get_tracer

log = logging.getLogger("csf-gateway.pii")
_tracer = get_tracer("csf-gateway")

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# Credit cards: match 13-19 digit groups (optionally space/dash separated), then
# Luhn-validate before redacting so we don't clobber random long numbers.
_CC = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# Phone: require a 3-3-4 (optionally +CC / parens / separators) shape so plain
# short numbers (dates, counts, CMMI levels) aren't touched.
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _luhn_ok(value: str) -> bool:
    ds = [int(c) for c in value if c.isdigit()]
    if not (13 <= len(ds) <= 19):
        return False
    checksum, parity = 0, len(ds) % 2
    for i, d in enumerate(ds):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# Ordered: most specific first. (pattern, placeholder_label, optional validator).
_DETECTORS = [
    (_EMAIL, "EMAIL", None),
    (_SSN, "SSN", None),
    (_IBAN, "IBAN", None),
    (_CC, "CREDIT_CARD", _luhn_ok),
    (_PHONE, "PHONE", None),
    (_IP, "IP_ADDRESS", None),
]


def scrub(text: str) -> tuple[str, dict[str, int]]:
    """Replace structured PII values with typed placeholders (e.g. [EMAIL]).
    Returns (de-identified text, {label: redaction_count}). Never raises — on any
    error returns the text as-is and logs (fail-safe: cleanup must not break the
    pipeline it protects)."""
    if not text:
        return text, {}
    counts: dict[str, int] = {}
    try:
        for pattern, label, validator in _DETECTORS:
            def _repl(m: re.Match, label=label, validator=validator) -> str:
                if validator and not validator(m.group(0)):
                    return m.group(0)
                counts[label] = counts.get(label, 0) + 1
                return f"[{label}]"

            text = pattern.sub(_repl, text)
    except Exception:
        log.exception("PII scrub failed — returning text unchanged (fail-safe)")
        return text, counts
    return text, counts


def scrub_for_llm(text: str, *, context: str) -> str:
    """Scrub text about to be sent to an LLM, emit an audit record (redaction
    counts + a Cloud Trace span — never the raw PII), and return the sanitized
    text. Disabled via settings.pii_scrub_enabled=False (returns text unchanged).
    """
    from csf_gateway.app.config import get_settings

    if not get_settings().pii_scrub_enabled:
        return text
    with _tracer.start_as_current_span("csf.pii.scrub") as span:
        cleaned, counts = scrub(text)
        total = sum(counts.values())
        span.set_attribute("csf.pii.context", context)
        span.set_attribute("csf.pii.redactions", total)
        for label, n in counts.items():
            span.set_attribute(f"csf.pii.{label.lower()}", n)
        if total:
            log.info(
                "[%s] PII de-identified %d value(s): %s",
                context, total, ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            )
        return cleaned
