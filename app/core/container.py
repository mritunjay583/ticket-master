"""Composition root: the single place that wires concrete adapters to ports.

Everything technology-specific is assembled here. Routers/services receive dependencies from
this container (via FastAPI ``Depends``), so swapping a backend is a change confined to this file
plus the new adapter module.

In Phase 0 the container only carries settings; repository/queue adapters are registered in
Phases 2 and 3 respectively.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class Container:
    """Holds fully-wired application dependencies."""

    settings: Settings


_container: Container | None = None


def build_container(settings: Settings | None = None) -> Container:
    """Create (once) and return the application container."""
    global _container
    if _container is None:
        _container = Container(settings=settings or get_settings())
    return _container


def get_container() -> Container:
    """FastAPI dependency returning the shared container."""
    if _container is None:
        return build_container()
    return _container
