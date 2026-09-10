"""Redis + RQ implementation of the ``TaskQueue`` port.

The API side only needs ``enqueue``. Swapping to SQS/Celery later means writing a new adapter that
satisfies the same port and changing one line in the container — call sites are unaffected.

Reliability (Phase 4): jobs are enqueued with an RQ ``Retry`` policy so transient failures are
retried with backoff before landing in RQ's failed-job registry (the dead-letter equivalent).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from redis import Redis
from rq import Queue, Retry


class RQTaskQueue:
    """Enqueue jobs onto a named RQ queue backed by Redis, with retries."""

    def __init__(self, redis_url: str, queue_name: str = "tickets", max_retries: int = 3) -> None:
        self._connection = Redis.from_url(redis_url)
        self._queue = Queue(queue_name, connection=self._connection)
        self._max_retries = max_retries

    def enqueue(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        # Exponential-ish backoff: wait 10s, 30s, 60s between retries (one interval per retry).
        retry = Retry(max=self._max_retries, interval=[10, 30, 60][: self._max_retries] or [10])
        job = self._queue.enqueue(func, *args, retry=retry, **kwargs)
        return str(job.id)
