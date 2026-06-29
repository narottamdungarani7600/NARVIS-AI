"""File download abstractions for the NARVIS Internet package.

This module defines reusable interfaces for downloading remote content and can
be backed by different HTTP libraries or streaming implementations later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol


class FileDownloader(Protocol):
    """Protocol for file downloader services."""

    def download(self, url: str, destination: str | Path) -> Path:
        """Download a file from a URL to the provided destination."""


class BaseFileDownloader(ABC):
    """Abstract base class for file downloader implementations."""

    @abstractmethod
    def download(self, url: str, destination: str | Path) -> Path:
        """Download a file to the given destination path."""


class NullFileDownloader(BaseFileDownloader):
    """No-op downloader used as a placeholder implementation."""

    def download(self, url: str, destination: str | Path) -> Path:
        """Create the destination path and return it without downloading content."""
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.touch(exist_ok=True)
        return destination_path
