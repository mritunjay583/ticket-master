"""SQLAlchemy adapter implementing the ``TicketEventRepository`` port."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket_event import TicketEvent


class SqlAlchemyEventRepository:
    """Data access for the append-only ticket-event log."""

    def add(self, session: Session, event: TicketEvent) -> TicketEvent:
        session.add(event)
        session.flush()
        return event

    def list_for_ticket(self, session: Session, ticket_id: UUID) -> list[TicketEvent]:
        stmt = (
            select(TicketEvent)
            .where(TicketEvent.ticket_id == ticket_id)
            .order_by(TicketEvent.created_at.asc())
        )
        return list(session.scalars(stmt).all())
