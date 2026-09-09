"""Health/readiness endpoint.

Returns the standard envelope and reports database connectivity. Returns HTTP 503 when a
required dependency is unreachable so orchestrators can gate traffic.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import check_database
from app.core.response import Envelope

router = APIRouter(tags=["health"])

@router.get("/health", summary="Liveness/readiness probe")
def health() -> JSONResponse:
    """Report service and dependency health."""
    settings = get_settings()
    db_ok = check_database()

    data = {
        "service": settings.app_name,
        "environment": settings.environment,
        "dependencies": {"database": "up" if db_ok else "down"},
    }

    if db_ok:
        envelope = Envelope.ok(data=data, message="healthy")
        return JSONResponse(status_code=200, content=envelope.model_dump())

    envelope = Envelope.fail(
        code="DEPENDENCY_UNAVAILABLE",
        description="One or more dependencies are unavailable.",
        additional_info=data,
    )
    return JSONResponse(status_code=503, content=envelope.model_dump())
