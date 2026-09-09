"""Shared SQLAlchemy native-enum type instances.

A native PostgreSQL enum type (e.g. ``department``) must be created exactly once in the database.
When more than one table references the same enum, each model defining its own ``SAEnum(...)`` would
emit a duplicate ``CREATE TYPE`` and fail. Defining the type objects once here and reusing them
across models avoids that: SQLAlchemy creates each type a single time.
"""

from __future__ import annotations

from sqlalchemy import Enum as SAEnum

from app.schemas.enums import (
    Department,
    EventType,
    ProcessingStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

ticket_status_enum = SAEnum(TicketStatus, name="ticket_status", native_enum=True)
ticket_priority_enum = SAEnum(TicketPriority, name="ticket_priority", native_enum=True)
ticket_category_enum = SAEnum(TicketCategory, name="ticket_category", native_enum=True)
department_enum = SAEnum(Department, name="department", native_enum=True)
processing_status_enum = SAEnum(ProcessingStatus, name="processing_status", native_enum=True)
event_type_enum = SAEnum(EventType, name="event_type", native_enum=True)
