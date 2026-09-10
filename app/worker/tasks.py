"""The background job: process a newly-created ticket.

Runs in the worker process (not the API). Idempotent and keyed by ticket_id — safe to re-run:
it upserts the single ProcessingResult and guards on processing_status. All writes happen in one
transaction (Unit of Work).

Pipeline: summarize -> spam-detect -> prioritize -> route. The full computed output is stored in
``processing_results``; priority + department are also applied to the live ticket (see
ARCHITECTURE.md §3.4 "suggested vs applied").
"""

from __future__ import annotations

from uuid import UUID

from app.adapters.processing.deterministic_summary import DeterministicSummaryProvider
from app.core.config import get_settings
from app.core.db import init_engine, session_scope
from app.core.logging import get_logger
from app.models.processing_result import ProcessingResult
from app.models.ticket import Ticket
from app.models.ticket_event import TicketEvent
from app.schemas.enums import EventType, ProcessingStatus
from app.worker.pipeline.prioritize import assign_priority
from app.worker.pipeline.route import route_department
from app.worker.pipeline.spam import detect_spam

logger = get_logger(__name__)


def process_ticket(ticket_id: str) -> None:
    """Enrich a ticket asynchronously and persist the result.

    ``ticket_id`` is passed as a string because RQ serializes job arguments (the API enqueues the
    ticket's UUID as ``str``).
    """
    tid = UUID(ticket_id)
    # The worker process must have its DB engine initialised (it does not go through the API's
    # lifespan). init_engine is idempotent.
    init_engine(get_settings())

    with session_scope() as session:
        ticket = session.get(Ticket, tid)
        if ticket is None:
            logger.error("process_ticket: ticket not found", extra={"ticket_id": ticket_id})
            return

        # Idempotency guard: if already processed, do nothing (safe re-run).
        if ticket.processing_status == ProcessingStatus.DONE:
            logger.info("process_ticket: already done, skipping", extra={"ticket_id": ticket_id})
            return

        try:
            subject = ticket.subject
            description = ticket.description

            # --- pipeline ---
            summary = DeterministicSummaryProvider().summarize(subject, description)
            is_spam = detect_spam(subject, description)
            suggested_priority = assign_priority(subject, description, is_spam)
            routed_department = route_department(ticket.category, is_spam)

            # --- persist result (upsert the single row for idempotency) ---
            result = ticket.processing_result
            if result is None:
                result = ProcessingResult(ticket_id=ticket.id)
                session.add(result)
            result.summary = summary
            result.is_spam = is_spam
            result.suggested_priority = suggested_priority
            result.routed_department = routed_department

            # --- apply the "action" outputs to the live ticket ---
            ticket.priority = suggested_priority
            ticket.department = routed_department
            ticket.processing_status = ProcessingStatus.DONE

            session.add(
                TicketEvent(
                    ticket_id=ticket.id,
                    event_type=EventType.PROCESSED,
                    actor="system",
                    note={
                        "summary": summary,
                        "is_spam": is_spam,
                        "suggested_priority": suggested_priority.value,
                        "routed_department": routed_department.value,
                    },
                )
            )
            logger.info(
                "process_ticket: done",
                extra={"ticket_id": ticket_id, "is_spam": is_spam,
                       "priority": suggested_priority.value, "department": routed_department.value},
            )
        except Exception as exc:  # noqa: BLE001 - record failure, don't crash the worker silently
            ticket.processing_status = ProcessingStatus.FAILED
            session.add(
                TicketEvent(
                    ticket_id=ticket.id,
                    event_type=EventType.PROCESSING_FAILED,
                    actor="system",
                    note={"error": str(exc)},
                )
            )
            logger.exception("process_ticket: failed", extra={"ticket_id": ticket_id})
            # Re-raise so RQ marks the job failed (and can retry in Phase 4).
            raise
