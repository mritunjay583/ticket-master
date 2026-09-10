"""Environment-based application configuration (12-factor).

A single typed ``Settings`` object is the only place environment variables are read.
Nothing else in the codebase should call ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings, loaded from environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "ticket-master"
    environment: Literal["local", "dev", "stage", "prod"] = "local"
    debug: bool = False
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://ticketmaster:ticketmaster@localhost:5432/ticketmaster",
        description="SQLAlchemy database URL (psycopg v3 driver).",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Queue (used from Phase 3 onward) ---
    redis_url: str = "redis://localhost:6379/0"
    queue_backend: Literal["rq", "sqs"] = "rq"
    queue_name: str = "tickets"

    # --- Reliability (Phase 4) ---
    job_max_retries: int = 3  # RQ retries for transient failures (with backoff)
    sweeper_interval_seconds: int = 60  # how often the sweeper scans for stuck PENDING tickets
    sweeper_stale_after_seconds: int = 120  # a PENDING ticket older than this is re-enqueued
    sweeper_batch_size: int = 100  # max stuck tickets re-enqueued per sweep

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (read once per process)."""
    return Settings()
