"""Seed the database with sample agents and tickets for quick manual testing.

Idempotent: running it repeatedly will not create duplicates (it checks for existing rows by a
natural key first). Run with:  ``uv run python -m scripts.seed``
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.db import init_engine, session_scope
from app.core.logging import configure_logging, get_logger
from app.models import Agent, Ticket
from app.schemas.enums import (
    Department,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

logger = get_logger(__name__)


AGENTS = [
    {"name": "Alice Billing", "email": "alice@support.example", "department": Department.BILLING},
    {"name": "Bob Engineer", "email": "bob@support.example", "department": Department.ENGINEERING},
    {"name": "Carol Accounts", "email": "carol@support.example",
     "department": Department.ACCOUNT_MANAGEMENT},
    {"name": "Dave Support", "email": "dave@support.example", "department": Department.SUPPORT},
]

TICKETS = [
    {
        "customer_name": "John Doe",
        "customer_email": "john@example.com",
        "subject": "Charged twice for my subscription",
        "description": "I was billed two times this month. Please refund the duplicate charge.",
        "category": TicketCategory.BILLING,
        "priority": TicketPriority.HIGH,
        "status": TicketStatus.OPEN,
    },
    {
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "subject": "App crashes on login",
        "description": "Every time I try to log in the mobile app crashes immediately.",
        "category": TicketCategory.TECHNICAL,
        "priority": TicketPriority.URGENT,
        "status": TicketStatus.IN_PROGRESS,
    },
    {
        "customer_name": "Raj Patel",
        "customer_email": "raj@example.com",
        "subject": "Cannot update my email address",
        "description": "The account settings page does not save my new email.",
        "category": TicketCategory.ACCOUNT,
        "priority": TicketPriority.MEDIUM,
        "status": TicketStatus.OPEN,
    },
    {
        "customer_name": "Mia Wong",
        "customer_email": "mia@example.com",
        "subject": "How do I export my data?",
        "description": "I would like to download all my data as CSV. Is that possible?",
        "category": TicketCategory.GENERAL,
        "priority": TicketPriority.LOW,
        "status": TicketStatus.RESOLVED,
    },
]


def seed() -> None:
    """Insert sample agents and tickets if they do not already exist."""
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)

    with session_scope() as session:
        existing_agents = {a.email for a in session.query(Agent).all()}
        created_agents = 0
        for data in AGENTS:
            if data["email"] in existing_agents:
                continue
            session.add(Agent(**data))
            created_agents += 1

        existing_subjects = {t.subject for t in session.query(Ticket).all()}
        created_tickets = 0
        for data in TICKETS:
            if data["subject"] in existing_subjects:
                continue
            session.add(Ticket(**data))
            created_tickets += 1

    logger.info(
        "seed complete",
        extra={"agents_created": created_agents, "tickets_created": created_tickets},
    )
    print(f"Seed complete: {created_agents} agents, {created_tickets} tickets created.")


if __name__ == "__main__":
    seed()
