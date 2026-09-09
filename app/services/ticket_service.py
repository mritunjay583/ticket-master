"""Ticket domain service.

Orchestrates business logic and owns the transaction boundary (Unit of Work). Depends only on the
repository *ports* (injected) — never on SQLAlchemy directly — so it stays storage-agnostic and
easily testable with fake repositories.
"""

from __future__ import annotations

from uuid import UUID

from app.core.db import session_scope
from app.core.errors import NotFoundError
from app.core.ports.event_repository import TicketEventRepository
from app.core.ports.ticket_repository import TicketFilter, TicketRepository
from app.models.ticket import Ticket
from app.models.ticket_event import TicketEvent
from app.schemas.enums import EventType, TicketStatus
from app.schemas.ticket import CreateTicketRequest
from app.services.state_machine import validate_transition


class TicketService:
    """Business operations for tickets."""

    def __init__(
        self,
        ticket_repository: TicketRepository,
        event_repository: TicketEventRepository,
    ) -> None:
        self._tickets = ticket_repository
        self._events = event_repository

    def create_ticket(self, payload: CreateTicketRequest) -> Ticket:
        """Create a ticket (status OPEN) and record a CREATED event, atomically."""
        with session_scope() as session:
            ticket = Ticket(
                customer_name=payload.customer_name,
                customer_email=payload.customer_email,
                subject=payload.subject,
                description=payload.description,
                priority=payload.priority,
                category=payload.category,
                status=TicketStatus.OPEN,
            )
            self._tickets.create(session, ticket)
            self._events.add(
                session,
                TicketEvent(
                    ticket_id=ticket.id,
                    event_type=EventType.CREATED,
                    to_status=TicketStatus.OPEN,
                    actor=payload.customer_email,
                ),
            )
            # commit happens on scope exit; refresh so returned object has DB-side defaults
            session.flush()
            session.refresh(ticket)
            session.expunge(ticket)
            return ticket

    def get_ticket(self, ticket_id: UUID) -> Ticket:
        """Return a ticket or raise NotFoundError (404)."""
        with session_scope() as session:
            ticket = self._tickets.get_by_id(session, ticket_id)
            if ticket is None:
                raise NotFoundError(
                    f"Ticket {ticket_id} not found.", code="TICKET_NOT_FOUND"
                )
            session.expunge(ticket)
            return ticket

    def list_tickets(
        self, *, filters: TicketFilter, page: int, page_size: int
    ) -> tuple[list[Ticket], int]:
        """Return a page of tickets and the total matching count."""
        with session_scope() as session:
            tickets, total = self._tickets.list(
                session, filters=filters, page=page, page_size=page_size
            )
            for t in tickets:
                session.expunge(t)
            return tickets, total

    def update_status(
        self, ticket_id: UUID, target: TicketStatus, actor: str | None
    ) -> Ticket:
        """Change a ticket's status via the state machine; record a STATUS_CHANGED event."""
        with session_scope() as session:
            ticket = self._tickets.get_by_id(session, ticket_id)
            if ticket is None:
                raise NotFoundError(
                    f"Ticket {ticket_id} not found.", code="TICKET_NOT_FOUND"
                )

            current = ticket.status
            validate_transition(current, target)  # raises InvalidTransitionError (409) if illegal

            ticket.status = target
            self._tickets.update(session, ticket)
            self._events.add(
                session,
                TicketEvent(
                    ticket_id=ticket.id,
                    event_type=EventType.STATUS_CHANGED,
                    from_status=current,
                    to_status=target,
                    actor=actor,
                ),
            )
            session.flush()
            session.refresh(ticket)
            session.expunge(ticket)
            return ticket

    def get_ticket_events(self, ticket_id: UUID) -> list[TicketEvent]:
        """Return a ticket's audit history (404 if the ticket does not exist)."""
        with session_scope() as session:
            ticket = self._tickets.get_by_id(session, ticket_id)
            if ticket is None:
                raise NotFoundError(
                    f"Ticket {ticket_id} not found.", code="TICKET_NOT_FOUND"
                )
            events = self._events.list_for_ticket(session, ticket_id)
            for e in events:
                session.expunge(e)
            return events
