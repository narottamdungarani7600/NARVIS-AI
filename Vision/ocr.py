"""Optical character recognition abstractions for the NARVIS Vision package.

This module defines reusable interfaces for OCR-capable services while keeping
engine implementations out of scope. It is designed for future support of
Tesseract OCR, EasyOCR, PaddleOCR, and similar tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .vision import AnalysisResult, ImageFrame


class OCRService(Protocol):
    """Protocol for OCR services."""

    def extract_text(self, image: ImageFrame) -> str:
        """Extract text from an image frame."""


class BaseOCRService(ABC):
    """Abstract base class for OCR implementations."""

    @abstractmethod
    def extract_text(self, image: ImageFrame) -> str:
        """Extract text from an image frame."""


class NullOCRService(BaseOCRService):
    """Placeholder OCR service that returns an empty string."""

    def extract_text(self, image: ImageFrame) -> str:
        """Return an empty transcription."""
        return ""


class OCRAnalyzer:
    """Reusable orchestrator for OCR workflows."""

    def __init__(self, ocr_service: OCRService) -> None:
        self.ocr_service = ocr_service

    def analyze(self, image: ImageFrame) -> AnalysisResult:
        """Run OCR and return a structured analysis result."""
        text = self.ocr_service.extract_text(image)
        return AnalysisResult(source="ocr", summary=text, metadata={"text_length": len(text)})
