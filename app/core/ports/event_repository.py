"""Port: ticket event/history persistence (append-only audit trail).

Note: signatures use ``Any`` placeholders in Phase 0 and are tightened to concrete domain types
in Phase 1 when the event entity exists.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TicketEventRepository(Protocol):
    """Data-access contract for the immutable ticket-event log."""

    def add(self, session: Any, event: Any) -> Any: ...

    def list_for_ticket(self, session: Any, ticket_id: Any) -> list[Any]: ...
