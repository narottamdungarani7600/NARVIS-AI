"""Short-term memory abstractions for the NARVIS Memory package.

Short-term memory is intended for transient, high-relevance context that can
change frequently during a session. This module provides reusable interfaces and
an in-memory implementation that can later be backed by more durable storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository


class ShortTermMemory(Protocol):
    """Protocol for short-term memory services."""

    def store(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a transient memory entry."""

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a short-term memory entry."""

    def clear(self) -> None:
        """Clear all short-term memory entries."""


class BaseShortTermMemory(ABC):
    """Abstract base class for short-term memory implementations."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @abstractmethod
    def store(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a transient memory entry."""

    @abstractmethod
    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a short-term memory entry."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all short-term memory entries."""


class InMemoryShortTermMemory(BaseShortTermMemory):
    """In-memory short-term memory implementation for development and testing."""

    def store(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a short-term entry using the configured repository."""
        entry = MemoryEntry(key=key, value=value, category="short_term", importance=importance, metadata=metadata or {})
        self.repository.save(entry)
        return entry

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve a short-term entry by key."""
        return self.repository.load(key)

    def clear(self) -> None:
        """Clear all short-term entries by removing all entries from the repository."""
        for entry in self.repository.list_entries(category="short_term"):
            self.repository.delete(entry.key)
