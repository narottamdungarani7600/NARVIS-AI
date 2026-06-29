"""Core vision abstractions for the NARVIS Vision package.

This module defines reusable data structures and contracts for images, visual
analysis, and future computer-vision integrations such as OpenCV, OCR engines,
and object detectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ImageFrame:
    """Represents an image payload used by vision components."""

    data: bytes
    width: int | None = None
    height: int | None = None
    format: str = "raw"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalysisResult:
    """Represents the outcome of a visual analysis task."""

    source: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageLoader(Protocol):
    """Protocol for loading images from a source."""

    def load(self, source: str) -> ImageFrame:
        """Load an image frame from the provided source."""


class ImagePreprocessor(Protocol):
    """Protocol for preparing images for downstream analysis."""

    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Transform an image frame into a normalized representation."""
