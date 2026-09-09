"""Ticket REST endpoints.

Thin HTTP layer: parse/validate DTOs, call the service, wrap the result in the standard envelope,
set the right status code. No business logic here.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.container import Container, get_container
from app.core.ports.ticket_repository import TicketFilter
from app.core.response import Envelope
from app.schemas.common import PageMeta
from app.schemas.enums import TicketCategory, TicketPriority, TicketStatus
from app.schemas.ticket import (
    CreateTicketRequest,
    TicketEventResponse,
    TicketResponse,
    UpdateStatusRequest,
)

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])

ContainerDep = Annotated[Container, Depends(get_container)]


def _envelope(data: object, status_code: int, *, message: str | None = None,
              meta: object | None = None) -> JSONResponse:
    env = Envelope.ok(data=data, message=message, meta=meta)
    return JSONResponse(status_code=status_code, content=env.model_dump(mode="json"))


@router.post("", summary="Create a ticket", status_code=201)
def create_ticket(payload: CreateTicketRequest, container: ContainerDep) -> JSONResponse:
    ticket = container.ticket_service.create_ticket(payload)
    data = TicketResponse.model_validate(ticket).model_dump(mode="json")
    return _envelope(data, 201, message="Ticket created")


@router.get("/{ticket_id}", summary="Retrieve a ticket by ID")
def get_ticket(ticket_id: UUID, container: ContainerDep) -> JSONResponse:
    ticket = container.ticket_service.get_ticket(ticket_id)
    data = TicketResponse.model_validate(ticket).model_dump(mode="json")
    return _envelope(data, 200)


@router.get("", summary="List tickets (pagination + filter by status/priority/category)")
def list_tickets(
    container: ContainerDep,
    status: Annotated[TicketStatus | None, Query()] = None,
    priority: Annotated[TicketPriority | None, Query()] = None,
    category: Annotated[TicketCategory | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    filters = TicketFilter(status=status, priority=priority, category=category)
    tickets, total = container.ticket_service.list_tickets(
        filters=filters, page=page, page_size=page_size
    )
    data = [TicketResponse.model_validate(t).model_dump(mode="json") for t in tickets]
    meta = PageMeta(page=page, page_size=page_size, total=total).model_dump()
    return _envelope(data, 200, meta=meta)


@router.patch("/{ticket_id}/status", summary="Update ticket status (state machine)")
def update_status(
    ticket_id: UUID, payload: UpdateStatusRequest, container: ContainerDep
) -> JSONResponse:
    ticket = container.ticket_service.update_status(ticket_id, payload.status, payload.actor)
    data = TicketResponse.model_validate(ticket).model_dump(mode="json")
    return _envelope(data, 200, message="Status updated")


@router.get("/{ticket_id}/events", summary="Get a ticket's audit history")
def get_ticket_events(ticket_id: UUID, container: ContainerDep) -> JSONResponse:
    events = container.ticket_service.get_ticket_events(ticket_id)
    data = [TicketEventResponse.model_validate(e).model_dump(mode="json") for e in events]
    return _envelope(data, 200)
