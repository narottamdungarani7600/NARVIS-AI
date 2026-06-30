"""Tests for the Vision module runtime registration and fallbacks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest import mock

from Core.system import DependencyContainer, EventBus
from Vision import (
    BasicImageAnalyzer,
    CameraService,
    FileImageLoader,
    NullCamera,
    NullOCRService,
    NullScreenshotCapture,
    ScreenshotService,
    TesseractOCRService,
    VisionRuntimeHook,
    build_vision_services,
    register_vision_services,
)
from Vision.vision import ImageFrame


_TEST_TMP_ROOT = Path("data") / "vision_test_tmp"
_TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _test_path(name: str) -> Path:
    """Return a unique filesystem path inside the writable test scratch area."""

    return _TEST_TMP_ROOT / f"{uuid4().hex}_{name}"


def _ppm_bytes(width: int, height: int, pixels: list[tuple[int, int, int]] | None = None) -> bytes:
    """Create a small binary PPM payload for deterministic image tests."""

    expected = width * height
    resolved_pixels = pixels or [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 255),
        (0, 0, 0),
        (255, 255, 0),
    ][:expected]
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    payload = bytearray()
    for red, green, blue in resolved_pixels:
        payload.extend((red, green, blue))
    return header + bytes(payload)


def _ppm_frame(width: int = 2, height: int = 2) -> ImageFrame:
    """Return a deterministic ``ImageFrame`` backed by PPM data."""

    return ImageFrame(
        data=_ppm_bytes(width, height),
        width=width,
        height=height,
        format="ppm",
        metadata={"source": "test"},
    )


class VisionRuntimeRegistrationTests(unittest.TestCase):
    """Verify Vision runtime registration and lifecycle behavior."""

    def test_register_vision_services_exposes_runtime_dependencies(self) -> None:
        container = DependencyContainer()
        services = build_vision_services(
            camera=NullCamera(),
            screenshot_capture=NullScreenshotCapture(),
            ocr_service=NullOCRService(),
        )

        register_vision_services(container, services=services)

        self.assertIs(container.resolve("vision_service"), services.vision_service)
        self.assertIs(container.resolve("vision_analyzer"), services.vision_analyzer)
        self.assertIs(container.resolve("image_loader"), services.image_loader)
        self.assertIs(container.resolve("image_service"), services.image_loader)
        self.assertIs(container.resolve("ocr_analyzer"), services.ocr_analyzer)
        self.assertIs(container.resolve("detector"), services.detection_analyzer)

    def test_runtime_hook_publishes_registration_event(self) -> None:
        container = DependencyContainer()
        event_bus = EventBus()
        published: list[str] = []
        event_bus.subscribe("vision.services.registered", lambda event: published.append(event.name))
        services = build_vision_services(
            camera=NullCamera(),
            screenshot_capture=NullScreenshotCapture(),
            ocr_service=NullOCRService(),
        )

        hook = VisionRuntimeHook(services=services)
        hook.load(container, event_bus=event_bus)

        self.assertIn("vision.services.registered", published)
        self.assertIs(container.resolve("vision_service"), services.vision_service)

    def test_vision_service_reports_degraded_health_with_null_backends(self) -> None:
        services = build_vision_services(
            camera=NullCamera(),
            screenshot_capture=NullScreenshotCapture(),
            ocr_service=NullOCRService(),
        )
        service = services.vision_service

        self.assertEqual(service.health_report().status, "stopped")

        service.initialize()
        health = service.health_report()

        self.assertEqual(health.status, "degraded")
        self.assertTrue(health.details["initialized"])

        service.shutdown()
        self.assertEqual(service.health_report().status, "stopped")


class ScreenshotServiceTests(unittest.TestCase):
    """Verify screenshot capture behavior and file persistence."""

    def test_screenshot_service_captures_and_saves_images(self) -> None:
        frame = _ppm_frame()
        saved_path = _test_path("screenshot.ppm")
        service = ScreenshotService(
            output_dir=_TEST_TMP_ROOT,
            full_screen_provider=lambda: frame,
            active_window_provider=lambda: frame,
        )

        try:
            captured = service.capture_full_screen()
            saved = service.save_screenshot(captured, saved_path)

            self.assertEqual(captured.width, 2)
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), frame.data)
        finally:
            saved_path.unlink(missing_ok=True)

    def test_active_window_capture_falls_back_to_full_screen(self) -> None:
        frame = _ppm_frame()
        service = ScreenshotService(full_screen_provider=lambda: frame)

        captured = service.capture_active_window()

        self.assertEqual(captured.metadata["capture_mode"], "active_window_fallback")
        self.assertEqual(captured.width, frame.width)


class ImageUtilitiesTests(unittest.TestCase):
    """Verify image utility operations and metadata analysis."""

    def test_image_loader_utilities_and_analyzer(self) -> None:
        loader = FileImageLoader()
        analyzer = BasicImageAnalyzer(loader)
        source_path = _test_path("sample.ppm")
        saved_path = _test_path("cropped.ppm")
        try:
            source_path.write_bytes(_ppm_bytes(2, 3))

            image = loader.load(source_path)
            resized = loader.resize(image, 4, 6)
            rotated = loader.rotate(image, 90)
            cropped = loader.crop(image, 0, 0, 1, 2)
            saved = loader.save(cropped, saved_path)
            analysis = analyzer.analyze(image)

            self.assertEqual(image.width, 2)
            self.assertEqual(image.height, 3)
            self.assertEqual(resized.width, 4)
            self.assertEqual(resized.height, 6)
            self.assertEqual(rotated.width, 3)
            self.assertEqual(rotated.height, 2)
            self.assertEqual(cropped.width, 1)
            self.assertEqual(cropped.height, 2)
            self.assertTrue(saved.exists())
            self.assertEqual(analysis.metadata["resolution"]["width"], 2)
            self.assertIn("color", analysis.metadata)
        finally:
            source_path.unlink(missing_ok=True)
            saved_path.unlink(missing_ok=True)

    def test_convert_format_handles_optional_dependencies(self) -> None:
        loader = FileImageLoader()
        image = _ppm_frame()

        with mock.patch("Vision.image.PILImage", None):
            with self.assertRaises(RuntimeError):
                loader.convert_format(image, "png")


class GracefulFallbackTests(unittest.TestCase):
    """Verify safe degradation when optional Vision backends are unavailable."""

    def test_camera_service_returns_empty_frame_when_backend_is_missing(self) -> None:
        camera = CameraService(backend_factory=lambda device_index: None)

        frame = camera.capture()

        self.assertTrue(frame.is_empty())
        self.assertEqual(frame.metadata["reason"], "camera_unavailable")

    def test_tesseract_ocr_service_returns_empty_text_without_dependencies(self) -> None:
        image = _ppm_frame()
        with mock.patch("Vision.ocr.pytesseract", None), mock.patch("Vision.ocr.PILImage", None):
            service = TesseractOCRService()

            self.assertFalse(service.is_available())
            self.assertEqual(service.extract_text(image), "")


if __name__ == "__main__":
    unittest.main()
