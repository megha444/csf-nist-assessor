"""
Typed environment/config loader for csf-coordinator.

Same pattern as csf_gateway/app/config.py — reads `.env` at repo root,
exposes settings as an immutable Pydantic model, cached accessor.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """
    Env-driven configuration for csf-coordinator.

    Field names are lower_snake_case; env var names are UPPER_SNAKE_CASE.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    google_cloud_project: str
    firestore_database: str = "(default)"

    # Pub/Sub — topics already provisioned in GCP by infra/setup.sh.
    pubsub_dispatch_prefix: str = "csf-dispatch-"
    pubsub_results_topic: str = "csf-results"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Safe to call from anywhere."""
    return Settings()
