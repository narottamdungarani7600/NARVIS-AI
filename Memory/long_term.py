"""Long-term memory services for the NARVIS Memory package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository, _emit_log
from .ranking import MemoryScorer


class LongTermMemory(Protocol):
    """Protocol for long-term memory services."""

    def store(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a durable memory entry."""

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a stored memory entry."""


class BaseLongTermMemory(ABC):
    """Abstract base class for long-term memory implementations."""

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
        """Store a durable memory entry."""

    @abstractmethod
    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a stored memory entry."""


class InMemoryLongTermMemory(BaseLongTermMemory):
    """Repository-backed long-term memory implementation."""

    def store(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Persist a long-term memory entry using the configured repository."""

        normalized_metadata = dict(metadata or {})
        resolved_importance = importance if importance > 0.0 else self.scorer.score(
            value,
            normalized_metadata,
            category="long_term",
        )
        entry = MemoryEntry(
            key=key,
            value=value,
            category="long_term",
            importance=resolved_importance,
            metadata=normalized_metadata,
        )
        self.repository.save(entry)
        _emit_log(self.logger, "debug", "Stored long-term memory", key=key, importance=resolved_importance)
        return entry

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a long-term memory entry by key."""

        entry = self.repository.load(key)
        if entry is None or entry.category != "long_term":
            return None
        _emit_log(self.logger, "debug", "Recalled long-term memory", key=key)
        return entry

    def list_entries(self, limit: int | None = None) -> list[MemoryEntry]:
        """Return long-term memory entries ordered by repository defaults."""

        entries = self.repository.list_entries(category="long_term")
        if limit is not None:
            return entries[: max(limit, 0)]
        return entries


__all__ = ["BaseLongTermMemory", "InMemoryLongTermMemory", "LongTermMemory"]
