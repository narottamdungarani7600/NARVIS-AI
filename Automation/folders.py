"""Folder management abstractions for the NARVIS Automation package.

This module defines reusable interfaces for directory operations while keeping
implementation details abstract and platform-neutral.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol


class FolderManager(Protocol):
    """Protocol for folder management services."""

    def create(self, path: str | Path) -> Path:
        """Create a directory at the specified path."""

    def exists(self, path: str | Path) -> bool:
        """Check whether a directory exists."""


class BaseFolderManager(ABC):
    """Abstract base class for folder manager implementations."""

    @abstractmethod
    def create(self, path: str | Path) -> Path:
        """Create a directory at the specified path."""

    @abstractmethod
    def exists(self, path: str | Path) -> bool:
        """Check whether a directory exists."""


class NullFolderManager(BaseFolderManager):
    """No-op folder manager used as a placeholder implementation."""

    def create(self, path: str | Path) -> Path:
        """Return the supplied path without creating it."""
        return Path(path)

    def exists(self, path: str | Path) -> bool:
        """Return False by default."""
        return False
