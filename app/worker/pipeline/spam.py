"""Spam detection step (deterministic heuristic simulation)."""

from __future__ import annotations

# Lowercase keywords/phrases that strongly indicate spam.
_SPAM_SIGNALS = (
    "free money",
    "winner",
    "you won",
    "lottery",
    "click here",
    "buy now",
    "limited offer",
    "act now",
    "crypto",
    "viagra",
    "prince",
    "wire transfer",
    "bitcoin",
    "100% free",
)


def detect_spam(subject: str, description: str) -> bool:
    """Return True if the ticket text looks like spam.

    Heuristic: any known spam signal appears in subject or description. Deterministic and
    dependency-free (the brief permits simulation).
    """
    text = f"{subject} {description}".lower()
    return any(signal in text for signal in _SPAM_SIGNALS)
