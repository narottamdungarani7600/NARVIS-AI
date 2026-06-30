"""Screenshot capture abstractions and implementations for the Vision package."""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .vision import ImageFrame, _emit_log

try:
    from PIL import ImageGrab  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    ImageGrab = None


class ScreenshotCapture(Protocol):
    """Protocol for screenshot capture services."""

    def capture(self) -> ImageFrame:
        """Capture and return the current screen contents as an image frame."""


class BaseScreenshotCapture(ABC):
    """Abstract base class for screenshot capture implementations."""

    def initialize(self) -> None:
        """Initialize the screenshot backend."""

    def shutdown(self) -> None:
        """Shutdown the screenshot backend."""

    def is_available(self) -> bool:
        """Return whether the screenshot backend is available."""

        return True

    def capture_full_screen(self) -> ImageFrame:
        """Capture the full desktop."""

        return self.capture()

    def capture_active_window(self) -> ImageFrame:
        """Capture the active window, falling back to the full desktop."""

        return self.capture_full_screen()

    def save_screenshot(self, image: ImageFrame, destination: str | Path) -> Path:
        """Save a screenshot image to disk."""

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.data)
        return path

    @abstractmethod
    def capture(self) -> ImageFrame:
        """Capture and return a screenshot frame."""


class ScreenshotService(BaseScreenshotCapture):
    """Screenshot service with injectable capture providers and safe fallbacks."""

    def __init__(
        self,
        *,
        output_dir: str | Path = "screenshots",
        full_screen_provider: Callable[[], ImageFrame] | None = None,
        active_window_provider: Callable[[], ImageFrame] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._full_screen_provider = full_screen_provider or self._capture_with_pillow
        self._active_window_provider = active_window_provider
        self._logger = logger
        self._initialized = False
        _emit_log(self._logger, "info", "Screenshot service constructed", output_dir=str(self.output_dir))

    def initialize(self) -> None:
        """Initialize the screenshot service."""

        self._initialized = True
        _emit_log(self._logger, "info", "Screenshot service initialized")

    def shutdown(self) -> None:
        """Shutdown the screenshot service."""

        self._initialized = False
        _emit_log(self._logger, "info", "Screenshot service shutdown")

    def is_available(self) -> bool:
        """Return whether a screenshot backend is available."""

        return self._full_screen_provider is not None and (
            self._full_screen_provider is not self._capture_with_pillow or ImageGrab is not None
        )

    def capture(self) -> ImageFrame:
        """Capture the full screen and return it as an ``ImageFrame``."""

        return self.capture_full_screen()

    def capture_full_screen(self) -> ImageFrame:
        """Capture the entire desktop."""

        try:
            frame = self._full_screen_provider()
            _emit_log(self._logger, "info", "Full-screen screenshot captured")
            return frame
        except Exception as error:
            _emit_log(self._logger, "warning", "Full-screen screenshot capture failed", error=str(error))
            return self._empty_frame(reason="screenshot_failed", error=str(error))

    def capture_active_window(self) -> ImageFrame:
        """Capture the active window or fall back to the full screen."""

        provider = self._active_window_provider
        if provider is None:
            _emit_log(self._logger, "warning", "Active-window capture unavailable; falling back to full screen")
            frame = self.capture_full_screen()
            metadata = dict(frame.metadata)
            metadata["capture_mode"] = "active_window_fallback"
            return ImageFrame(
                data=frame.data,
                width=frame.width,
                height=frame.height,
                format=frame.format,
                mode=frame.mode,
                metadata=metadata,
            )

        try:
            frame = provider()
            _emit_log(self._logger, "info", "Active-window screenshot captured")
            return frame
        except Exception as error:
            _emit_log(self._logger, "warning", "Active-window screenshot capture failed", error=str(error))
            return self.capture_full_screen()

    def save_screenshot(self, image: ImageFrame, destination: str | Path | None = None) -> Path:
        """Save a screenshot to the configured output directory."""

        path = Path(destination) if destination is not None else self._default_path(image.format)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.data)
        _emit_log(self._logger, "info", "Screenshot saved", destination=str(path))
        return path

    def _capture_with_pillow(self) -> ImageFrame:
        """Capture the screen through Pillow ``ImageGrab`` when available."""

        if ImageGrab is None:
            raise RuntimeError("Pillow ImageGrab is unavailable")

        image = ImageGrab.grab()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ImageFrame(
            data=buffer.getvalue(),
            width=image.width,
            height=image.height,
            format="png",
            mode=getattr(image, "mode", "RGB"),
            metadata={"source": "screenshot", "capture_mode": "full_screen"},
        )

    def _default_path(self, image_format: str) -> Path:
        """Build a timestamped screenshot output path."""

        extension = image_format.lower().lstrip(".") or "png"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"screenshot_{timestamp}.{extension}"

    @staticmethod
    def _empty_frame(*, reason: str, **metadata: Any) -> ImageFrame:
        """Return an empty screenshot frame with diagnostic metadata."""

        return ImageFrame(
            data=b"",
            format="raw",
            metadata={"source": "screenshot", "reason": reason, **metadata},
        )


class NullScreenshotCapture(BaseScreenshotCapture):
    """Placeholder screenshot implementation that returns an empty frame."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null screenshot capture constructed")

    def initialize(self) -> None:
        """Initialize the placeholder screenshot service."""

        _emit_log(self._logger, "warning", "Null screenshot initialize requested")

    def shutdown(self) -> None:
        """Shutdown the placeholder screenshot service."""

        _emit_log(self._logger, "info", "Null screenshot capture shutdown")

    def is_available(self) -> bool:
        """Return that no screenshot backend is available."""

        return False

    def capture(self) -> ImageFrame:
        """Return an empty image frame."""

        return ImageFrame(
            data=b"",
            format="raw",
            metadata={"source": "screenshot", "reason": "backend_unavailable"},
        )


__all__ = [
    "BaseScreenshotCapture",
    "NullScreenshotCapture",
    "ScreenshotCapture",
    "ScreenshotService",
]
