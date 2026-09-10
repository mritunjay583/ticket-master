"""RQ worker entrypoint.

Runs as a separate process/container (`python -m app.worker.worker`). It connects to Redis, listens
on the configured queue, and executes jobs (e.g. ``process_ticket``). It shares this codebase
(models/config/DB) but runs independently of the API.

Reliability (Phase 4): on startup it registers a recurring **sweeper** (defined in
``app.worker.sweeper``) that re-enqueues tickets stuck in PENDING.
``worker.work(with_scheduler=True)`` runs RQ's scheduler in the same process, so scheduled jobs
fire without a separate scheduler daemon.
"""

from __future__ import annotations

from datetime import UTC, datetime

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.db import init_engine
from app.core.logging import configure_logging, get_logger
from app.worker.sweeper import schedule_sweeper

logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    # Initialise the DB engine once for the worker process (jobs also call init_engine defensively).
    init_engine(settings)

    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=connection)

    # Register the recurring sweeper (functions live in app.worker.sweeper so RQ can import them).
    schedule_sweeper()

    logger.info(
        "worker starting",
        extra={
            "queue": settings.queue_name,
            "redis": settings.redis_url,
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    worker = Worker([queue], connection=connection)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
