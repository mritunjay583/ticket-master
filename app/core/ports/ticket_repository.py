"""Port: ticket persistence.

Implemented by a SQLAlchemy adapter today; any store can be substituted by writing a new class
that satisfies this interface and wiring it in ``app.core.container``.

Note: method signatures use ``Any`` placeholders in Phase 0 and are tightened to concrete
domain types (Ticket entity, filter/pagination DTOs) in Phase 1 when those types exist.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TicketRepository(Protocol):
    """Data-access contract for tickets."""

    def create(self, session: Any, ticket: Any) -> Any: ...

    def get_by_id(self, session: Any, ticket_id: Any) -> Any | None: ...

    def list(
        self, session: Any, *, filters: Any, page: int, page_size: int
    ) -> tuple[list[Any], int]: ...

    def update(self, session: Any, ticket: Any) -> Any: ...
