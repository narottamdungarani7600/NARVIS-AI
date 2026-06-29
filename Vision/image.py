"""Image loading and preprocessing abstractions for the NARVIS Vision package.

This module provides reusable interfaces for image loading, normalization, and
preprocessing so future computer-vision engines can be integrated through
dependency injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .vision import ImageFrame


class ImageLoader(Protocol):
    """Protocol for image loading services."""

    def load(self, source: str) -> ImageFrame:
        """Load an image frame from a source path or identifier."""


class BaseImageLoader(ABC):
    """Abstract base class for image loading implementations."""

    @abstractmethod
    def load(self, source: str) -> ImageFrame:
        """Load an image frame from a source path or identifier."""


class ImagePreprocessor(Protocol):
    """Protocol for image preprocessing services."""

    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Transform an image frame into a normalized representation."""


class BaseImagePreprocessor(ABC):
    """Abstract base class for image preprocessing implementations."""

    @abstractmethod
    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Transform the supplied image frame."""


class PassthroughImagePreprocessor(BaseImagePreprocessor):
    """A no-op preprocessor that leaves the image unchanged."""

    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Return the original image frame."""
        return image


class FileImageLoader(BaseImageLoader):
    """Simple file-based image loader placeholder implementation."""

    def load(self, source: str) -> ImageFrame:
        """Return a placeholder image frame for the provided source path."""
        with open(source, "rb") as handle:
            return ImageFrame(data=handle.read(), metadata={"source": source})
