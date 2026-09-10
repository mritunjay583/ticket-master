"""Deterministic (rule-based) SummaryProvider.

Implements the ``SummaryProvider`` port without any ML — the brief permits simulation. Isolated
behind the port so a real LLM-backed provider can be swapped in later without touching the worker
pipeline.
"""

from __future__ import annotations

_MAX_SUMMARY_LEN = 160


class DeterministicSummaryProvider:
    """Produce a short, deterministic summary from a ticket's subject + description."""

    def summarize(self, subject: str, description: str) -> str:
        subject = (subject or "").strip()
        description = " ".join((description or "").split())  # collapse whitespace
        combined = f"{subject}: {description}" if subject else description
        if len(combined) <= _MAX_SUMMARY_LEN:
            return combined
        return combined[: _MAX_SUMMARY_LEN - 1].rstrip() + "…"
