"""Ticket ORM model — the core support-ticket entity."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enum_types import (
    department_enum,
    processing_status_enum,
    ticket_category_enum,
    ticket_priority_enum,
    ticket_status_enum,
)
from app.schemas.enums import (
    Department,
    ProcessingStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.processing_result import ProcessingResult
    from app.models.ticket_event import TicketEvent


class Ticket(Base, TimestampMixin):
    """A customer support ticket — the aggregate root of the domain."""

    __tablename__ = "tickets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # --- Customer-provided data (what the customer submitted) ---
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Classification & lifecycle ---
    status: Mapped[TicketStatus] = mapped_column(
        ticket_status_enum, nullable=False, default=TicketStatus.OPEN
    )
    priority: Mapped[TicketPriority] = mapped_column(
        ticket_priority_enum, nullable=False, default=TicketPriority.MEDIUM
    )
    category: Mapped[TicketCategory] = mapped_column(ticket_category_enum, nullable=False)
    department: Mapped[Department | None] = mapped_column(department_enum, nullable=True)

    # --- Assignment ---
    assigned_agent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Async processing lifecycle (drives the worker; acts as a lightweight outbox marker) ---
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        processing_status_enum, nullable=False, default=ProcessingStatus.PENDING
    )

    # --- Relationships ---
    assigned_agent: Mapped[Agent | None] = relationship(lazy="joined")
    events: Mapped[list[TicketEvent]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketEvent.created_at",
    )
    processing_result: Mapped[ProcessingResult | None] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        # Indexes for the required list filters and default ordering.
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_priority", "priority"),
        Index("ix_tickets_category", "category"),
        Index("ix_tickets_created_at", "created_at"),
        Index("ix_tickets_status_priority", "status", "priority"),  # common combined filter
        Index("ix_tickets_processing_status", "processing_status"),  # sweeper lookups
    )

    def __repr__(self) -> str:
        return f"<Ticket id={self.id} status={self.status} priority={self.priority}>"
