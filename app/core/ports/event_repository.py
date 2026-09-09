"""Port: ticket event/history persistence (append-only audit trail)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ticket_event import TicketEvent


@runtime_checkable
class TicketEventRepository(Protocol):
    """Data-access contract for the immutable ticket-event log."""

    def add(self, session: Session, event: TicketEvent) -> TicketEvent: ...

    def list_for_ticket(self, session: Session, ticket_id: UUID) -> list[TicketEvent]: ...
