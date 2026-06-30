"""Short-term memory services for the NARVIS Memory package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository, _emit_log
from .ranking import MemoryScorer


class ShortTermMemory(Protocol):
    """Protocol for short-term memory services."""

    def store(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a transient memory entry."""

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a short-term memory entry."""

    def clear(self) -> None:
        """Clear all short-term memory entries."""


class BaseShortTermMemory(ABC):
    """Abstract base class for short-term memory implementations."""

    def __init__(
        self,
        repository: MemoryRepository,
        scorer: MemoryScorer | None = None,
        logger: Any | None = None,
    ) -> None:
        self.repository = repository
        self.scorer = scorer or MemoryScorer(logger=logger)
        self.logger = logger

    @abstractmethod
    def store(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a transient memory entry."""

    @abstractmethod
    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a short-term memory entry."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all short-term memory entries."""


class InMemoryShortTermMemory(BaseShortTermMemory):
    """Repository-backed short-term memory implementation."""

    def store(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a short-term entry using the configured repository."""

        normalized_metadata = dict(metadata or {})
        resolved_importance = importance if importance > 0.0 else self.scorer.score(
            value,
            normalized_metadata,
            category="short_term",
        )
        entry = MemoryEntry(
            key=key,
            value=value,
            category="short_term",
            importance=resolved_importance,
            metadata=normalized_metadata,
        )
        self.repository.save(entry)
        _emit_log(self.logger, "debug", "Stored short-term memory", key=key, importance=resolved_importance)
        return entry

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a short-term entry by key."""

        entry = self.repository.load(key)
        if entry is None or entry.category != "short_term":
            return None
        _emit_log(self.logger, "debug", "Recalled short-term memory", key=key)
        return entry

    def clear(self) -> None:
        """Clear all short-term entries by removing them from the repository."""

        entries = self.repository.list_entries(category="short_term")
        for entry in entries:
            self.repository.delete(entry.key)
        _emit_log(self.logger, "info", "Cleared short-term memory", count=len(entries))

    def list_entries(self, limit: int | None = None) -> list[MemoryEntry]:
        """Return short-term entries ordered by importance and recency."""

        entries = self.repository.list_entries(category="short_term")
        if limit is not None:
            return entries[: max(limit, 0)]
        return entries


__all__ = ["BaseShortTermMemory", "InMemoryShortTermMemory", "ShortTermMemory"]
