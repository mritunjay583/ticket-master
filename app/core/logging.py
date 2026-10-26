"""Structured JSON logging with request-id correlation.

A ``ContextVar`` carries the current request id so every log line emitted while handling
a request is automatically tagged with it, without threading the id through call sites.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Holds the current request id for the active request/task context.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Redaction (defense-in-depth): if a structured extra uses one of these key names, its value is
# masked in the log output. This does NOT replace the primary rule — never log secrets — but it
# automatically catches the common accidental case (e.g. extra={"password": ...}).
REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "card_number",
        "cvv",
        "ssn",
    }
)


def _redact(key: str, value: Any) -> Any:
    """Mask the value if the key looks sensitive (case-insensitive, substring match)."""
    lowered = key.lower()
    if any(sensitive in lowered for sensitive in _SENSITIVE_KEYS):
        return REDACTED
    return value


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Include any structured extras attached via logger.info(..., extra={...}),
        # redacting values whose key looks sensitive.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = _redact(key, value)
        return json.dumps(payload, default=str)


# Standard LogRecord attributes we do not want to duplicate into the JSON payload.
_RESERVED_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger to emit structured JSON to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn's own loggers should propagate through our handler, not double-log.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
