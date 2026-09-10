"""Reliability sweeper (Phase 4).

Periodically finds tickets stuck in ``processing_status = PENDING`` for longer than a threshold and
re-enqueues them for processing. This is the safety net that makes PostgreSQL — not the queue — the
source of truth: as long as a ticket row exists as PENDING, it *will* eventually be processed, even
if the original enqueue failed (Redis was down) or a queued job was lost (Redis wiped).

Combined with the idempotent ``process_ticket`` job, re-enqueuing is always safe (no duplicates).

Scheduling: registered as a recurring RQ scheduled job from the worker entrypoint. See
``LEARNING_PHASE4_RELIABILITY.md`` for how to run it instead as a standalone periodic loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from redis import Redis
from rq import Queue
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import init_engine, session_scope
from app.core.logging import get_logger
from app.models.ticket import Ticket
from app.schemas.enums import ProcessingStatus
from app.worker.tasks import process_ticket

logger = get_logger(__name__)

# Stable job id so worker restarts don't stack duplicate recurring schedules.
SWEEPER_JOB_ID = "recurring-pending-sweeper"


def schedule_sweeper() -> None:
    """Register the (self-rescheduling) recurring sweeper.

    Defined here — NOT in the worker entrypoint — because RQ cannot serialize a reference to a
    function living in the ``__main__`` module. Functions enqueued for RQ must be importable by a
    stable module path (``app.worker.sweeper.run_sweeper_cycle``).
    """
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=connection)
    try:
        queue.enqueue_in(
            timedelta(seconds=settings.sweeper_interval_seconds),
            run_sweeper_cycle,
            job_id=SWEEPER_JOB_ID,
        )
        logger.info(
            "recurring sweeper registered",
            extra={"interval_seconds": settings.sweeper_interval_seconds},
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to register recurring sweeper")


def run_sweeper_cycle() -> None:
    """One sweep, then schedule the next run (self-perpetuating recurring job)."""
    settings = get_settings()
    try:
        sweep_pending_tickets()
    finally:
        connection = Redis.from_url(settings.redis_url)
        queue = Queue(settings.queue_name, connection=connection)
        queue.enqueue_in(
            timedelta(seconds=settings.sweeper_interval_seconds),
            run_sweeper_cycle,
            job_id=SWEEPER_JOB_ID,
        )


def sweep_pending_tickets() -> int:
    """Re-enqueue tickets stuck in PENDING beyond the threshold; return the count enqueued."""
    settings = get_settings()
    init_engine(settings)

    cutoff = datetime.now(UTC) - timedelta(seconds=settings.sweeper_stale_after_seconds)

    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=connection)

    enqueued = 0
    with session_scope() as session:
        stmt = (
            select(Ticket.id)
            .where(
                Ticket.processing_status == ProcessingStatus.PENDING,
                Ticket.created_at < cutoff,
            )
            .order_by(Ticket.created_at.asc())
            .limit(settings.sweeper_batch_size)
        )
        stuck_ids = list(session.scalars(stmt).all())

    for ticket_id in stuck_ids:
        queue.enqueue(process_ticket, str(ticket_id))
        enqueued += 1

    if enqueued:
        logger.info("sweeper re-enqueued stuck tickets", extra={"count": enqueued})
    else:
        logger.debug("sweeper found no stuck tickets")
    return enqueued
