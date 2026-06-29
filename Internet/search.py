"""Search provider abstractions for the NARVIS Internet package.

This module defines reusable interfaces for search providers and can later be
implemented by Google Search, DuckDuckGo, Bing, or other engines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class SearchResult:
    """Represents a single search result entry."""

    title: str
    url: str
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SearchProvider(Protocol):
    """Protocol for search providers."""

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for results related to the provided query."""


class BaseSearchProvider(ABC):
    """Abstract base class for search provider implementations."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for results related to the provided query."""


class NullSearchProvider(BaseSearchProvider):
    """No-op search provider used as a placeholder implementation."""

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return an empty list of results."""
        return []
