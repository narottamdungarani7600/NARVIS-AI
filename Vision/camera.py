"""Camera capture abstractions for the NARVIS Vision package.

This module provides reusable interfaces for acquiring visual data from a
camera source and can later be backed by OpenCV, GStreamer, or other runtime
providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .vision import ImageFrame


class Camera(Protocol):
    """Protocol for camera capture services."""

    def capture(self) -> ImageFrame:
        """Capture and return a single image frame."""


class BaseCamera(ABC):
    """Abstract base class for camera implementations."""

    @abstractmethod
    def capture(self) -> ImageFrame:
        """Capture and return an image frame."""


class NullCamera(BaseCamera):
    """A placeholder camera implementation that returns an empty frame."""

    def capture(self) -> ImageFrame:
        """Return an empty image frame."""
        return ImageFrame(data=b"")
