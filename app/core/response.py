"""Standardized API response envelope.

Every response the API emits shares one shape::

    { "success": bool, "message": str|null, "data": any|null,
      "error": {code, description, ...}|null, "meta": {...}|null }

The ``Envelope`` builder gives a consistent, fluent construction path so handlers never
assemble raw dicts by hand.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Machine-readable error body carried in the envelope's ``error`` field."""

    code: str
    description: str
    additional_info: Any | None = None


class Envelope(BaseModel):
    """The single response shape for the whole API."""

    success: bool
    message: str | None = None
    data: Any | None = None
    error: ErrorDetail | None = None
    meta: Any | None = None

    @classmethod
    def ok(
        cls,
        data: Any | None = None,
        *,
        message: str | None = None,
        meta: Any | None = None,
    ) -> Envelope:
        """Build a success envelope."""
        return cls(success=True, message=message, data=data, meta=meta)

    @classmethod
    def fail(
        cls,
        *,
        code: str,
        description: str,
        message: str | None = None,
        additional_info: Any | None = None,
    ) -> Envelope:
        """Build an error envelope."""
        return cls(
            success=False,
            message=message or description,
            error=ErrorDetail(
                code=code,
                description=description,
                additional_info=additional_info,
            ),
        )
