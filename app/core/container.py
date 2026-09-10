"""Composition root: the single place that wires concrete adapters to ports.

Everything technology-specific is assembled here. Routers/services receive dependencies from
this container, so swapping a backend is a change confined to this file plus the new adapter module.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.queue.rq_task_queue import RQTaskQueue
from app.core.config import Settings, get_settings
from app.core.ports.event_repository import TicketEventRepository
from app.core.ports.task_queue import TaskQueue
from app.core.ports.ticket_repository import TicketRepository
from app.repositories.sqlalchemy_event_repository import SqlAlchemyEventRepository
from app.repositories.sqlalchemy_ticket_repository import SqlAlchemyTicketRepository
from app.services.ticket_service import TicketService


@dataclass(frozen=True)
class Container:
    """Holds fully-wired application dependencies."""

    settings: Settings
    ticket_repository: TicketRepository
    event_repository: TicketEventRepository
    task_queue: TaskQueue
    ticket_service: TicketService


_container: Container | None = None


def build_container(settings: Settings | None = None) -> Container:
    """Create (once) and return the container — the only place concrete tech is chosen."""
    global _container
    if _container is None:
        settings = settings or get_settings()
        ticket_repository: TicketRepository = SqlAlchemyTicketRepository()
        event_repository: TicketEventRepository = SqlAlchemyEventRepository()
        task_queue: TaskQueue = RQTaskQueue(
            settings.redis_url, settings.queue_name, settings.job_max_retries
        )
        ticket_service = TicketService(ticket_repository, event_repository, task_queue)
        _container = Container(
            settings=settings,
            ticket_repository=ticket_repository,
            event_repository=event_repository,
            task_queue=task_queue,
            ticket_service=ticket_service,
        )
    return _container


def get_container() -> Container:
    """FastAPI dependency returning the shared container."""
    if _container is None:
        return build_container()
    return _container
