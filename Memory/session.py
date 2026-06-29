"""Session memory abstractions for the NARVIS Memory package.

Session memory tracks ephemeral context relevant to an active interaction
session and is designed to be reusable across multiple session-based workflows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository


class SessionMemory(Protocol):
    """Protocol for session-scoped memory services."""

    def store(self, session_id: str, key: str, value: Any, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a value in a named session scope."""

    def recall(self, session_id: str, key: str) -> MemoryEntry | None:
        """Retrieve a session-scoped value."""


class BaseSessionMemory(ABC):
    """Abstract base class for session memory implementations."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @abstractmethod
    def store(self, session_id: str, key: str, value: Any, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a value in a named session scope."""

    @abstractmethod
    def recall(self, session_id: str, key: str) -> MemoryEntry | None:
        """Retrieve a session-scoped value."""


class InMemorySessionMemory(BaseSessionMemory):
    """In-memory session memory implementation."""

    def store(self, session_id: str, key: str, value: Any, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Persist a session-scoped entry using the repository."""
        entry = MemoryEntry(key=f"session:{session_id}:{key}", value=value, category="session", metadata=metadata or {})
        self.repository.save(entry)
        return entry

    def recall(self, session_id: str, key: str) -> MemoryEntry | None:
        """Retrieve a session-scoped entry."""
        return self.repository.load(f"session:{session_id}:{key}")
