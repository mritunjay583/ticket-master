"""Database engine, session factory, and FastAPI session dependency.

The engine/sessionmaker are created once from ``Settings``. Repositories receive a ``Session``;
the service layer owns the transaction boundary (Unit of Work) via ``session_scope``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def init_engine(settings: Settings) -> Engine:
    """Create the global engine + session factory (idempotent)."""
    global _engine, _SessionFactory
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            echo=settings.db_echo,
            future=True,
        )
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine not initialized; call init_engine() at startup.")
    return _engine


def dispose_engine() -> None:
    """Dispose the engine's connection pool (called on shutdown)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionFactory = None


def _session_factory() -> sessionmaker[Session]:
    if _SessionFactory is None:
        raise RuntimeError("Session factory not initialized; call init_engine() at startup.")
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional Unit-of-Work scope: commit on success, rollback on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session (auto commit/rollback)."""
    with session_scope() as session:
        yield session


def check_database() -> bool:
    """Lightweight connectivity probe used by the health endpoint."""
    try:
        with _session_factory()() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
