"""Typed domain-error hierarchy + FastAPI exception handlers.

Services raise typed ``AppError`` subclasses (never bare ``HTTPException``). A single set of
handlers maps them — and framework/validation/unexpected errors — onto the response envelope,
so error handling is centralized rather than scattered across routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.response import Envelope

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for all domain errors.

    Attributes:
        code: Stable, machine-readable error code (e.g. ``TICKET_NOT_FOUND``).
        description: Human-readable explanation.
        status_code: HTTP status the handler should return.
        additional_info: Optional structured context for the client.
    """

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(
        self,
        description: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        additional_info: Any | None = None,
    ) -> None:
        super().__init__(description)
        self.description = description
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.additional_info = additional_info


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409


class InvalidTransitionError(ConflictError):
    code = "INVALID_TRANSITION"
    status_code = 409


def _envelope_response(envelope: Envelope, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=envelope.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that render every error as the standard envelope."""

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "domain error", extra={"error_code": exc.code, "description": exc.description}
        )
        envelope = Envelope.fail(
            code=exc.code,
            description=exc.description,
            additional_info=exc.additional_info,
        )
        return _envelope_response(envelope, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        envelope = Envelope.fail(
            code="VALIDATION_ERROR",
            description="Request validation failed.",
            additional_info=exc.errors(),
        )
        return _envelope_response(envelope, 422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        envelope = Envelope.fail(
            code=f"HTTP_{exc.status_code}",
            description=str(exc.detail),
        )
        return _envelope_response(envelope, exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception: %s", exc)
        envelope = Envelope.fail(
            code="INTERNAL_ERROR",
            description="An unexpected error occurred.",
        )
        return _envelope_response(envelope, 500)
