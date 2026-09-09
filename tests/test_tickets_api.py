"""API integration tests for the ticket endpoints (require a PostgreSQL test DB)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import requires_db

VALID_TICKET = {
    "customer_name": "Test User",
    "customer_email": "test@example.com",
    "subject": "Cannot login",
    "description": "The app shows an error when I try to log in.",
    "priority": "HIGH",
    "category": "TECHNICAL",
}


@requires_db
def test_create_ticket_returns_201_envelope(client: TestClient) -> None:
    resp = client.post("/api/v1/tickets", json=VALID_TICKET)
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "OPEN"
    assert data["processing_status"] == "PENDING"
    assert data["priority"] == "HIGH"
    assert "id" in data


@requires_db
def test_create_ticket_invalid_email_returns_422(client: TestClient) -> None:
    bad = {**VALID_TICKET, "customer_email": "not-an-email"}
    resp = client.post("/api/v1/tickets", json=bad)
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@requires_db
def test_get_ticket_roundtrip(client: TestClient) -> None:
    created = client.post("/api/v1/tickets", json=VALID_TICKET).json()["data"]
    resp = client.get(f"/api/v1/tickets/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == created["id"]


@requires_db
def test_get_missing_ticket_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/tickets/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TICKET_NOT_FOUND"


@requires_db
def test_list_with_filter_and_pagination(client: TestClient) -> None:
    client.post("/api/v1/tickets", json=VALID_TICKET)
    client.post("/api/v1/tickets", json={**VALID_TICKET, "category": "BILLING"})

    resp = client.get("/api/v1/tickets", params={"status": "OPEN", "page": 1, "page_size": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 2
    assert all(t["status"] == "OPEN" for t in body["data"])

    resp2 = client.get("/api/v1/tickets", params={"category": "BILLING"})
    assert resp2.status_code == 200
    assert all(t["category"] == "BILLING" for t in resp2.json()["data"])


@requires_db
def test_valid_status_transition_and_events(client: TestClient) -> None:
    tid = client.post("/api/v1/tickets", json=VALID_TICKET).json()["data"]["id"]

    resp = client.patch(f"/api/v1/tickets/{tid}/status", json={"status": "IN_PROGRESS"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "IN_PROGRESS"

    events = client.get(f"/api/v1/tickets/{tid}/events").json()["data"]
    types = [e["event_type"] for e in events]
    assert types == ["CREATED", "STATUS_CHANGED"]


@requires_db
def test_invalid_status_transition_returns_409(client: TestClient) -> None:
    tid = client.post("/api/v1/tickets", json=VALID_TICKET).json()["data"]["id"]
    # OPEN -> CLOSED is not allowed
    resp = client.patch(f"/api/v1/tickets/{tid}/status", json={"status": "CLOSED"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"
