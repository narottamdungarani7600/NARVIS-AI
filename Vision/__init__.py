"""Vision package for NARVIS.

This package provides reusable abstractions for camera capture, screenshots,
image loading, preprocessing, OCR, object detection, face detection, and image
analysis without introducing engine-specific logic.
"""

from .analyzer import CompositeVisionAnalyzer, VisionAnalyzer
from .camera import BaseCamera, Camera, NullCamera
from .detector import BaseFaceDetector, BaseObjectDetector, DetectionAnalyzer, FaceDetector, NullFaceDetector, NullObjectDetector, ObjectDetector
from .image import BaseImageLoader, BaseImagePreprocessor, FileImageLoader, ImageLoader, ImagePreprocessor, PassthroughImagePreprocessor
from .ocr import BaseOCRService, NullOCRService, OCRAnalyzer, OCRService
from .screenshot import BaseScreenshotCapture, NullScreenshotCapture, ScreenshotCapture
from .vision import AnalysisResult, ImageFrame

__all__ = [
    "AnalysisResult",
    "BaseCamera",
    "BaseFaceDetector",
    "BaseImageLoader",
    "BaseImagePreprocessor",
    "BaseOCRService",
    "BaseObjectDetector",
    "BaseScreenshotCapture",
    "Camera",
    "CompositeVisionAnalyzer",
    "DetectionAnalyzer",
    "FaceDetector",
    "FileImageLoader",
    "ImageFrame",
    "ImageLoader",
    "ImagePreprocessor",
    "NullCamera",
    "NullFaceDetector",
    "NullOCRService",
    "NullObjectDetector",
    "NullScreenshotCapture",
    "ObjectDetector",
    "OCRAnalyzer",
    "OCRService",
    "PassthroughImagePreprocessor",
    "ScreenshotCapture",
    "VisionAnalyzer",
]
