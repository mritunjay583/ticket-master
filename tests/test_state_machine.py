"""Unit tests for the ticket status state machine (pure logic, no DB)."""

from __future__ import annotations

import pytest

from app.core.errors import InvalidTransitionError
from app.schemas.enums import TicketStatus
from app.services.state_machine import can_transition, validate_transition

S = TicketStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.OPEN, S.IN_PROGRESS),
        (S.OPEN, S.RESOLVED),
        (S.IN_PROGRESS, S.RESOLVED),
        (S.IN_PROGRESS, S.OPEN),
        (S.RESOLVED, S.CLOSED),
        (S.RESOLVED, S.OPEN),
        (S.CLOSED, S.OPEN),
    ],
)
def test_allowed_transitions(current: TicketStatus, target: TicketStatus) -> None:
    assert can_transition(current, target) is True
    validate_transition(current, target)  # should not raise


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.OPEN, S.CLOSED),
        (S.IN_PROGRESS, S.CLOSED),
        (S.CLOSED, S.RESOLVED),
        (S.CLOSED, S.IN_PROGRESS),
        (S.RESOLVED, S.IN_PROGRESS),
    ],
)
def test_disallowed_transitions_raise(current: TicketStatus, target: TicketStatus) -> None:
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError):
        validate_transition(current, target)


def test_noop_transition_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(S.OPEN, S.OPEN)


def test_error_carries_allowed_list() -> None:
    try:
        validate_transition(S.IN_PROGRESS, S.CLOSED)
    except InvalidTransitionError as exc:
        assert exc.status_code == 409
        assert exc.code == "INVALID_TRANSITION"
        assert exc.additional_info is not None
        assert "allowed" in exc.additional_info
    else:  # pragma: no cover
        pytest.fail("expected InvalidTransitionError")
