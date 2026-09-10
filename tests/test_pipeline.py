"""Unit tests for the processing pipeline steps (pure logic, no DB / no Redis)."""

from __future__ import annotations

from app.adapters.processing.deterministic_summary import DeterministicSummaryProvider
from app.schemas.enums import Department, TicketCategory, TicketPriority
from app.worker.pipeline.prioritize import assign_priority
from app.worker.pipeline.route import route_department
from app.worker.pipeline.spam import detect_spam


class TestSummary:
    def test_short_text_kept_whole(self) -> None:
        s = DeterministicSummaryProvider().summarize("Login broken", "Cannot log in.")
        assert s == "Login broken: Cannot log in."

    def test_long_text_truncated_with_ellipsis(self) -> None:
        s = DeterministicSummaryProvider().summarize("Subj", "x" * 500)
        assert len(s) <= 160
        assert s.endswith("…")

    def test_whitespace_collapsed(self) -> None:
        s = DeterministicSummaryProvider().summarize("A", "b    c\n\n d")
        assert s == "A: b c d"


class TestSpam:
    def test_detects_spam_keywords(self) -> None:
        assert detect_spam("You won the lottery", "click here now") is True

    def test_clean_text_not_spam(self) -> None:
        assert detect_spam("Cannot login", "The app errors on login") is False


class TestPrioritize:
    def test_spam_is_low(self) -> None:
        assert assign_priority("winner", "free money", is_spam=True) == TicketPriority.LOW

    def test_urgent_keywords(self) -> None:
        assert assign_priority("URGENT outage", "system down", False) == TicketPriority.URGENT

    def test_high_keywords(self) -> None:
        assert assign_priority("App error", "login failed", False) == TicketPriority.HIGH

    def test_low_keywords(self) -> None:
        assert assign_priority("Question", "how do i export", False) == TicketPriority.LOW

    def test_default_medium(self) -> None:
        assert assign_priority("Hello", "some neutral text", False) == TicketPriority.MEDIUM


class TestRoute:
    def test_spam_routes_to_triage(self) -> None:
        assert route_department(TicketCategory.BILLING, is_spam=True) == Department.TRIAGE

    def test_category_mapping(self) -> None:
        assert route_department(TicketCategory.BILLING, False) == Department.BILLING
        assert route_department(TicketCategory.TECHNICAL, False) == Department.ENGINEERING
        assert route_department(TicketCategory.ACCOUNT, False) == Department.ACCOUNT_MANAGEMENT
        assert route_department(TicketCategory.GENERAL, False) == Department.SUPPORT
