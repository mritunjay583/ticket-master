"""Tests for the reliability sweeper (requires the test DB; monkeypatches the queue — no Redis)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import requires_db

VALID_TICKET = {
    "customer_name": "Sweeper Test",
    "customer_email": "sweep@example.com",
    "subject": "Neutral subject",
    "description": "some neutral description",
    "priority": "MEDIUM",
    "category": "GENERAL",
}


def _patch_sweeper_queue(monkeypatch, enqueued: list[str]) -> None:
    """Replace the Redis/Queue the sweeper uses with fakes that just record enqueued ids."""

    class _FakeQueue:
        def __init__(self, *a, **k) -> None: ...
        def enqueue(self, func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            enqueued.append(args[0])
            return object()

    class _FakeRedis:
        @staticmethod
        def from_url(url: str) -> None:
            return None

    import app.worker.sweeper as sweeper_mod

    monkeypatch.setattr(sweeper_mod, "Queue", _FakeQueue)
    monkeypatch.setattr(sweeper_mod, "Redis", _FakeRedis)


@requires_db
def test_sweeper_reenqueues_stale_pending_ticket(client: TestClient, monkeypatch) -> None:
    # Create a ticket (fake queue in tests, so it stays PENDING — nothing processed it).
    tid = client.post("/api/v1/tickets", json=VALID_TICKET).json()["data"]["id"]

    # Make it "stale" by backdating created_at beyond the stale threshold.
    from uuid import UUID

    from app.core.db import session_scope
    from app.models.ticket import Ticket

    with session_scope() as session:
        ticket = session.get(Ticket, UUID(tid))
        assert ticket is not None
        ticket.created_at = datetime.now(UTC) - timedelta(seconds=999)

    # Capture what the sweeper enqueues (patch the Queue used inside the sweeper).
    enqueued: list[str] = []
    _patch_sweeper_queue(monkeypatch, enqueued)

    import app.worker.sweeper as sweeper_mod

    count = sweeper_mod.sweep_pending_tickets()

    assert count == 1
    assert tid in enqueued


@requires_db
def test_sweeper_ignores_fresh_and_done_tickets(client: TestClient, monkeypatch) -> None:
    # A fresh PENDING ticket (not stale yet) should NOT be swept.
    client.post("/api/v1/tickets", json=VALID_TICKET)

    enqueued: list[str] = []
    _patch_sweeper_queue(monkeypatch, enqueued)

    import app.worker.sweeper as sweeper_mod

    count = sweeper_mod.sweep_pending_tickets()
    assert count == 0
    assert enqueued == []
