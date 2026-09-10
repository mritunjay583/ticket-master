"""Integration test for the process_ticket job (requires the test DB, no Redis needed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import requires_db


@requires_db
def test_process_ticket_populates_result_and_flips_status(client: TestClient) -> None:
    # Create a ticket via the API (enqueue is faked, so nothing runs automatically).
    payload = {
        "customer_name": "Test User",
        "customer_email": "test@example.com",
        "subject": "App error on login",
        "description": "Login failed with an error message.",
        "priority": "MEDIUM",
        "category": "TECHNICAL",
    }
    tid = client.post("/api/v1/tickets", json=payload).json()["data"]["id"]

    # Run the job directly (as the worker would).
    from app.worker.tasks import process_ticket

    process_ticket(tid)

    # Ticket is now processed: status DONE, priority/department applied.
    body = client.get(f"/api/v1/tickets/{tid}").json()["data"]
    assert body["processing_status"] == "DONE"
    assert body["priority"] == "HIGH"  # "error"/"failed" -> HIGH
    assert body["department"] == "ENGINEERING"  # TECHNICAL -> ENGINEERING

    # A PROCESSED event was recorded.
    events = client.get(f"/api/v1/tickets/{tid}/events").json()["data"]
    assert [e["event_type"] for e in events] == ["CREATED", "PROCESSED"]


@requires_db
def test_process_ticket_is_idempotent(client: TestClient) -> None:
    payload = {
        "customer_name": "T",
        "customer_email": "t@example.com",
        "subject": "Question",
        "description": "how do i export data",
        "priority": "MEDIUM",
        "category": "GENERAL",
    }
    tid = client.post("/api/v1/tickets", json=payload).json()["data"]["id"]

    from app.worker.tasks import process_ticket

    process_ticket(tid)
    process_ticket(tid)  # second run must be a safe no-op (already DONE)

    events = client.get(f"/api/v1/tickets/{tid}/events").json()["data"]
    # Only one PROCESSED event despite running twice.
    assert [e["event_type"] for e in events].count("PROCESSED") == 1


@requires_db
def test_create_enqueues_processing_job(client: TestClient) -> None:
    from app.core.container import get_container

    payload = {
        "customer_name": "T",
        "customer_email": "t@example.com",
        "subject": "Hello",
        "description": "neutral text",
        "priority": "MEDIUM",
        "category": "GENERAL",
    }
    client.post("/api/v1/tickets", json=payload)

    # The fake queue recorded exactly one enqueued job.
    queue = get_container().task_queue
    assert len(queue.enqueued) == 1  # type: ignore[attr-defined]
