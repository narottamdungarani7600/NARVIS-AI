"""Long-term memory abstractions for the NARVIS Memory package.

Long-term memory is intended for durable, persistent context that should remain
available across sessions. This module provides reusable interfaces and a base
implementation that can later be backed by SQLite, a vector database, or a
remote service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository


class LongTermMemory(Protocol):
    """Protocol for long-term memory services."""

    def store(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a durable memory entry."""

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a stored memory entry."""


class BaseLongTermMemory(ABC):
    """Abstract base class for long-term memory implementations."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @abstractmethod
    def store(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a durable memory entry."""

    @abstractmethod
    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a stored memory entry."""


class InMemoryLongTermMemory(BaseLongTermMemory):
    """In-memory long-term memory implementation for the initial architecture."""

    def store(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Persist a memory entry using the configured repository."""
        entry = MemoryEntry(key=key, value=value, category="long_term", importance=importance, metadata=metadata or {})
        self.repository.save(entry)
        return entry

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a memory entry by key."""
        return self.repository.load(key)
