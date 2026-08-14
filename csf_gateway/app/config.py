"""
Typed environment/config loader.

Reads `.env` at repo root, exposes settings as an immutable Pydantic model,
and provides `get_settings()` as a cached accessor.
"""
from __future__ import annotations

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


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Safe to call from anywhere."""
    return Settings()
