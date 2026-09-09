"""ProcessingResult ORM model — output of the async processing job (one row per ticket)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enum_types import department_enum, ticket_priority_enum
from app.schemas.enums import Department, TicketPriority

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class ProcessingResult(Base, TimestampMixin):
    """The immutable record of what the background worker computed for a ticket.

    One-to-one with a ticket (enforced by the UNIQUE ticket_id). Holds the full computed output;
    ``suggested_priority`` / ``routed_department`` are also *applied* to the live ticket, while
    ``summary`` / ``is_spam`` live only here (see ARCHITECTURE.md §3.4 — suggested-vs-applied).
    """

    __tablename__ = "processing_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one result per ticket
    )

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_spam: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suggested_priority: Mapped[TicketPriority | None] = mapped_column(
        ticket_priority_enum, nullable=True
    )
    routed_department: Mapped[Department | None] = mapped_column(department_enum, nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="processing_result")

    def __repr__(self) -> str:
        return f"<ProcessingResult ticket={self.ticket_id} is_spam={self.is_spam}>"
