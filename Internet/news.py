"""News provider abstractions for the NARVIS Internet package.

This module defines reusable interfaces for news retrieval and can later be
implemented by RSS, REST APIs, or news aggregation services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class NewsArticle:
    """Represents a single news article entry."""

    title: str
    url: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class NewsProvider(Protocol):
    """Protocol for news provider services."""

    def fetch(self, topic: str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Fetch news articles for a topic."""


class BaseNewsProvider(ABC):
    """Abstract base class for news provider implementations."""

    @abstractmethod
    def fetch(self, topic: str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Fetch news articles for a topic."""


class NullNewsProvider(BaseNewsProvider):
    """No-op news provider used as a placeholder implementation."""

    def fetch(self, topic: str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Return an empty article list."""
        return []
