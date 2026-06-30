"""Core Vision contracts, models, and runtime registration for NARVIS.

This module defines the shared ``ImageFrame`` and ``AnalysisResult`` payloads
used throughout the Vision package, plus the dependency-injection helpers used
to register Vision services inside the NARVIS runtime container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from Core.system import HealthReport

if TYPE_CHECKING:
    from .analyzer import BasicImageAnalyzer, CompositeVisionAnalyzer
    from .camera import BaseCamera
    from .detector import (
        BaseBarcodeDetector,
        BaseFaceDetector,
        BaseObjectDetector,
        BaseQRDetector,
        DetectionAnalyzer,
    )
    from .image import BaseImagePreprocessor, FileImageLoader
    from .ocr import BaseOCRService, OCRAnalyzer
    from .screenshot import BaseScreenshotCapture


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a structured log message through either supported logger contract."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


@dataclass(slots=True)
class ImageFrame:
    """Represents an image payload shared between Vision services."""

    data: bytes
    width: int | None = None
    height: int | None = None
    format: str = "raw"
    mode: str = "RGB"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        """Return the size of the underlying image payload in bytes."""

        return len(self.data)

    def is_empty(self) -> bool:
        """Return whether the frame contains any image payload."""

        return self.size_bytes == 0


@dataclass(slots=True)
class AnalysisResult:
    """Represents the outcome of a visual analysis task."""

    source: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageLoader(Protocol):
    """Protocol for loading images from a source."""

    def load(self, source: str | Path) -> ImageFrame:
        """Load an image frame from the provided source."""


class ImagePreprocessor(Protocol):
    """Protocol for preparing images for downstream analysis."""

    def preprocess(self, image: ImageFrame) -> ImageFrame:
        """Transform an image frame into a normalized representation."""


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Vision."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class EventPublisher(Protocol):
    """Protocol for runtime event publishers used by Vision hooks."""

    def publish(self, event: Any) -> None:
        """Publish a runtime event."""


@dataclass(slots=True)
class VisionServices:
    """Container for the concrete services that make up the Vision module."""

    vision_service: VisionService
    vision_analyzer: CompositeVisionAnalyzer
    image_loader: FileImageLoader
    image_preprocessor: BaseImagePreprocessor
    image_analyzer: BasicImageAnalyzer
    ocr_service: BaseOCRService
    ocr_analyzer: OCRAnalyzer
    detection_analyzer: DetectionAnalyzer
    camera: BaseCamera
    screenshot_capture: BaseScreenshotCapture
    object_detector: BaseObjectDetector
    face_detector: BaseFaceDetector
    barcode_detector: BaseBarcodeDetector
    qr_detector: BaseQRDetector


class VisionService:
    """Central lifecycle and orchestration service for the Vision module."""

    def __init__(
        self,
        *,
        camera: BaseCamera,
        screenshot_capture: BaseScreenshotCapture,
        image_loader: FileImageLoader,
        image_preprocessor: BaseImagePreprocessor,
        image_analyzer: BasicImageAnalyzer,
        ocr_service: BaseOCRService,
        ocr_analyzer: OCRAnalyzer,
        detection_analyzer: DetectionAnalyzer,
        vision_analyzer: CompositeVisionAnalyzer,
        object_detector: BaseObjectDetector,
        face_detector: BaseFaceDetector,
        barcode_detector: BaseBarcodeDetector,
        qr_detector: BaseQRDetector,
        logger: Any | None = None,
    ) -> None:
        self.camera = camera
        self.screenshot_capture = screenshot_capture
        self.image_loader = image_loader
        self.image_preprocessor = image_preprocessor
        self.image_analyzer = image_analyzer
        self.ocr_service = ocr_service
        self.ocr_analyzer = ocr_analyzer
        self.detection_analyzer = detection_analyzer
        self.vision_analyzer = vision_analyzer
        self.object_detector = object_detector
        self.face_detector = face_detector
        self.barcode_detector = barcode_detector
        self.qr_detector = qr_detector
        self.logger = logger
        self._initialized = False
        _emit_log(self.logger, "info", "Vision service constructed")

    @property
    def initialized(self) -> bool:
        """Return whether the Vision service has been initialized."""

        return self._initialized

    def initialize(self, context: Any | None = None) -> None:
        """Initialize Vision dependencies and mark the module as active."""

        if self._initialized:
            _emit_log(self.logger, "warning", "Vision service initialize requested while already initialized")
            return

        services = (
            ("camera", self.camera),
            ("screenshot_capture", self.screenshot_capture),
            ("image_loader", self.image_loader),
            ("image_preprocessor", self.image_preprocessor),
            ("image_analyzer", self.image_analyzer),
            ("ocr_service", self.ocr_service),
            ("ocr_analyzer", self.ocr_analyzer),
            ("detection_analyzer", self.detection_analyzer),
            ("vision_analyzer", self.vision_analyzer),
        )
        for name, service in services:
            initializer = getattr(service, "initialize", None)
            if not callable(initializer):
                continue
            try:
                initializer()
            except Exception as error:
                _emit_log(
                    self.logger,
                    "warning",
                    "Vision dependency failed to initialize",
                    service=name,
                    error=str(error),
                )

        self._initialized = True
        _emit_log(
            self.logger,
            "info",
            "Vision service initialized",
            context_type=type(context).__name__ if context is not None else "none",
        )

    def shutdown(self) -> None:
        """Shutdown Vision dependencies and release any held resources."""

        services = (
            ("vision_analyzer", self.vision_analyzer),
            ("detection_analyzer", self.detection_analyzer),
            ("ocr_analyzer", self.ocr_analyzer),
            ("ocr_service", self.ocr_service),
            ("image_analyzer", self.image_analyzer),
            ("image_preprocessor", self.image_preprocessor),
            ("image_loader", self.image_loader),
            ("screenshot_capture", self.screenshot_capture),
            ("camera", self.camera),
        )
        for name, service in services:
            shutdown_handler = getattr(service, "shutdown", None)
            if not callable(shutdown_handler):
                continue
            try:
                shutdown_handler()
            except Exception as error:
                _emit_log(
                    self.logger,
                    "warning",
                    "Vision dependency failed during shutdown",
                    service=name,
                    error=str(error),
                )

        self._initialized = False
        _emit_log(self.logger, "info", "Vision service shutdown")

    def health_report(self) -> HealthReport:
        """Return a structured health snapshot for the Vision module."""

        camera_available = bool(getattr(self.camera, "is_available", lambda: False)())
        screenshot_available = bool(getattr(self.screenshot_capture, "is_available", lambda: False)())
        ocr_available = bool(getattr(self.ocr_service, "is_available", lambda: False)())
        status = "ok"
        if not self._initialized:
            status = "stopped"
        elif not screenshot_available or not camera_available or not ocr_available:
            status = "degraded"

        return HealthReport(
            name="vision",
            status=status,
            details={
                "module": "Vision",
                "initialized": self._initialized,
                "camera_available": camera_available,
                "screenshot_available": screenshot_available,
                "ocr_available": ocr_available,
                "object_detector": type(self.object_detector).__name__,
                "face_detector": type(self.face_detector).__name__,
                "barcode_detector": type(self.barcode_detector).__name__,
                "qr_detector": type(self.qr_detector).__name__,
            },
        )

    def capture_camera_frame(self) -> ImageFrame:
        """Capture a single frame from the configured camera service."""

        frame = self.camera.capture()
        if frame.is_empty():
            _emit_log(self.logger, "warning", "Camera capture returned an empty frame")
        return frame

    def capture_camera_frames(self, count: int) -> list[ImageFrame]:
        """Capture multiple frames from the configured camera service."""

        frames = self.camera.capture_many(count)
        _emit_log(self.logger, "info", "Captured camera frames", count=len(frames))
        return frames

    def capture_screenshot(self, *, active_window: bool = False) -> ImageFrame:
        """Capture a screenshot through the configured screenshot service."""

        if active_window:
            frame = self.screenshot_capture.capture_active_window()
        else:
            frame = self.screenshot_capture.capture_full_screen()
        if frame.is_empty():
            _emit_log(
                self.logger,
                "warning",
                "Screenshot capture returned an empty frame",
                active_window=active_window,
            )
        return frame

    def analyze(self, image: ImageFrame) -> AnalysisResult:
        """Run the full Vision analysis pipeline for the supplied image."""

        processed = self.image_preprocessor.preprocess(image)
        result = self.vision_analyzer.analyze_frame(processed)
        _emit_log(self.logger, "info", "Vision analysis completed", source=result.source)
        return result

    def load_image(self, source: str | Path) -> ImageFrame:
        """Load an image through the registered image loader."""

        return self.image_loader.load(source)


def build_vision_services(
    *,
    camera: BaseCamera | None = None,
    screenshot_capture: BaseScreenshotCapture | None = None,
    image_loader: FileImageLoader | None = None,
    image_preprocessor: BaseImagePreprocessor | None = None,
    image_analyzer: BasicImageAnalyzer | None = None,
    ocr_service: BaseOCRService | None = None,
    ocr_analyzer: OCRAnalyzer | None = None,
    object_detector: BaseObjectDetector | None = None,
    face_detector: BaseFaceDetector | None = None,
    barcode_detector: BaseBarcodeDetector | None = None,
    qr_detector: BaseQRDetector | None = None,
    detection_analyzer: DetectionAnalyzer | None = None,
    vision_analyzer: CompositeVisionAnalyzer | None = None,
    screenshot_output_dir: str | Path = "screenshots",
    logger: Any | None = None,
) -> VisionServices:
    """Create the Vision service bundle using constructor injection."""

    from .analyzer import BasicImageAnalyzer, CompositeVisionAnalyzer
    from .camera import CameraService
    from .detector import (
        DetectionAnalyzer,
        NullBarcodeDetector,
        NullFaceDetector,
        NullObjectDetector,
        NullQRDetector,
    )
    from .image import FileImageLoader, PassthroughImagePreprocessor
    from .ocr import OCRAnalyzer, TesseractOCRService
    from .screenshot import ScreenshotService

    resolved_camera = camera or CameraService(logger=logger)
    resolved_screenshot = screenshot_capture or ScreenshotService(
        output_dir=screenshot_output_dir,
        logger=logger,
    )
    resolved_image_loader = image_loader or FileImageLoader(logger=logger)
    resolved_preprocessor = image_preprocessor or PassthroughImagePreprocessor(logger=logger)
    resolved_object_detector = object_detector or NullObjectDetector(logger=logger)
    resolved_face_detector = face_detector or NullFaceDetector(logger=logger)
    resolved_barcode_detector = barcode_detector or NullBarcodeDetector(logger=logger)
    resolved_qr_detector = qr_detector or NullQRDetector(logger=logger)
    resolved_detection_analyzer = detection_analyzer or DetectionAnalyzer(
        object_detector=resolved_object_detector,
        face_detector=resolved_face_detector,
        barcode_detector=resolved_barcode_detector,
        qr_detector=resolved_qr_detector,
        logger=logger,
    )
    resolved_ocr_service = ocr_service or TesseractOCRService(logger=logger)
    resolved_ocr_analyzer = ocr_analyzer or OCRAnalyzer(ocr_service=resolved_ocr_service, logger=logger)
    resolved_image_analyzer = image_analyzer or BasicImageAnalyzer(
        image_loader=resolved_image_loader,
        logger=logger,
    )
    resolved_vision_analyzer = vision_analyzer or CompositeVisionAnalyzer(
        camera=resolved_camera,
        screenshot_capture=resolved_screenshot,
        ocr_analyzer=resolved_ocr_analyzer,
        detection_analyzer=resolved_detection_analyzer,
        image_analyzer=resolved_image_analyzer,
        logger=logger,
    )
    resolved_vision_service = VisionService(
        camera=resolved_camera,
        screenshot_capture=resolved_screenshot,
        image_loader=resolved_image_loader,
        image_preprocessor=resolved_preprocessor,
        image_analyzer=resolved_image_analyzer,
        ocr_service=resolved_ocr_service,
        ocr_analyzer=resolved_ocr_analyzer,
        detection_analyzer=resolved_detection_analyzer,
        vision_analyzer=resolved_vision_analyzer,
        object_detector=resolved_object_detector,
        face_detector=resolved_face_detector,
        barcode_detector=resolved_barcode_detector,
        qr_detector=resolved_qr_detector,
        logger=logger,
    )
    _emit_log(
        logger,
        "info",
        "Built vision services",
        camera_type=type(resolved_camera).__name__,
        screenshot_type=type(resolved_screenshot).__name__,
        image_loader_type=type(resolved_image_loader).__name__,
    )
    return VisionServices(
        vision_service=resolved_vision_service,
        vision_analyzer=resolved_vision_analyzer,
        image_loader=resolved_image_loader,
        image_preprocessor=resolved_preprocessor,
        image_analyzer=resolved_image_analyzer,
        ocr_service=resolved_ocr_service,
        ocr_analyzer=resolved_ocr_analyzer,
        detection_analyzer=resolved_detection_analyzer,
        camera=resolved_camera,
        screenshot_capture=resolved_screenshot,
        object_detector=resolved_object_detector,
        face_detector=resolved_face_detector,
        barcode_detector=resolved_barcode_detector,
        qr_detector=resolved_qr_detector,
    )


def register_vision_services(
    container: DependencyRegistrar,
    *,
    services: VisionServices | None = None,
    screenshot_output_dir: str | Path = "screenshots",
    logger: Any | None = None,
) -> VisionServices:
    """Register Vision services in the shared dependency-injection container."""

    resolved_services = services or build_vision_services(
        screenshot_output_dir=screenshot_output_dir,
        logger=logger,
    )
    container.register_instance("vision_service", resolved_services.vision_service)
    container.register_instance("vision_analyzer", resolved_services.vision_analyzer)
    container.register_instance("camera", resolved_services.camera)
    container.register_instance("screenshot_capture", resolved_services.screenshot_capture)
    container.register_instance("image_loader", resolved_services.image_loader)
    container.register_instance("image_service", resolved_services.image_loader)
    container.register_instance("image_preprocessor", resolved_services.image_preprocessor)
    container.register_instance("image_analyzer", resolved_services.image_analyzer)
    container.register_instance("ocr_service", resolved_services.ocr_service)
    container.register_instance("ocr_analyzer", resolved_services.ocr_analyzer)
    container.register_instance("detector", resolved_services.detection_analyzer)
    container.register_instance("detection_analyzer", resolved_services.detection_analyzer)
    container.register_instance("object_detector", resolved_services.object_detector)
    container.register_instance("face_detector", resolved_services.face_detector)
    container.register_instance("barcode_detector", resolved_services.barcode_detector)
    container.register_instance("qr_detector", resolved_services.qr_detector)
    _emit_log(logger, "info", "Registered vision services in container")
    return resolved_services


class VisionRuntimeHook:
    """Runtime hook that registers Vision services during startup or plugin load."""

    def __init__(
        self,
        *,
        services: VisionServices | None = None,
        screenshot_output_dir: str | Path = "screenshots",
        logger: Any | None = None,
    ) -> None:
        self.services = services
        self.screenshot_output_dir = Path(screenshot_output_dir)
        self.logger = logger

    def load(
        self,
        container: DependencyRegistrar,
        event_bus: EventPublisher | None = None,
        logger: Any | None = None,
    ) -> None:
        """Register Vision services and publish a readiness event if possible."""

        resolved_logger = logger or self.logger
        self.services = register_vision_services(
            container,
            services=self.services,
            screenshot_output_dir=self.screenshot_output_dir,
            logger=resolved_logger,
        )
        if event_bus is not None:
            try:
                from Core.system import SystemEvent

                event_bus.publish(
                    SystemEvent(
                        name="vision.services.registered",
                        payload={"module": "Vision"},
                    )
                )
            except Exception:
                _emit_log(resolved_logger, "warning", "Unable to publish vision registration event")
        _emit_log(resolved_logger, "info", "Vision runtime hook completed")


__all__ = [
    "AnalysisResult",
    "DependencyRegistrar",
    "EventPublisher",
    "ImageFrame",
    "ImageLoader",
    "ImagePreprocessor",
    "VisionRuntimeHook",
    "VisionService",
    "VisionServices",
    "build_vision_services",
    "register_vision_services",
]
