"""
Agent Gateway policy enforcement: API-key auth + per-key rate limiting.

csf-gateway is deployed `--allow-unauthenticated` (Cloud Run IAM is bypassed
entirely for this service), so today anyone with the URL can call every
route. This module is the actual enforcement layer for that: every router
except /health requires a valid `X-API-Key` header, and each key is capped
to a request budget per minute.
"""
from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from .config import get_settings

log = logging.getLogger("csf-gateway.security")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Sliding-window request timestamps per identity: a real API key for successful
# callers, "local-dev" when no key is configured, or "unauthenticated:<ip>" for
# a failed attempt (see _client_ip — per-sender, not one global bucket, so one
# flooding source can't collaterally lock out every other caller's ability to
# even get a clean 401). In-memory only — correct for a single Cloud Run
# instance, which is the realistic case here (min-instances=0, one demo/judging
# client at a time); doesn't share state across replicas if traffic ever
# justified scaling past one instance for real.
_request_log: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """
    Best-effort caller identity for bucketing failed-auth attempts, since
    there's no valid key yet to key off of. Cloud Run's own frontend sets
    X-Forwarded-For from the actual observed connection — the first entry is
    the real client and isn't something a caller can forge by sending their
    own X-Forwarded-For before it ever reaches Cloud Run. This trust
    assumption only holds behind the real Cloud Run deployment, though: local
    dev (bare uvicorn, nothing in front of it) has no proxy enforcing that, so
    a local caller could freely spoof the header — acceptable, since local
    dev isn't the surface this is actually defending.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _mask(identity: str) -> str:
    """Never write a real API key to logs in full — a short prefix is enough to
    debug with, and can't be replayed. IPs and "local-dev" aren't secrets."""
    if identity == "local-dev" or identity.startswith("unauthenticated:"):
        return identity
    return f"{identity[:6]}…"


def _check_rate_limit(identity: str, limit_per_minute: int) -> None:
    now = time.monotonic()
    window_start = now - 60.0
    entry = _request_log[identity]
    while entry and entry[0] < window_start:
        entry.popleft()
    if len(entry) >= limit_per_minute:
        log.warning("rate limit exceeded for %s", _mask(identity))
        raise HTTPException(status_code=429, detail="rate limit exceeded — try again shortly")
    entry.append(now)


def require_api_key(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
    """
    FastAPI dependency: validates X-API-Key and enforces a rate limit.
    Successful callers are throttled per API key (the real identity of a
    legitimate consumer); failed attempts are throttled per source IP, not
    keyed off the attempted key value — an attacker can't dodge the limit by
    sending a different garbage key on every request, since it's the sender
    that's tracked, not the guess. Wire into a router via
    `include_router(..., dependencies=[Depends(require_api_key)])`.

    GATEWAY_API_KEY unset (local dev default) skips the key check but still
    rate-limits, keyed by a shared "local-dev" bucket.
    """
    settings = get_settings()
    if settings.gateway_api_key:
        # Constant-time comparison — a plain `!=` on a static shared secret is a
        # real (if minor) timing side-channel; hmac.compare_digest costs nothing here.
        valid = bool(api_key) and hmac.compare_digest(api_key, settings.gateway_api_key)
        if not valid:
            ip_bucket = f"unauthenticated:{_client_ip(request)}"
            _check_rate_limit(ip_bucket, settings.gateway_rate_limit_per_minute)
            log.warning("rejected request with %s", "no X-API-Key" if not api_key else "invalid X-API-Key")
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
        identity = api_key
    else:
        identity = "local-dev"
    _check_rate_limit(identity, settings.gateway_rate_limit_per_minute)
    return identity
