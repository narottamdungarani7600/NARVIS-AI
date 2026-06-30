"""Detection contracts and analyzers for the NARVIS Vision package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, TypedDict

from .vision import AnalysisResult, ImageFrame, _emit_log


class DetectionRecord(TypedDict, total=False):
    """Typed detection payload shared by Vision detector implementations."""

    type: str
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]
    value: str
    metadata: dict[str, Any]


class ObjectDetector(Protocol):
    """Protocol for object detection services."""

    def detect_objects(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return a list of detected object descriptors."""


class FaceDetector(Protocol):
    """Protocol for face detection services."""

    def detect_faces(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return a list of detected face descriptors."""


class BarcodeDetector(Protocol):
    """Protocol for barcode detection services."""

    def detect_barcodes(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return a list of detected barcode descriptors."""


class QRDetector(Protocol):
    """Protocol for QR code detection services."""

    def detect_qr_codes(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return a list of detected QR code descriptors."""


class BaseObjectDetector(ABC):
    """Abstract base class for object detection implementations."""

    def initialize(self) -> None:
        """Initialize the detector backend."""

    def shutdown(self) -> None:
        """Shutdown the detector backend."""

    def is_available(self) -> bool:
        """Return whether the detector backend is available."""

        return True

    @abstractmethod
    def detect_objects(self, image: ImageFrame) -> list[DetectionRecord]:
        """Detect objects in an image frame."""


class BaseFaceDetector(ABC):
    """Abstract base class for face detection implementations."""

    def initialize(self) -> None:
        """Initialize the detector backend."""

    def shutdown(self) -> None:
        """Shutdown the detector backend."""

    def is_available(self) -> bool:
        """Return whether the detector backend is available."""

        return True

    @abstractmethod
    def detect_faces(self, image: ImageFrame) -> list[DetectionRecord]:
        """Detect faces in an image frame."""


class BaseBarcodeDetector(ABC):
    """Abstract base class for barcode detection implementations."""

    def initialize(self) -> None:
        """Initialize the detector backend."""

    def shutdown(self) -> None:
        """Shutdown the detector backend."""

    def is_available(self) -> bool:
        """Return whether the detector backend is available."""

        return True

    @abstractmethod
    def detect_barcodes(self, image: ImageFrame) -> list[DetectionRecord]:
        """Detect barcodes in an image frame."""


class BaseQRDetector(ABC):
    """Abstract base class for QR code detection implementations."""

    def initialize(self) -> None:
        """Initialize the detector backend."""

    def shutdown(self) -> None:
        """Shutdown the detector backend."""

    def is_available(self) -> bool:
        """Return whether the detector backend is available."""

        return True

    @abstractmethod
    def detect_qr_codes(self, image: ImageFrame) -> list[DetectionRecord]:
        """Detect QR codes in an image frame."""


class NullObjectDetector(BaseObjectDetector):
    """Placeholder object detector that returns no detections."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null object detector constructed")

    def initialize(self) -> None:
        """Initialize the placeholder detector."""

        _emit_log(self._logger, "info", "Null object detector initialized")

    def shutdown(self) -> None:
        """Shutdown the placeholder detector."""

        _emit_log(self._logger, "info", "Null object detector shutdown")

    def is_available(self) -> bool:
        """Return that no model-backed detector is available."""

        return False

    def detect_objects(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return an empty detection list."""

        return []


class NullFaceDetector(BaseFaceDetector):
    """Placeholder face detector that returns no detections."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null face detector constructed")

    def initialize(self) -> None:
        """Initialize the placeholder detector."""

        _emit_log(self._logger, "info", "Null face detector initialized")

    def shutdown(self) -> None:
        """Shutdown the placeholder detector."""

        _emit_log(self._logger, "info", "Null face detector shutdown")

    def is_available(self) -> bool:
        """Return that no model-backed detector is available."""

        return False

    def detect_faces(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return an empty detection list."""

        return []


class NullBarcodeDetector(BaseBarcodeDetector):
    """Placeholder barcode detector that returns no detections."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null barcode detector constructed")

    def initialize(self) -> None:
        """Initialize the placeholder detector."""

        _emit_log(self._logger, "info", "Null barcode detector initialized")

    def shutdown(self) -> None:
        """Shutdown the placeholder detector."""

        _emit_log(self._logger, "info", "Null barcode detector shutdown")

    def is_available(self) -> bool:
        """Return that no model-backed detector is available."""

        return False

    def detect_barcodes(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return an empty detection list."""

        return []


class NullQRDetector(BaseQRDetector):
    """Placeholder QR detector that returns no detections."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null QR detector constructed")

    def initialize(self) -> None:
        """Initialize the placeholder detector."""

        _emit_log(self._logger, "info", "Null QR detector initialized")

    def shutdown(self) -> None:
        """Shutdown the placeholder detector."""

        _emit_log(self._logger, "info", "Null QR detector shutdown")

    def is_available(self) -> bool:
        """Return that no model-backed detector is available."""

        return False

    def detect_qr_codes(self, image: ImageFrame) -> list[DetectionRecord]:
        """Return an empty detection list."""

        return []


class DetectionAnalyzer:
    """Reusable orchestrator for Vision detection workflows."""

    def __init__(
        self,
        object_detector: ObjectDetector,
        face_detector: FaceDetector,
        barcode_detector: BarcodeDetector | None = None,
        qr_detector: QRDetector | None = None,
        logger: Any | None = None,
    ) -> None:
        self.object_detector = object_detector
        self.face_detector = face_detector
        self.barcode_detector = barcode_detector or NullBarcodeDetector(logger=logger)
        self.qr_detector = qr_detector or NullQRDetector(logger=logger)
        self._logger = logger
        _emit_log(self._logger, "info", "Detection analyzer constructed")

    def initialize(self) -> None:
        """Initialize the detection analyzer and child detectors."""

        for name, detector in (
            ("object_detector", self.object_detector),
            ("face_detector", self.face_detector),
            ("barcode_detector", self.barcode_detector),
            ("qr_detector", self.qr_detector),
        ):
            initializer = getattr(detector, "initialize", None)
            if callable(initializer):
                try:
                    initializer()
                except Exception as error:
                    _emit_log(
                        self._logger,
                        "warning",
                        "Detector initialization failed",
                        detector=name,
                        error=str(error),
                    )
        _emit_log(self._logger, "info", "Detection analyzer initialized")

    def shutdown(self) -> None:
        """Shutdown the detection analyzer and child detectors."""

        for name, detector in (
            ("qr_detector", self.qr_detector),
            ("barcode_detector", self.barcode_detector),
            ("face_detector", self.face_detector),
            ("object_detector", self.object_detector),
        ):
            shutdown_handler = getattr(detector, "shutdown", None)
            if callable(shutdown_handler):
                try:
                    shutdown_handler()
                except Exception as error:
                    _emit_log(
                        self._logger,
                        "warning",
                        "Detector shutdown failed",
                        detector=name,
                        error=str(error),
                    )
        _emit_log(self._logger, "info", "Detection analyzer shutdown")

    def analyze(self, image: ImageFrame) -> AnalysisResult:
        """Run all configured detection workflows for the supplied image."""

        objects = self.object_detector.detect_objects(image)
        faces = self.face_detector.detect_faces(image)
        barcodes = self.barcode_detector.detect_barcodes(image)
        qr_codes = self.qr_detector.detect_qr_codes(image)
        counts = {
            "objects": len(objects),
            "faces": len(faces),
            "barcodes": len(barcodes),
            "qr_codes": len(qr_codes),
        }
        _emit_log(self._logger, "info", "Detection analysis completed", **counts)
        summary = ", ".join(f"{key}={value}" for key, value in counts.items())
        return AnalysisResult(
            source="detection",
            summary=summary,
            metadata={
                "counts": counts,
                "objects": objects,
                "faces": faces,
                "barcodes": barcodes,
                "qr_codes": qr_codes,
            },
        )


__all__ = [
    "BarcodeDetector",
    "BaseBarcodeDetector",
    "BaseFaceDetector",
    "BaseObjectDetector",
    "BaseQRDetector",
    "DetectionAnalyzer",
    "DetectionRecord",
    "FaceDetector",
    "NullBarcodeDetector",
    "NullFaceDetector",
    "NullObjectDetector",
    "NullQRDetector",
    "ObjectDetector",
    "QRDetector",
]
