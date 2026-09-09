"""initial schema

Revision ID: 2ed68c6af95d
Revises:
Create Date: 2026-09-10 02:56:10.134761

Notes on native PostgreSQL enums:
    A PG enum is a standalone type object, independent of any table. Autogenerate creates it
    implicitly on first column use and does NOT drop it on downgrade — which breaks the
    downgrade→upgrade roundtrip with "type already exists". We therefore manage the enum types
    EXPLICITLY here: create them once up front, reference them with ``create_type=False`` so column
    creation does not re-emit CREATE TYPE, and drop them explicitly on downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2ed68c6af95d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- Enum type definitions (created/dropped explicitly; create_type=False on columns) ---
ticket_status = postgresql.ENUM(
    "OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED", name="ticket_status", create_type=False
)
ticket_priority = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "URGENT", name="ticket_priority", create_type=False
)
ticket_category = postgresql.ENUM(
    "BILLING", "TECHNICAL", "ACCOUNT", "GENERAL", name="ticket_category", create_type=False
)
department = postgresql.ENUM(
    "BILLING",
    "ENGINEERING",
    "ACCOUNT_MANAGEMENT",
    "SUPPORT",
    "TRIAGE",
    name="department",
    create_type=False,
)
processing_status = postgresql.ENUM(
    "PENDING", "DONE", "FAILED", name="processing_status", create_type=False
)
event_type = postgresql.ENUM(
    "CREATED", "STATUS_CHANGED", "PROCESSED", "PROCESSING_FAILED", name="event_type",
    create_type=False,
)

_ALL_ENUMS = (
    ticket_status,
    ticket_priority,
    ticket_category,
    department,
    processing_status,
    event_type,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # 1) Create all enum types once, explicitly.
    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # 2) Tables (columns reference the already-created enums; create_type=False prevents re-emit).
    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("department", department, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agents_email"), "agents", ["email"], unique=True)

    op.create_table(
        "tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_name", sa.String(length=128), nullable=False),
        sa.Column("customer_email", sa.String(length=256), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column("priority", ticket_priority, nullable=False),
        sa.Column("category", ticket_category, nullable=False),
        sa.Column("department", department, nullable=True),
        sa.Column("assigned_agent_id", sa.UUID(), nullable=True),
        sa.Column("processing_status", processing_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_category", "tickets", ["category"], unique=False)
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"], unique=False)
    op.create_index("ix_tickets_priority", "tickets", ["priority"], unique=False)
    op.create_index(
        "ix_tickets_processing_status", "tickets", ["processing_status"], unique=False
    )
    op.create_index("ix_tickets_status", "tickets", ["status"], unique=False)
    op.create_index(
        "ix_tickets_status_priority", "tickets", ["status", "priority"], unique=False
    )

    op.create_table(
        "processing_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("is_spam", sa.Boolean(), nullable=False),
        sa.Column("suggested_priority", ticket_priority, nullable=True),
        sa.Column("routed_department", department, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_id"),
    )

    op.create_table(
        "ticket_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("from_status", ticket_status, nullable=True),
        sa.Column("to_status", ticket_status, nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("note", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ticket_events_ticket_id_created_at",
        "ticket_events",
        ["ticket_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ticket_events_ticket_id_created_at", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_table("processing_results")
    op.drop_index("ix_tickets_status_priority", table_name="tickets")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_processing_status", table_name="tickets")
    op.drop_index("ix_tickets_priority", table_name="tickets")
    op.drop_index("ix_tickets_created_at", table_name="tickets")
    op.drop_index("ix_tickets_category", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index(op.f("ix_agents_email"), table_name="agents")
    op.drop_table("agents")

    # Drop enum types explicitly (tables are gone; the types would otherwise linger).
    bind = op.get_bind()
    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
