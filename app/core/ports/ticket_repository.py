"""Port: ticket persistence.

Implemented by a SQLAlchemy adapter today; any store can be substituted by writing a new class
that satisfies this interface and wiring it in ``app.core.container``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.schemas.enums import TicketCategory, TicketPriority, TicketStatus


@dataclass(frozen=True)
class TicketFilter:
    """Optional filters for listing tickets (all ``None`` = no filtering)."""

    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    category: TicketCategory | None = None


@runtime_checkable
class TicketRepository(Protocol):
    """Data-access contract for tickets.

    The ``Session`` is passed in by the service layer, which owns the transaction boundary
    (Unit of Work) — repositories never commit.
    """

    def create(self, session: Session, ticket: Ticket) -> Ticket: ...

    def get_by_id(self, session: Session, ticket_id: UUID) -> Ticket | None: ...

    def list(
        self,
        session: Session,
        *,
        filters: TicketFilter,
        page: int,
        page_size: int,
    ) -> tuple[list[Ticket], int]:
        """Return (page of tickets, total matching count)."""
        ...

    def update(self, session: Session, ticket: Ticket) -> Ticket: ...
