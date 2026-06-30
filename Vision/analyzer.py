"""High-level analysis services for the NARVIS Vision package."""

from __future__ import annotations

from statistics import mean
from typing import Any, Protocol

from .camera import Camera
from .detector import DetectionAnalyzer
from .image import FileImageLoader
from .ocr import OCRAnalyzer
from .screenshot import ScreenshotCapture
from .vision import AnalysisResult, ImageFrame, _emit_log


class VisionAnalyzer(Protocol):
    """Protocol for composite Vision analysis services."""

    def analyze_frame(self, image: ImageFrame) -> AnalysisResult:
        """Analyze a single image frame."""


class BasicImageAnalyzer:
    """Analyze image metadata, dimensions, size, and simple color statistics."""

    def __init__(self, image_loader: FileImageLoader, logger: Any | None = None) -> None:
        self.image_loader = image_loader
        self._logger = logger
        _emit_log(self._logger, "info", "Image analyzer constructed")

    def initialize(self) -> None:
        """Initialize the image analyzer."""

        _emit_log(self._logger, "info", "Image analyzer initialized")

    def shutdown(self) -> None:
        """Shutdown the image analyzer."""

        _emit_log(self._logger, "info", "Image analyzer shutdown")

    def analyze(self, image: ImageFrame) -> AnalysisResult:
        """Return image metadata and simple descriptive statistics."""

        metadata = {
            "format": image.format,
            "mode": image.mode,
            "resolution": {
                "width": image.width,
                "height": image.height,
            },
            "size_bytes": image.size_bytes,
        }
        if image.width is not None and image.height is not None:
            metadata["pixel_count"] = image.width * image.height

        try:
            raster = self.image_loader.decode(image)
        except Exception as error:
            _emit_log(self._logger, "warning", "Image analysis fallback engaged", error=str(error))
            summary = f"format={image.format}, size={image.size_bytes} bytes"
            return AnalysisResult(source="image", summary=summary, metadata=metadata)

        red_values = [pixel[0] for pixel in raster.pixels]
        green_values = [pixel[1] for pixel in raster.pixels]
        blue_values = [pixel[2] for pixel in raster.pixels]
        color_information = {
            "channel_mean": {
                "red": round(mean(red_values), 2) if red_values else 0.0,
                "green": round(mean(green_values), 2) if green_values else 0.0,
                "blue": round(mean(blue_values), 2) if blue_values else 0.0,
            },
            "channel_min": {
                "red": min(red_values) if red_values else 0,
                "green": min(green_values) if green_values else 0,
                "blue": min(blue_values) if blue_values else 0,
            },
            "channel_max": {
                "red": max(red_values) if red_values else 0,
                "green": max(green_values) if green_values else 0,
                "blue": max(blue_values) if blue_values else 0,
            },
        }
        metadata["color"] = color_information
        summary = (
            f"{image.format.upper()} image "
            f"{raster.width}x{raster.height} "
            f"({image.size_bytes} bytes)"
        )
        _emit_log(
            self._logger,
            "info",
            "Image analysis completed",
            width=raster.width,
            height=raster.height,
            image_format=image.format,
        )
        return AnalysisResult(source="image", summary=summary, metadata=metadata)


class CompositeVisionAnalyzer:
    """Compose image, OCR, and detection workflows behind one analysis service."""

    def __init__(
        self,
        camera: Camera | None = None,
        screenshot_capture: ScreenshotCapture | None = None,
        ocr_analyzer: OCRAnalyzer | None = None,
        detection_analyzer: DetectionAnalyzer | None = None,
        image_analyzer: BasicImageAnalyzer | None = None,
        logger: Any | None = None,
    ) -> None:
        self.camera = camera
        self.screenshot_capture = screenshot_capture
        self.ocr_analyzer = ocr_analyzer
        self.detection_analyzer = detection_analyzer
        self.image_analyzer = image_analyzer
        self._logger = logger
        _emit_log(self._logger, "info", "Composite vision analyzer constructed")

    def initialize(self) -> None:
        """Initialize the composite analyzer."""

        _emit_log(self._logger, "info", "Composite vision analyzer initialized")

    def shutdown(self) -> None:
        """Shutdown the composite analyzer."""

        _emit_log(self._logger, "info", "Composite vision analyzer shutdown")

    def analyze_frame(self, image: ImageFrame) -> AnalysisResult:
        """Analyze an image frame using the configured analyzer services."""

        image_result = (
            self.image_analyzer.analyze(image)
            if self.image_analyzer is not None
            else AnalysisResult(source="image", summary="image analysis unavailable", metadata={})
        )
        ocr_result = (
            self.ocr_analyzer.analyze(image)
            if self.ocr_analyzer is not None
            else AnalysisResult(source="ocr", summary="ocr unavailable", metadata={"text": ""})
        )
        detection_result = (
            self.detection_analyzer.analyze(image)
            if self.detection_analyzer is not None
            else AnalysisResult(source="detection", summary="detection unavailable", metadata={"counts": {}})
        )
        summary_parts = [
            image_result.summary,
            f"OCR: {ocr_result.summary}",
            f"Detection: {detection_result.summary}",
        ]
        _emit_log(self._logger, "info", "Composite vision analysis completed")
        return AnalysisResult(
            source="vision",
            summary=" | ".join(part for part in summary_parts if part),
            metadata={
                "image": image_result.metadata,
                "ocr": ocr_result.metadata,
                "detection": detection_result.metadata,
            },
        )

    def capture_from_camera(self) -> ImageFrame:
        """Capture an image frame from the configured camera."""

        if self.camera is None:
            _emit_log(self._logger, "warning", "Camera capture requested without a configured camera")
            return ImageFrame(data=b"", format="raw", metadata={"source": "camera", "reason": "unconfigured"})
        return self.camera.capture()

    def capture_screen(self) -> ImageFrame:
        """Capture a screenshot frame from the configured screenshot service."""

        if self.screenshot_capture is None:
            _emit_log(
                self._logger,
                "warning",
                "Screenshot capture requested without a configured screenshot service",
            )
            return ImageFrame(data=b"", format="raw", metadata={"source": "screenshot", "reason": "unconfigured"})
        return self.screenshot_capture.capture()


__all__ = [
    "BasicImageAnalyzer",
    "CompositeVisionAnalyzer",
    "VisionAnalyzer",
]
