"""Search and retrieval abstractions for the NARVIS Memory package.

This module defines reusable search interfaces and a simple implementation for
querying stored memory entries. It is intentionally generic and can be adapted
for future vector database systems.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .memory import MemoryEntry, MemoryRepository


class MemorySearch(Protocol):
    """Protocol for memory search services."""

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search stored memory using a query string."""


class BaseMemorySearch(ABC):
    """Abstract base class for memory-search implementations."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @abstractmethod
    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search stored memory using a query string."""


class SimpleMemorySearch(BaseMemorySearch):
    """Basic text-based memory search implementation."""

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search entries whose text values contain the query string."""
        entries = self.repository.list_entries(category=category)
        normalized_query = query.lower()
        filtered = [entry for entry in entries if isinstance(entry.value, str) and normalized_query in entry.value.lower()]
        return filtered[:limit]
