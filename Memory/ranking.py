"""Ranking and importance scoring utilities for the NARVIS Memory package."""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol

from .memory import MemoryEntry, _emit_log, normalize_text, utc_now

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""

    return _TOKEN_PATTERN.findall(text.lower())


class MemoryRanker(Protocol):
    """Protocol for ranking services over memory entries."""

    def rank(
        self,
        entries: list[MemoryEntry],
        query: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryEntry]:
        """Return memory entries sorted by relevance or importance."""


class BaseMemoryRanker(ABC):
    """Abstract base class for memory ranking implementations."""

    @abstractmethod
    def rank(
        self,
        entries: list[MemoryEntry],
        query: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryEntry]:
        """Return a ranked list of memory entries."""


class ImportanceRanker(BaseMemoryRanker):
    """Rank entries using importance, recency, and optional lexical relevance."""

    def __init__(self, recency_half_life_days: float = 30.0, logger: Any | None = None) -> None:
        self.recency_half_life_days = recency_half_life_days
        self.logger = logger

    def rank(
        self,
        entries: list[MemoryEntry],
        query: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryEntry]:
        """Sort entries by a combined importance and retrieval relevance score."""

        ranked = sorted(
            entries,
            key=lambda entry: (
                self.score_entry(entry, query=query),
                entry.importance,
                entry.timestamp,
                entry.key,
            ),
            reverse=True,
        )
        if limit is not None:
            ranked = ranked[: max(limit, 0)]
        _emit_log(self.logger, "debug", "Ranked memory entries", query=query, count=len(ranked))
        return ranked

    def score_entry(self, entry: MemoryEntry, query: str | None = None, now: datetime | None = None) -> float:
        """Calculate the retrieval score for a single memory entry."""

        reference_time = now or utc_now()
        importance_score = max(0.0, min(1.0, float(entry.importance)))
        recency_score = self._recency_score(entry.timestamp, reference_time)
        query_score = self._query_score(entry, query)
        pinned_bonus = 0.1 if bool(entry.metadata.get("pinned")) else 0.0
        profile_bonus = 0.05 if entry.category == "profile" else 0.0
        return round(
            (importance_score * 0.55)
            + (recency_score * 0.20)
            + (query_score * 0.25)
            + pinned_bonus
            + profile_bonus,
            6,
        )

    def _recency_score(self, timestamp: datetime, now: datetime) -> float:
        """Return an exponential decay score based on entry age."""

        age_seconds = max((now - timestamp).total_seconds(), 0.0)
        half_life_seconds = max(self.recency_half_life_days * 24 * 60 * 60, 1.0)
        return math.pow(0.5, age_seconds / half_life_seconds)

    def _query_score(self, entry: MemoryEntry, query: str | None) -> float:
        """Return a lexical match score for the supplied query."""

        if not query:
            return 0.0

        normalized_query = " ".join(query.lower().split())
        if not normalized_query:
            return 0.0

        tokens = _tokenize(normalized_query)
        if not tokens:
            return 0.0

        entry_text = entry.text_content().lower()
        phrase_score = 1.0 if normalized_query in entry_text else 0.0
        token_coverage = sum(1 for token in tokens if token in entry_text) / len(tokens)
        key_bonus = 0.2 if any(token in entry.key.lower() for token in tokens) else 0.0
        return min(1.0, (phrase_score * 0.45) + (token_coverage * 0.55) + key_bonus)


class MemoryScorer:
    """Utility for generating deterministic importance scores for new entries."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger

    def score(
        self,
        value: object,
        metadata: dict[str, object] | None = None,
        *,
        category: str | None = None,
    ) -> float:
        """Return a simple importance score based on content richness and hints."""

        score = min(len(normalize_text(value)) / 400.0, 0.45)
        metadata = dict(metadata or {})
        score += min(len(metadata) * 0.03, 0.15)
        if metadata.get("pinned") or metadata.get("important"):
            score += 0.25
        if metadata.get("source") in {"profile", "preference", "user"}:
            score += 0.15
        if category == "profile":
            score += 0.20
        elif category == "long_term":
            score += 0.10
        elif category == "conversation_history":
            score += 0.05
        final_score = round(min(score, 1.0), 3)
        _emit_log(self.logger, "debug", "Calculated memory importance score", category=category, score=final_score)
        return final_score


__all__ = ["BaseMemoryRanker", "ImportanceRanker", "MemoryRanker", "MemoryScorer"]
