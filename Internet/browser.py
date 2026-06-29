"""Browser interface abstractions for the NARVIS Internet package.

This module defines reusable browser contracts that can be implemented by
future web automation or browsing backends without embedding application logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class Browser(Protocol):
    """Protocol for browser-like interfaces."""

    def open(self, url: str) -> None:
        """Open a URL in the browser."""

    def close(self) -> None:
        """Close the active browser session."""


class BaseBrowser(ABC):
    """Abstract base class for browser implementations."""

    @abstractmethod
    def open(self, url: str) -> None:
        """Open a URL in a browser implementation."""

    @abstractmethod
    def close(self) -> None:
        """Close the browser implementation."""


class NullBrowser(BaseBrowser):
    """No-op browser implementation used for offline or test scenarios."""

    def open(self, url: str) -> None:
        """Do nothing."""

    def close(self) -> None:
        """Do nothing."""
