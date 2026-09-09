"""TicketEvent ORM model — append-only audit history of ticket changes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enum_types import event_type_enum, ticket_status_enum
from app.schemas.enums import EventType, TicketStatus

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class TicketEvent(Base, TimestampMixin):
    """One immutable entry in a ticket's history (created, status-changed, processed, ...).

    Rows are only ever inserted, never updated or deleted (except via ticket cascade). This is the
    audit trail the brief asks for under "ticket events/history".
    """

    __tablename__ = "ticket_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[EventType] = mapped_column(event_type_enum, nullable=False)

    # Status transition captured for STATUS_CHANGED events (null for others).
    from_status: Mapped[TicketStatus | None] = mapped_column(ticket_status_enum, nullable=True)
    to_status: Mapped[TicketStatus | None] = mapped_column(ticket_status_enum, nullable=True)

    # Who/what triggered it (agent email, "system", "customer", ...).
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-form structured context (e.g. processing outcome details).
    note: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_ticket_events_ticket_id_created_at", "ticket_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<TicketEvent id={self.id} ticket={self.ticket_id} type={self.event_type}>"
