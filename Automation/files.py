"""File management abstractions for the NARVIS Automation package.

This module defines reusable interfaces for common file operations while keeping
implementation details out of the architectural contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol


class FileManager(Protocol):
    """Protocol for file management services."""

    def read_text(self, path: str | Path) -> str:
        """Read the content of a text file."""

    def write_text(self, path: str | Path, content: str) -> None:
        """Write text content to a file."""

    def exists(self, path: str | Path) -> bool:
        """Check whether a file exists."""


class BaseFileManager(ABC):
    """Abstract base class for file manager implementations."""

    @abstractmethod
    def read_text(self, path: str | Path) -> str:
        """Read the content of a text file."""

    @abstractmethod
    def write_text(self, path: str | Path, content: str) -> None:
        """Write text content to a file."""

    @abstractmethod
    def exists(self, path: str | Path) -> bool:
        """Check whether a file exists."""


class NullFileManager(BaseFileManager):
    """No-op file manager used as a placeholder implementation."""

    def read_text(self, path: str | Path) -> str:
        """Return an empty string."""
        return ""

    def write_text(self, path: str | Path, content: str) -> None:
        """Do nothing."""

    def exists(self, path: str | Path) -> bool:
        """Return False by default."""
        return False
