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

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (read once per process)."""
    return Settings()
