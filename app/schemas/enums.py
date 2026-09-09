"""Domain enums — the fixed value sets used across models, DTOs, and the DB.

Defined once here and reused by both SQLAlchemy models (as native PostgreSQL enum types) and
Pydantic schemas, so there is a single source of truth for allowed values.

All enums subclass ``str`` so their members serialize to plain strings in JSON and compare
naturally (e.g. ``ticket.status == TicketStatus.OPEN``).
"""

from __future__ import annotations

from enum import StrEnum


class TicketStatus(StrEnum):
    """Lifecycle states of a ticket (see the state machine in Phase 2)."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketPriority(StrEnum):
    """How urgent a ticket is."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TicketCategory(StrEnum):
    """What the ticket is about (drives routing)."""

    BILLING = "BILLING"
    TECHNICAL = "TECHNICAL"
    ACCOUNT = "ACCOUNT"
    GENERAL = "GENERAL"


class Department(StrEnum):
    """Team a ticket can be routed to."""

    BILLING = "BILLING"
    ENGINEERING = "ENGINEERING"
    ACCOUNT_MANAGEMENT = "ACCOUNT_MANAGEMENT"
    SUPPORT = "SUPPORT"
    TRIAGE = "TRIAGE"  # default sink for spam / unroutable tickets


class ProcessingStatus(StrEnum):
    """State of the asynchronous processing job for a ticket."""

    PENDING = "PENDING"  # created, not yet processed (also acts as a lightweight outbox marker)
    DONE = "DONE"
    FAILED = "FAILED"


class EventType(StrEnum):
    """Kinds of entries in the append-only ticket audit log."""

    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PROCESSED = "PROCESSED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
