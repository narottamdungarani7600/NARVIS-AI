"""OCR contracts and implementations for the NARVIS Vision package."""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from typing import Any, Protocol

from .vision import AnalysisResult, ImageFrame, _emit_log

try:
    import pytesseract  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None

try:
    from PIL import Image as PILImage  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    PILImage = None


class OCRService(Protocol):
    """Protocol for OCR services."""

    def extract_text(self, image: ImageFrame) -> str:
        """Extract text from an image frame."""


class BaseOCRService(ABC):
    """Abstract base class for OCR implementations."""

    def initialize(self) -> None:
        """Initialize the OCR backend."""

    def shutdown(self) -> None:
        """Shutdown the OCR backend."""

    def is_available(self) -> bool:
        """Return whether the OCR backend is available."""

        return True

    @abstractmethod
    def extract_text(self, image: ImageFrame) -> str:
        """Extract text from an image frame."""


class NullOCRService(BaseOCRService):
    """Placeholder OCR service that returns an empty string."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null OCR service constructed")

    def initialize(self) -> None:
        """Initialize the placeholder OCR service."""

        _emit_log(self._logger, "warning", "Null OCR initialize requested")

    def shutdown(self) -> None:
        """Shutdown the placeholder OCR service."""

        _emit_log(self._logger, "info", "Null OCR service shutdown")

    def is_available(self) -> bool:
        """Return that no OCR backend is available."""

        return False

    def extract_text(self, image: ImageFrame) -> str:
        """Return an empty transcription."""

        return ""


class TesseractOCRService(BaseOCRService):
    """Optional Tesseract-backed OCR service with safe dependency fallbacks."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Tesseract OCR service constructed")

    def initialize(self) -> None:
        """Initialize the Tesseract OCR service."""

        if not self.is_available():
            _emit_log(self._logger, "warning", "Tesseract OCR dependencies are unavailable")
            return
        _emit_log(self._logger, "info", "Tesseract OCR service initialized")

    def shutdown(self) -> None:
        """Shutdown the Tesseract OCR service."""

        _emit_log(self._logger, "info", "Tesseract OCR service shutdown")

    def is_available(self) -> bool:
        """Return whether Tesseract OCR dependencies are importable."""

        return pytesseract is not None and PILImage is not None

    def extract_text(self, image: ImageFrame) -> str:
        """Extract text from an image frame when dependencies are available."""

        if not self.is_available():
            _emit_log(self._logger, "warning", "OCR extraction requested without available dependencies")
            return ""

        if image.is_empty():
            _emit_log(self._logger, "warning", "OCR extraction requested for an empty image")
            return ""

        try:
            with PILImage.open(io.BytesIO(image.data)) as pil_image:
                text = pytesseract.image_to_string(pil_image)
        except Exception as error:
            _emit_log(self._logger, "warning", "OCR extraction failed", error=str(error))
            return ""

        normalized = text.strip()
        _emit_log(self._logger, "info", "OCR extraction completed", text_length=len(normalized))
        return normalized


class OCRAnalyzer:
    """Reusable orchestrator for OCR workflows."""

    def __init__(self, ocr_service: OCRService, logger: Any | None = None) -> None:
        self.ocr_service = ocr_service
        self._logger = logger
        _emit_log(self._logger, "info", "OCR analyzer constructed")

    def initialize(self) -> None:
        """Initialize the analyzer and the underlying OCR service."""

        initializer = getattr(self.ocr_service, "initialize", None)
        if callable(initializer):
            try:
                initializer()
            except Exception as error:
                _emit_log(self._logger, "warning", "OCR service initialization failed", error=str(error))
        _emit_log(self._logger, "info", "OCR analyzer initialized")

    def shutdown(self) -> None:
        """Shutdown the analyzer and the underlying OCR service."""

        shutdown_handler = getattr(self.ocr_service, "shutdown", None)
        if callable(shutdown_handler):
            try:
                shutdown_handler()
            except Exception as error:
                _emit_log(self._logger, "warning", "OCR service shutdown failed", error=str(error))
        _emit_log(self._logger, "info", "OCR analyzer shutdown")

    def analyze(self, image: ImageFrame) -> AnalysisResult:
        """Run OCR and return a structured analysis result."""

        text = self.ocr_service.extract_text(image)
        summary = text if text else "no text detected"
        _emit_log(self._logger, "info", "OCR analysis completed", text_length=len(text))
        return AnalysisResult(
            source="ocr",
            summary=summary,
            metadata={"text": text, "text_length": len(text)},
        )


__all__ = [
    "BaseOCRService",
    "NullOCRService",
    "OCRAnalyzer",
    "OCRService",
    "TesseractOCRService",
]
