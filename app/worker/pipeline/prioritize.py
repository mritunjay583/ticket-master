"""Priority scoring step (deterministic heuristic simulation)."""

from __future__ import annotations

from app.schemas.enums import TicketPriority

# Keyword → priority hints (checked highest-severity first).
_URGENT_SIGNALS = ("urgent", "asap", "critical", "outage", "cannot access", "data loss", "breach")
_HIGH_SIGNALS = ("error", "failed", "not working", "broken", "crash", "charged twice", "refund")
_LOW_SIGNALS = ("question", "how do i", "how to", "feedback", "suggestion", "clarification")


def assign_priority(subject: str, description: str, is_spam: bool) -> TicketPriority:
    """Derive a priority from the ticket text.

    Spam is always LOW. Otherwise, match keyword signals from most to least severe; default MEDIUM.
    """
    if is_spam:
        return TicketPriority.LOW

    text = f"{subject} {description}".lower()
    if any(s in text for s in _URGENT_SIGNALS):
        return TicketPriority.URGENT
    if any(s in text for s in _HIGH_SIGNALS):
        return TicketPriority.HIGH
    if any(s in text for s in _LOW_SIGNALS):
        return TicketPriority.LOW
    return TicketPriority.MEDIUM
