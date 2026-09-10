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


class FakeTaskQueue:
    """In-memory TaskQueue for tests — records enqueued jobs instead of hitting Redis.

    Demonstrates the ports payoff: the service is tested with a fake adapter, no Redis needed.
    """

    def __init__(self) -> None:
        self.enqueued: list[tuple[object, tuple[object, ...]]] = []

    def enqueue(self, func: object, *args: object, **kwargs: object) -> str:
        self.enqueued.append((func, args))
        return "fake-job-id"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI TestClient wired to the test database (fresh schema) with a fake task queue."""
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

    # Build the container, then swap the queue adapter for the in-memory fake (no Redis in tests).
    from app.core.container import build_container
    from app.services.ticket_service import TicketService

    c = build_container(settings)
    fake_queue = FakeTaskQueue()
    service = TicketService(c.ticket_repository, c.event_repository, fake_queue)
    object.__setattr__(c, "task_queue", fake_queue)
    object.__setattr__(c, "ticket_service", service)

    from app.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(engine)
    db.dispose_engine()
