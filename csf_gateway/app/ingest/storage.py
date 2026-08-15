"""
E1 — Cloud Storage raw upload.

Called from the POST /documents route (Phase F) BEFORE the async ingest kicks
off, so if GCS is down the user gets an immediate 500 rather than a silent
background failure.
"""
from __future__ import annotations

import logging

from google.cloud import storage

from ..config import get_settings

log = logging.getLogger("csf-gateway.ingest.storage")

_client: storage.Client | None = None


def _client_get() -> storage.Client:
    global _client
    if _client is None:
        s = get_settings()
        _client = storage.Client(project=s.google_cloud_project)
    return _client


def upload_raw(
    session_id: str,
    doc_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    """
    Upload raw file bytes to `gs://<raw-bucket>/<session_id>/<doc_id>/<filename>`.
    Returns the gs:// URI.
    """
    s = get_settings()
    bucket = _client_get().bucket(s.gcs_raw_bucket)
    blob_path = f"{session_id}/{doc_id}/{filename}"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    uri = f"gs://{s.gcs_raw_bucket}/{blob_path}"
    log.info("uploaded %d bytes → %s", len(data), uri)
    return uri
