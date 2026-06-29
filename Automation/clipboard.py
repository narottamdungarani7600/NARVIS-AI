"""Clipboard management abstractions for the NARVIS Automation package.

This module provides reusable interfaces for reading from and writing to a
clipboard abstraction without coupling the design to a specific platform.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class ClipboardManager(Protocol):
    """Protocol for clipboard management services."""

    def read(self) -> str:
        """Read the current clipboard contents."""

    def write(self, text: str) -> None:
        """Write text to the clipboard."""


class BaseClipboardManager(ABC):
    """Abstract base class for clipboard manager implementations."""

    @abstractmethod
    def read(self) -> str:
        """Read clipboard contents."""

    @abstractmethod
    def write(self, text: str) -> None:
        """Write clipboard contents."""


class NullClipboardManager(BaseClipboardManager):
    """No-op clipboard manager used as a placeholder implementation."""

    def read(self) -> str:
        """Return an empty string."""
        return ""

    def write(self, text: str) -> None:
        """Do nothing."""
