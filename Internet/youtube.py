"""YouTube search abstractions for the NARVIS Internet package.

This module defines reusable interfaces for YouTube content discovery and can
later be implemented by specific providers or API wrappers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class YouTubeResult:
    """Represents a single YouTube search result."""

    title: str
    video_id: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class YouTubeProvider(Protocol):
    """Protocol for YouTube search providers."""

    def search(self, query: str, limit: int = 10) -> list[YouTubeResult]:
        """Search for YouTube content related to the provided query."""


class BaseYouTubeProvider(ABC):
    """Abstract base class for YouTube provider implementations."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[YouTubeResult]:
        """Search for YouTube content related to the provided query."""


class NullYouTubeProvider(BaseYouTubeProvider):
    """No-op YouTube provider used as a placeholder implementation."""

    def search(self, query: str, limit: int = 10) -> list[YouTubeResult]:
        """Return an empty result list."""
        return []
