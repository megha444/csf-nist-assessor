"""
csf-gateway FastAPI entrypoint.

The gateway is the public-facing service of the CSF Assessor Fleet. It hosts:
- Streamlit UI (added later)
- REST API for session, ingest, chat, run, report (routes added phase by phase)

For now: `/health` returns a basic liveness check with the Qdrant and Firestore
connection status so we can verify the deploy target early.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from . import sessions as sessions_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("csf-gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info("csf-gateway starting up")
    log.info("GCP project: %s", s.google_cloud_project)
    log.info("Qdrant URL:  %s", s.qdrant_url)
    log.info("Qdrant collection: %s", s.qdrant_collection)
    yield
    log.info("csf-gateway shutting down")


app = FastAPI(
    title="csf-gateway",
    version="0.1.0",
    description="CSF Assessor Fleet — public gateway (ingest, session, chat, run, report)",
    lifespan=lifespan,
)

app.include_router(sessions_module.router)


@app.get("/health")
async def health() -> dict:
    """Liveness + dependency probe. Cheap enough to poll every second."""
    s = get_settings()
    checks = {
        "app": "ok",
        "qdrant": _check_qdrant(),
        "gcp_project": s.google_cloud_project,
    }
    checks["status"] = "healthy" if checks["qdrant"].startswith("ok") else "degraded"
    return checks


def _check_qdrant() -> str:
    """Fast, non-throwing Qdrant probe. Returns 'ok' or an error string."""
    try:
        from qdrant_client import QdrantClient

        s = get_settings()
        client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=2.0)
        info = client.get_collection(s.qdrant_collection)
        return f"ok ({info.points_count} points)"
    except Exception as e:  # noqa: BLE001 — health check must never raise
        return f"error: {type(e).__name__}: {e}"
