"""Port: ticket-processing strategies (summary / spam / routing).

A deterministic, rule-based adapter implements these today; an LLM-backed adapter can replace
the summary provider later without changing the worker pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SummaryProvider(Protocol):
    """Produce a short summary from a ticket's subject and description."""

    def summarize(self, subject: str, description: str) -> str: ...
