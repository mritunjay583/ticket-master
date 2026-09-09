"""Shared schema helpers: pagination query params and list metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Standard pagination query parameters."""

    page: int = Field(default=1, ge=1, description="1-based page number.")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page (max 100).")


class PageMeta(BaseModel):
    """Pagination metadata returned in the envelope's ``meta`` field."""

    page: int
    page_size: int
    total: int
