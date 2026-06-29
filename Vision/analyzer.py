"""High-level image analysis orchestration for the NARVIS Vision package.

This module provides reusable analysis services that compose camera capture,
screenshot capture, image preprocessing, OCR, and detection components without
introducing application-specific logic.
"""

from __future__ import annotations

from typing import Protocol

from .camera import Camera
from .detector import DetectionAnalyzer
from .ocr import OCRAnalyzer
from .screenshot import ScreenshotCapture
from .vision import AnalysisResult, ImageFrame


class VisionAnalyzer(Protocol):
    """Protocol for composite vision analysis services."""

    def analyze_frame(self, image: ImageFrame) -> AnalysisResult:
        """Analyze a single image frame."""


class CompositeVisionAnalyzer:
    """Composes camera, OCR, and detection analysis into a reusable analyzer."""

    def __init__(self, camera: Camera | None = None, screenshot_capture: ScreenshotCapture | None = None, ocr_analyzer: OCRAnalyzer | None = None, detection_analyzer: DetectionAnalyzer | None = None) -> None:
        self.camera = camera
        self.screenshot_capture = screenshot_capture
        self.ocr_analyzer = ocr_analyzer
        self.detection_analyzer = detection_analyzer

    def analyze_frame(self, image: ImageFrame) -> AnalysisResult:
        """Analyze an image frame using the configured analyzers."""
        if self.ocr_analyzer is not None:
            ocr_result = self.ocr_analyzer.analyze(image)
        else:
            ocr_result = AnalysisResult(source="ocr", summary="")

        if self.detection_analyzer is not None:
            detection_result = self.detection_analyzer.analyze(image)
        else:
            detection_result = AnalysisResult(source="detection", summary="")

        return AnalysisResult(
            source="vision",
            summary="analysis complete",
            metadata={"ocr": ocr_result.metadata, "detection": detection_result.metadata},
        )

    def capture_from_camera(self) -> ImageFrame:
        """Capture an image frame from the configured camera."""
        if self.camera is None:
            return ImageFrame(data=b"")
        return self.camera.capture()

    def capture_screen(self) -> ImageFrame:
        """Capture a screenshot frame from the configured screen capture service."""
        if self.screenshot_capture is None:
            return ImageFrame(data=b"")
        return self.screenshot_capture.capture()
