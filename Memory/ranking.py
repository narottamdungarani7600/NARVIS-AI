"""Ranking and importance scoring abstractions for the NARVIS Memory package.

This module defines reusable scoring interfaces and a deterministic ranking
strategy that can later be extended with more advanced heuristics or external
ranking services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .memory import MemoryEntry


class MemoryRanker(Protocol):
    """Protocol for ranking services over memory entries."""

    def rank(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """Return memory entries sorted by relevance or importance."""


class BaseMemoryRanker(ABC):
    """Abstract base class for memory ranking implementations."""

    @abstractmethod
    def rank(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """Return a ranked list of memory entries."""


class ImportanceRanker(BaseMemoryRanker):
    """Simple ranking implementation based on importance and recency."""

    def rank(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """Sort entries by importance descending and timestamp descending."""
        return sorted(
            entries,
            key=lambda entry: (entry.importance, entry.timestamp),
            reverse=True,
        )


class MemoryScorer:
    """Utility for calculating a simple importance score for memory entries."""

    def score(self, value: object, metadata: dict[str, object] | None = None) -> float:
        """Return a simple, deterministic importance score."""
        base = 0.0
        if isinstance(value, str):
            base += min(len(value) / 100.0, 1.0)
        if metadata:
            base += min(len(metadata) * 0.1, 1.0)
        return round(base, 3)
