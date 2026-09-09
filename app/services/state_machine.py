"""Ticket status state machine.

The single source of truth for which status transitions are allowed. Centralizing the transition
table makes the rule testable and prevents illegal states. Pure in-process domain logic — not a
port (no external dependency, only one sensible implementation).
"""

from __future__ import annotations

from app.core.errors import InvalidTransitionError
from app.schemas.enums import TicketStatus

# Allowed transitions: current status -> set of statuses it may move to.
# Lifecycle: OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED, with controlled reopen from
# RESOLVED/CLOSED back to OPEN.
_ALLOWED: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.OPEN: frozenset({TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED}),
    TicketStatus.IN_PROGRESS: frozenset({TicketStatus.RESOLVED, TicketStatus.OPEN}),
    TicketStatus.RESOLVED: frozenset({TicketStatus.CLOSED, TicketStatus.OPEN}),
    TicketStatus.CLOSED: frozenset({TicketStatus.OPEN}),  # reopen only
}


def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    """Return True if moving from ``current`` to ``target`` is allowed."""
    return target in _ALLOWED.get(current, frozenset())


def validate_transition(current: TicketStatus, target: TicketStatus) -> None:
    """Raise ``InvalidTransitionError`` (HTTP 409) if the transition is not allowed.

    A no-op transition (current == target) is rejected as invalid — there is nothing to change.
    """
    if current == target:
        raise InvalidTransitionError(
            f"Ticket is already in status {current.value}.",
            additional_info={"from": current.value, "to": target.value},
        )
    if not can_transition(current, target):
        allowed = sorted(s.value for s in _ALLOWED.get(current, frozenset()))
        raise InvalidTransitionError(
            f"Cannot change status from {current.value} to {target.value}.",
            additional_info={"from": current.value, "to": target.value, "allowed": allowed},
        )
