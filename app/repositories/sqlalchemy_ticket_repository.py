"""SQLAlchemy adapter implementing the ``TicketRepository`` port.

This is the only place ticket SQL lives. The service layer talks to the ``TicketRepository``
interface and never sees SQLAlchemy — so swapping the store means writing a new adapter here and
changing one line in the container.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ports.ticket_repository import TicketFilter
from app.models.ticket import Ticket


class SqlAlchemyTicketRepository:
    """Data access for tickets, backed by SQLAlchemy/PostgreSQL."""

    def create(self, session: Session, ticket: Ticket) -> Ticket:
        session.add(ticket)
        session.flush()  # assign PK/defaults without committing (service owns the transaction)
        return ticket

    def get_by_id(self, session: Session, ticket_id: UUID) -> Ticket | None:
        return session.get(Ticket, ticket_id)

    def list(
        self,
        session: Session,
        *,
        filters: TicketFilter,
        page: int,
        page_size: int,
    ) -> tuple[list[Ticket], int]:
        """Return (page of tickets ordered by newest first, total matching count)."""
        conditions = []
        if filters.status is not None:
            conditions.append(Ticket.status == filters.status)
        if filters.priority is not None:
            conditions.append(Ticket.priority == filters.priority)
        if filters.category is not None:
            conditions.append(Ticket.category == filters.category)

        # Total count of matching rows (before pagination).
        count_stmt = select(func.count()).select_from(Ticket)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total = session.scalar(count_stmt) or 0

        # Page of rows, newest first, with offset/limit pagination.
        stmt = select(Ticket)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = (
            stmt.order_by(Ticket.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list(session.scalars(stmt).all())
        return rows, total

    def update(self, session: Session, ticket: Ticket) -> Ticket:
        # ``ticket`` is already tracked by the session; flush persists pending changes.
        session.flush()
        return ticket
