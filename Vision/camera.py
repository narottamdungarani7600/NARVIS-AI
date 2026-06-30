"""Camera capture abstractions and implementations for the Vision package."""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol

from .vision import ImageFrame, _emit_log

try:
    import cv2  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    cv2 = None


class Camera(Protocol):
    """Protocol for camera capture services."""

    def capture(self) -> ImageFrame:
        """Capture and return a single image frame."""

    def capture_many(self, count: int) -> list[ImageFrame]:
        """Capture and return multiple image frames."""


class BaseCamera(ABC):
    """Abstract base class for camera implementations."""

    def initialize(self) -> None:
        """Initialize the camera backend."""

    def shutdown(self) -> None:
        """Release camera resources."""

    def is_available(self) -> bool:
        """Return whether the camera backend is currently available."""

        return False

    def capture_many(self, count: int) -> list[ImageFrame]:
        """Capture multiple frames from the camera."""

        frame_count = max(0, count)
        frames: list[ImageFrame] = []
        for _ in range(frame_count):
            frame = self.capture()
            if frame.is_empty():
                break
            frames.append(frame)
        return frames

    @abstractmethod
    def capture(self) -> ImageFrame:
        """Capture and return an image frame."""


class CameraService(BaseCamera):
    """Optional webcam-backed camera service with safe runtime fallbacks."""

    def __init__(
        self,
        *,
        device_index: int = 0,
        backend_factory: Callable[[int], Any] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.device_index = device_index
        self._backend_factory = backend_factory or self._default_backend_factory
        self._backend: Any | None = None
        self._initialized = False
        self._logger = logger
        _emit_log(self._logger, "info", "Camera service constructed", device_index=device_index)

    def initialize(self) -> None:
        """Initialize the webcam backend if one is available."""

        if self._initialized:
            _emit_log(self._logger, "warning", "Camera initialize requested while already initialized")
            return

        try:
            backend = self._backend_factory(self.device_index)
        except Exception as error:
            self._backend = None
            _emit_log(
                self._logger,
                "warning",
                "Camera backend initialization failed",
                device_index=self.device_index,
                error=str(error),
            )
            return

        if not self._backend_is_ready(backend):
            self._backend = None
            _emit_log(
                self._logger,
                "warning",
                "Camera backend unavailable",
                device_index=self.device_index,
            )
            return

        self._backend = backend
        self._initialized = True
        _emit_log(self._logger, "info", "Camera service initialized", device_index=self.device_index)

    def shutdown(self) -> None:
        """Release the webcam backend safely."""

        if self._backend is not None:
            release = getattr(self._backend, "release", None)
            if callable(release):
                try:
                    release()
                except Exception as error:
                    _emit_log(self._logger, "warning", "Camera release failed", error=str(error))
        self._backend = None
        self._initialized = False
        _emit_log(self._logger, "info", "Camera service shutdown")

    def is_available(self) -> bool:
        """Return whether a live camera backend is ready for capture."""

        return self._backend_is_ready(self._backend)

    def capture(self) -> ImageFrame:
        """Capture a single image frame, falling back gracefully when needed."""

        if self._backend is None:
            self.initialize()

        if self._backend is None:
            _emit_log(self._logger, "warning", "Camera capture requested without an available backend")
            return self._empty_frame(reason="camera_unavailable")

        try:
            if hasattr(self._backend, "read_frame"):
                frame = self._backend.read_frame()
                if isinstance(frame, ImageFrame):
                    return frame
                _emit_log(self._logger, "warning", "Custom camera backend returned an invalid frame type")
                return self._empty_frame(reason="invalid_frame_type")

            result = self._backend.read()
            if not isinstance(result, tuple) or len(result) != 2:
                _emit_log(self._logger, "warning", "Camera backend returned an unexpected read payload")
                return self._empty_frame(reason="invalid_read_payload")

            success, raw_frame = result
            if not success or raw_frame is None:
                _emit_log(self._logger, "warning", "Camera backend failed to capture a frame")
                return self._empty_frame(reason="capture_failed")

            encoded_frame = self._encode_cv_frame(raw_frame)
            _emit_log(self._logger, "info", "Camera frame captured")
            return encoded_frame
        except Exception as error:
            _emit_log(self._logger, "warning", "Camera capture failed", error=str(error))
            return self._empty_frame(reason="capture_exception", error=str(error))

    @staticmethod
    def _default_backend_factory(device_index: int) -> Any:
        """Return the default OpenCV backend when available."""

        if cv2 is None:
            return None
        return cv2.VideoCapture(device_index)

    @staticmethod
    def _backend_is_ready(backend: Any | None) -> bool:
        """Return whether the supplied backend appears ready for use."""

        if backend is None:
            return False
        is_opened = getattr(backend, "isOpened", None)
        if callable(is_opened):
            return bool(is_opened())
        return True

    def _encode_cv_frame(self, raw_frame: Any) -> ImageFrame:
        """Encode an OpenCV frame into the shared ``ImageFrame`` payload."""

        if cv2 is None:
            return self._empty_frame(reason="opencv_unavailable")

        success, encoded = cv2.imencode(".png", raw_frame)
        if not success:
            return self._empty_frame(reason="frame_encode_failed")

        height = int(getattr(raw_frame, "shape", (0, 0))[0]) or None
        width = int(getattr(raw_frame, "shape", (0, 0))[1]) or None
        return ImageFrame(
            data=bytes(encoded),
            width=width,
            height=height,
            format="png",
            mode="BGR",
            metadata={"source": "camera", "device_index": self.device_index},
        )

    def _empty_frame(self, *, reason: str, **metadata: Any) -> ImageFrame:
        """Return an empty camera frame with diagnostic metadata."""

        return ImageFrame(
            data=b"",
            format="raw",
            metadata={"source": "camera", "reason": reason, **metadata},
        )


class NullCamera(BaseCamera):
    """Placeholder camera implementation that always fails gracefully."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger
        _emit_log(self._logger, "info", "Null camera constructed")

    def initialize(self) -> None:
        """Initialize the null camera."""

        _emit_log(self._logger, "warning", "Null camera initialize requested")

    def shutdown(self) -> None:
        """Shutdown the null camera."""

        _emit_log(self._logger, "info", "Null camera shutdown")

    def is_available(self) -> bool:
        """Return that no real camera backend is available."""

        return False

    def capture(self) -> ImageFrame:
        """Return an empty image frame."""

        _emit_log(self._logger, "warning", "Null camera capture requested")
        return ImageFrame(
            data=b"",
            format="raw",
            metadata={"source": "camera", "reason": "camera_unavailable"},
        )


__all__ = [
    "BaseCamera",
    "Camera",
    "CameraService",
    "NullCamera",
]
