"""Wikipedia search abstractions for the NARVIS Internet package.

This module defines reusable interfaces for retrieving information from
Wikipedia and can later be backed by dedicated providers or API clients.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class WikipediaResult:
    """Represents a single Wikipedia search result."""

    title: str
    summary: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class WikipediaProvider(Protocol):
    """Protocol for Wikipedia search providers."""

    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Search Wikipedia content for the provided query."""


class BaseWikipediaProvider(ABC):
    """Abstract base class for Wikipedia provider implementations."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Search Wikipedia content for the provided query."""


class NullWikipediaProvider(BaseWikipediaProvider):
    """No-op Wikipedia provider used as a placeholder implementation."""

    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Return an empty result list."""
        return []
