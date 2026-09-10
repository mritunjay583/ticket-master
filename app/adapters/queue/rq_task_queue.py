"""Redis + RQ implementation of the ``TaskQueue`` port.

The API side only needs ``enqueue``. Swapping to SQS/Celery later means writing a new adapter that
satisfies the same port and changing one line in the container — call sites are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from redis import Redis
from rq import Queue


class RQTaskQueue:
    """Enqueue jobs onto a named RQ queue backed by Redis."""

    def __init__(self, redis_url: str, queue_name: str = "tickets") -> None:
        self._connection = Redis.from_url(redis_url)
        self._queue = Queue(queue_name, connection=self._connection)

    def enqueue(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        job = self._queue.enqueue(func, *args, **kwargs)
        return str(job.id)
