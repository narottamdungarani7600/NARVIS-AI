"""Screenshot capture abstractions for the NARVIS Vision package.

This module defines reusable interfaces for capturing screen content and can be
implemented using different platform-specific backends in the future.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .vision import ImageFrame


class ScreenshotCapture(Protocol):
    """Protocol for screenshot capture services."""

    def capture(self) -> ImageFrame:
        """Capture and return the current screen contents as an image frame."""


class BaseScreenshotCapture(ABC):
    """Abstract base class for screenshot capture implementations."""

    @abstractmethod
    def capture(self) -> ImageFrame:
        """Capture and return a screenshot frame."""


class NullScreenshotCapture(BaseScreenshotCapture):
    """A placeholder screenshot implementation that returns an empty frame."""

    def capture(self) -> ImageFrame:
        """Return an empty image frame."""
        return ImageFrame(data=b"")
