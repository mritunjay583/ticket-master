"""Ticket request/response DTOs (Pydantic).

These are the API contract — distinct from the SQLAlchemy models (persistence). Keeping them
separate means a DB change doesn't automatically change the public API, and vice versa.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.enums import (
    Department,
    ProcessingStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)


class CreateTicketRequest(BaseModel):
    """Payload a customer submits to open a ticket."""

    customer_name: str = Field(min_length=1, max_length=128)
    customer_email: EmailStr
    subject: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1)
    priority: TicketPriority = TicketPriority.MEDIUM
    category: TicketCategory


class UpdateStatusRequest(BaseModel):
    """Payload an agent submits to change a ticket's status."""

    status: TicketStatus
    actor: str | None = Field(
        default=None,
        max_length=256,
        description="Who is performing the change (e.g. agent email). Optional.",
    )


class TicketResponse(BaseModel):
    """A ticket as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_name: str
    customer_email: str
    subject: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    department: Department | None
    assigned_agent_id: UUID | None
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime


class TicketEventResponse(BaseModel):
    """One entry in a ticket's audit history."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_id: UUID
    event_type: str
    from_status: TicketStatus | None
    to_status: TicketStatus | None
    actor: str | None
    created_at: datetime
