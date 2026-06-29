"""Detection abstractions for the NARVIS Vision package.

This module defines reusable interfaces for object detection and face detection
services. Concrete integrations for YOLO, MediaPipe, and similar engines can
be added later through dependency injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .vision import AnalysisResult, ImageFrame


class ObjectDetector(Protocol):
    """Protocol for object detection services."""

    def detect_objects(self, image: ImageFrame) -> list[dict[str, object]]:
        """Return a list of detected object descriptors."""


class FaceDetector(Protocol):
    """Protocol for face detection services."""

    def detect_faces(self, image: ImageFrame) -> list[dict[str, object]]:
        """Return a list of detected face descriptors."""


class BaseObjectDetector(ABC):
    """Abstract base class for object detection implementations."""

    @abstractmethod
    def detect_objects(self, image: ImageFrame) -> list[dict[str, object]]:
        """Detect objects in an image frame."""


class BaseFaceDetector(ABC):
    """Abstract base class for face detection implementations."""

    @abstractmethod
    def detect_faces(self, image: ImageFrame) -> list[dict[str, object]]:
        """Detect faces in an image frame."""


class NullObjectDetector(BaseObjectDetector):
    """Placeholder object detector that returns no results."""

    def detect_objects(self, image: ImageFrame) -> list[dict[str, object]]:
        """Return an empty detection list."""
        return []


class NullFaceDetector(BaseFaceDetector):
    """Placeholder face detector that returns no results."""

    def detect_faces(self, image: ImageFrame) -> list[dict[str, object]]:
        """Return an empty detection list."""
        return []


class DetectionAnalyzer:
    """Reusable orchestrator for object and face detection workflows."""

    def __init__(self, object_detector: ObjectDetector, face_detector: FaceDetector) -> None:
        self.object_detector = object_detector
        self.face_detector = face_detector

    def analyze(self, image: ImageFrame) -> AnalysisResult:
        """Run detection workflows and return a structured analysis result."""
        objects = self.object_detector.detect_objects(image)
        faces = self.face_detector.detect_faces(image)
        return AnalysisResult(
            source="detection",
            summary="detection complete",
            metadata={"objects": len(objects), "faces": len(faces)},
        )
