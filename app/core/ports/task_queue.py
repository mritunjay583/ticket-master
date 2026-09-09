"""Port: background task queue.

Implemented by an RQ adapter today; an SQS/Kafka adapter can be substituted later without
touching call sites (see ARCHITECTURE.md ADR-3 / §1.4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TaskQueue(Protocol):
    """Enqueue a callable for asynchronous execution; returns a job id."""

    def enqueue(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str: ...
