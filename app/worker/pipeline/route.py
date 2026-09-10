"""Department routing step (deterministic category → department mapping)."""

from __future__ import annotations

from app.schemas.enums import Department, TicketCategory

# Category → owning department. Spam is routed to TRIAGE regardless of category.
_CATEGORY_TO_DEPARTMENT: dict[TicketCategory, Department] = {
    TicketCategory.BILLING: Department.BILLING,
    TicketCategory.TECHNICAL: Department.ENGINEERING,
    TicketCategory.ACCOUNT: Department.ACCOUNT_MANAGEMENT,
    TicketCategory.GENERAL: Department.SUPPORT,
}


def route_department(category: TicketCategory, is_spam: bool) -> Department:
    """Return the department a ticket should be routed to."""
    if is_spam:
        return Department.TRIAGE
    return _CATEGORY_TO_DEPARTMENT.get(category, Department.SUPPORT)
