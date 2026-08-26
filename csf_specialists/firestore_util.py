"""Shared Firestore async-client cleanup.

`AsyncClient.close()` only closes the HTTP transport — the grpc.aio channel (and
its completion-queue poller thread) is left open. When a client is created inside
a SHORT-LIVED asyncio.run() loop (Streamlit reruns render the report via
asyncio.run; the CLI export scripts likewise), that poller then raises
"RuntimeError: Event loop is closed" on teardown and grpc logs "FD from fork
parent still in poll list". Awaiting the async gRPC transport's close() shuts the
channel cleanly, silencing both. Validated 2026-08-26.

Only needed on the short-lived-loop paths (report build, CLI scripts). The
long-lived gateway (uvicorn) keeps one persistent loop, so its cached clients
never hit this — leave those alone.
"""
from __future__ import annotations


async def aclose_firestore(client) -> None:
    """Best-effort close of an AsyncClient's grpc.aio channel. Never raises —
    cleanup must not break the caller. Uses the private `_firestore_api_internal`
    backing field so it doesn't lazily build the API just to close it."""
    try:
        api = getattr(client, "_firestore_api_internal", None)
        if api is not None:
            await api.transport.close()
    except Exception:  # pragma: no cover - cleanup must never break a report
        pass
