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
from fastapi.openapi.utils import get_openapi

from .config import get_settings
from . import documents as documents_module
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
app.include_router(documents_module.router)


def _swagger_friendly_openapi() -> dict:
    """
    Rewrite the auto-generated OpenAPI so Swagger UI renders file-upload fields
    as real file pickers (multi-select) instead of text inputs.

    FastAPI (OpenAPI 3.1) emits `type: string, contentMediaType: application/octet-stream`
    for binary payloads. Swagger UI's file picker still keys off the older
    `format: binary`. We patch the schema in place to add that alias.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for comp in schema.get("components", {}).get("schemas", {}).values():
        if not isinstance(comp, dict):
            continue
        for prop in comp.get("properties", {}).values():
            # array-of-files case
            items = prop.get("items")
            if isinstance(items, dict) and items.get("contentMediaType") == "application/octet-stream":
                items["format"] = "binary"
            # single-file case
            if prop.get("contentMediaType") == "application/octet-stream":
                prop["format"] = "binary"
    app.openapi_schema = schema
    return schema


app.openapi = _swagger_friendly_openapi


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
        client = QdrantClient(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            timeout=2.0,
            check_compatibility=False,
        )
        info = client.get_collection(s.qdrant_collection)
        return f"ok ({info.points_count} points)"
    except Exception as e:  # noqa: BLE001 — health check must never raise
        return f"error: {type(e).__name__}: {e}"
