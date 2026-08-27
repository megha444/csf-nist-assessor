"""
Typed environment/config loader.

Reads `.env` at repo root, exposes settings as an immutable Pydantic model,
and provides `get_settings()` as a cached accessor.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    All env-driven configuration for csf-gateway.

    Field names are lower_snake_case; env var names are UPPER_SNAKE_CASE.
    Pydantic-settings does the case mapping automatically.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # GCP / Vertex AI
    google_cloud_project: str
    google_cloud_location: str = "global"  # required for Gemini 3.x on this project
    google_genai_use_vertexai: bool = True

    # Storage (bucket names carry region; not tied to google_cloud_location above)
    gcs_raw_bucket: str
    gcs_artifacts_bucket: str

    # Firestore
    firestore_database: str = "(default)"

    # Models — hackathon requires Gemini 3.5 or newer
    gemini_flash_model: str = "gemini-3.5-flash"
    gemini_pro_model: str = "gemini-3.7-flash"   # 3.x has no Pro tier; newer Flash plays the Judge role
    embedding_model: str = "text-embedding-004"
    embedding_dim: int = 768

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "csf_chunks"

    # Ingest limits
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, description="20 MB per file")
    chunk_target_tokens: int = 800
    chunk_overlap_tokens: int = 100
    chunk_max_tokens: int = 1200

    # Agent Gateway policy — API key required on every route except /health.
    # Unset (local dev default) disables the key check but rate limiting still applies.
    gateway_api_key: str | None = None
    gateway_rate_limit_per_minute: int = 2000

    # Model Armor / DLP (Fortified) — deterministic PII de-identification before
    # every LLM call (csf_gateway/app/pii_scrubber.py). On by default; False =
    # identity pass-through (no scrubbing).
    pii_scrub_enabled: bool = True

    # Model Armor (Fortified) — managed Google threat gate at every LLM boundary
    # (csf_gateway/app/model_armor.py): prompt-injection / jailbreak / malicious-URL
    # / RAI screening, plus PII detection for the audit trail. Complements the regex
    # scrubber (which does the actual PII value redaction). Disabled by default so
    # local dev needs no API/creds; enable in the deployed env via MODEL_ARMOR_ENABLED.
    model_armor_enabled: bool = False
    model_armor_location: str = "us"  # region-locked; template lives in the `us` multi-region
    model_armor_template_id: str = "my-test-template"
    # Hard-block the run on a confirmed injection/jailbreak. Default False = log a
    # security warning and proceed (a false positive must never sink a live run);
    # flip True to demonstrate a live block against a crafted injection prompt.
    model_armor_block_on_injection: bool = False


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings singleton. Safe to call from anywhere.

    Also mirrors the Vertex AI vars into the real process environment
    (os.environ). pydantic-settings only populates this Settings object from
    `.env` — it never touches os.environ. But ADK's LlmAgent (and the raw
    google-genai SDK, when auto-configuring) build their own internal client
    by reading these exact env vars directly, not through our Settings class.
    Without this, ADK-based agents fail with a "No API key was provided"
    error even though `.env` has the right values — they're just invisible
    to anything that isn't going through get_settings().
    """
    settings = Settings()
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE" if settings.google_genai_use_vertexai else "FALSE")
    return settings
