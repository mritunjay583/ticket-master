"""FastAPI application factory + lifespan.

Bootstrap sequence (mirrors a clean production server init):
    configure logging → build container → init DB engine → verify DB reachable
    → register routers, middleware, exception handlers.
On shutdown: dispose the DB engine's connection pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.middleware import RequestIDMiddleware
from app.api.v1.tickets import router as tickets_router
from app.core.config import Settings, get_settings
from app.core.container import build_container
from app.core.db import check_database, dispose_engine, init_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle."""
    settings: Settings = app.state.settings
    init_engine(settings)
    if check_database():
        logger.info("database connection verified")
    else:
        # Fail loud but keep the process up so /health can report 'down' for diagnosis.
        logger.error("database unreachable at startup")
    logger.info("%s started (env=%s)", settings.app_name, settings.environment)
    yield
    dispose_engine()
    logger.info("%s stopped", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    build_container(settings)

    app = FastAPI(
        title="Ticket-Master API",
        version="0.1.0",
        description="Support Ticket Management System with asynchronous ticket processing.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(tickets_router)
    return app


app = create_app()
