"""Shared test fixtures.

API tests need a real PostgreSQL (the models use PG-specific types like UUID/JSONB/native enums).
Tests requiring the DB are skipped automatically if it is unreachable, so the pure-unit suite still
runs anywhere. Point at a DB with the TEST_DATABASE_URL env var (defaults to the local compose DB).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://ticketmaster:ticketmaster@localhost:5432/ticketmaster",
)


def _database_available(url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(TEST_DATABASE_URL),
    reason="PostgreSQL not reachable (start it with `docker compose up -d db` + run migrations)",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI TestClient wired to the test database with a fresh schema."""
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    # Reset cached singletons so the app picks up TEST_DATABASE_URL.
    from app.core import config, container, db

    config.get_settings.cache_clear()
    container._container = None
    db.dispose_engine()

    from app.core.config import get_settings
    from app.core.db import init_engine
    from app.models import Base

    settings = get_settings()
    engine = init_engine(settings)

    # Create a clean schema for the test module.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from app.main import create_app

    app = create_app(settings)
    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    db.dispose_engine()
