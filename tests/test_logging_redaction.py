"""Tests for the JSON log formatter and sensitive-value redaction (Layer 2)."""

from __future__ import annotations

import json
import logging

from app.core.logging import REDACTED, JsonFormatter, request_id_ctx


def _make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event happened",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_basic_fields_are_rendered() -> None:
    payload = json.loads(JsonFormatter().format(_make_record()))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"
    assert payload["message"] == "event happened"


def test_custom_extras_are_included() -> None:
    payload = json.loads(JsonFormatter().format(_make_record(ticket_id=42, priority="high")))
    assert payload["ticket_id"] == 42
    assert payload["priority"] == "high"


def test_sensitive_keys_are_redacted() -> None:
    payload = json.loads(
        JsonFormatter().format(
            _make_record(password="hunter2", api_key="abc123", authorization="Bearer x")
        )
    )
    assert payload["password"] == REDACTED
    assert payload["api_key"] == REDACTED
    assert payload["authorization"] == REDACTED


def test_substring_match_redacts_related_keys() -> None:
    payload = json.loads(
        JsonFormatter().format(_make_record(db_password="s3cret", user_token="t0ken"))
    )
    assert payload["db_password"] == REDACTED
    assert payload["user_token"] == REDACTED


def test_request_id_included_when_set() -> None:
    token = request_id_ctx.set("req-123")
    try:
        payload = json.loads(JsonFormatter().format(_make_record()))
    finally:
        request_id_ctx.reset(token)
    assert payload["request_id"] == "req-123"
