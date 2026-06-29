"""Core memory abstractions for the NARVIS Memory package.

This module defines reusable memory contracts and shared data structures that
provide a stable foundation for short-term, long-term, session, and profile
memory systems without embedding AI-specific logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(slots=True)
class MemoryEntry:
    """Represents a single memory entry stored by the system."""

    key: str
    value: Any
    category: str = "general"
    importance: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryStore(Protocol):
    """Protocol for storage implementations used by the memory system."""

    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry."""

    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by its key."""

    def delete(self, key: str) -> None:
        """Delete a memory entry by its key."""

    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """Return stored memory entries, optionally filtered by category."""


class MemoryRepository(ABC):
    """Abstract repository interface for memory-backed services."""

    @abstractmethod
    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry."""

    @abstractmethod
    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by its key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a memory entry by its key."""

    @abstractmethod
    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """Return stored memory entries, optionally filtered by category."""


class SemanticMemory(Protocol):
    """Protocol for future semantic memory backends such as vector databases."""

    def add(self, entry: MemoryEntry) -> None:
        """Add a memory entry to the semantic memory backend."""

    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Search semantic memory using a query string."""
