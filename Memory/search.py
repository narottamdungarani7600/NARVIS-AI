"""Search and retrieval services for the NARVIS Memory package."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository, _emit_log
from .ranking import ImportanceRanker, MemoryRanker

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Split text into normalized alphanumeric tokens."""

    return _TOKEN_PATTERN.findall(text.lower())


class MemorySearch(Protocol):
    """Protocol for memory search services."""

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search stored memory using a query string."""


class BaseMemorySearch(ABC):
    """Abstract base class for memory-search implementations."""

    def __init__(
        self,
        repository: MemoryRepository,
        ranker: MemoryRanker | None = None,
        logger: Any | None = None,
    ) -> None:
        self.repository = repository
        self.ranker = ranker or ImportanceRanker(logger=logger)
        self.logger = logger

    @abstractmethod
    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search stored memory using a query string."""


class SimpleMemorySearch(BaseMemorySearch):
    """Basic ranked retrieval over stored memory records."""

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search entries by key, value, and metadata text with ranking."""

        normalized_query = " ".join(query.strip().split())
        if not normalized_query or limit <= 0:
            return []

        candidates = self._load_candidates(normalized_query, category=category, limit=limit)
        matched = [entry for entry in candidates if self._matches(entry, normalized_query)]
        try:
            ranked = self.ranker.rank(matched, query=normalized_query, limit=limit)
        except TypeError:
            ranked = self.ranker.rank(matched)[:limit]

        _emit_log(
            self.logger,
            "debug",
            "Searched memory",
            query=normalized_query,
            category=category,
            candidates=len(candidates),
            matches=len(ranked),
        )
        return ranked[:limit]

    def search_history(self, session_id: str, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Search only persisted conversation history for a specific session."""

        results = self.search(query, category="conversation_history", limit=max(limit * 3, limit))
        filtered = [entry for entry in results if entry.metadata.get("session_id") == session_id]
        return filtered[:limit]

    def _load_candidates(self, query: str, category: str | None, limit: int) -> list[MemoryEntry]:
        """Load candidate entries from the repository."""

        repository_search = getattr(self.repository, "search_entries", None)
        if callable(repository_search):
            return list(repository_search(query, category=category, limit=max(limit * 5, limit)))
        return list(self.repository.list_entries(category=category))

    def _matches(self, entry: MemoryEntry, query: str) -> bool:
        """Return whether an entry matches a query well enough to rank."""

        search_text = entry.text_content().lower()
        normalized_query = query.lower()
        if normalized_query in search_text:
            return True

        tokens = _tokenize(normalized_query)
        if not tokens:
            return False
        return any(token in search_text for token in tokens)


__all__ = ["BaseMemorySearch", "MemorySearch", "SimpleMemorySearch"]
