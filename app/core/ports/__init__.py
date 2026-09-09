"""Ports: abstract interfaces the domain depends on.

Modules in this package MUST NOT import concrete adapters (SQLAlchemy repos, RQ, Redis, etc.).
The domain (``app.services``) depends only on these interfaces; concrete adapters are wired to
them in exactly one place: ``app.core.container``.
"""
