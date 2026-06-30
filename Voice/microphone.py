"""Microphone abstractions and runtime services for the NARVIS Voice package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from .audio import AudioDeviceInfo, AudioFrame, AudioSink, combine_audio_frames, _emit_log


class Microphone(Protocol):
    """Protocol for microphone input sources."""

    def start(self) -> None:
        """Begin capturing audio."""

    def stop(self) -> None:
        """Stop capturing audio."""

    def stream(self, sink: AudioSink, *, max_frames: int | None = None) -> None:
        """Stream captured audio to a sink."""

    def is_available(self) -> bool:
        """Return whether the microphone backend is available."""

    def list_devices(self) -> tuple[AudioDeviceInfo, ...]:
        """Return the detected input devices."""


class BaseMicrophone(ABC):
    """Abstract base class for microphone implementations."""

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate

    @abstractmethod
    def start(self) -> None:
        """Begin capturing audio."""

    @abstractmethod
    def stop(self) -> None:
        """Stop capturing audio."""

    @abstractmethod
    def stream(self, sink: AudioSink, *, max_frames: int | None = None) -> None:
        """Stream captured audio to a sink."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether the microphone backend is available."""

    @abstractmethod
    def list_devices(self) -> tuple[AudioDeviceInfo, ...]:
        """Return the detected input devices."""


class NullMicrophone(BaseMicrophone):
    """A no-op microphone implementation for testing and offline use."""

    def __init__(self, sample_rate: int = 16000) -> None:
        super().__init__(sample_rate=sample_rate)

    def start(self) -> None:
        """Do nothing."""

    def stop(self) -> None:
        """Do nothing."""

    def stream(self, sink: AudioSink, *, max_frames: int | None = None) -> None:
        """Emit no frames."""

    def is_available(self) -> bool:
        """Return ``False`` because the null backend captures no audio."""

        return False

    def list_devices(self) -> tuple[AudioDeviceInfo, ...]:
        """Return an empty device list."""

        return ()


class AudioCaptureSession:
    """Convenience wrapper that captures microphone audio into a sink."""

    def __init__(self, microphone: Microphone) -> None:
        self._microphone = microphone

    def run(self, sink: AudioSink, *, max_frames: int | None = None) -> None:
        """Start the capture process and stream audio into the given sink."""

        self._microphone.start()
        try:
            self._microphone.stream(sink, max_frames=max_frames)
        finally:
            self._microphone.stop()


@dataclass(slots=True)
class AudioInputService:
    """Capture a bounded block of microphone audio for transcription."""

    microphone_service: "MicrophoneService"
    default_max_frames: int = 16

    def capture_audio(self, *, max_frames: int | None = None) -> AudioFrame:
        """Capture audio frames and return them as a single combined frame."""

        frames = self.microphone_service.capture_frames(max_frames=max_frames or self.default_max_frames)
        return combine_audio_frames(frames)


class MicrophoneService:
    """High-level runtime service around a concrete microphone backend."""

    def __init__(self, microphone: Microphone, logger: Any | None = None) -> None:
        self.microphone = microphone
        self.logger = logger
        self._cached_devices: tuple[AudioDeviceInfo, ...] | None = None

    def is_available(self) -> bool:
        """Return whether the underlying microphone backend is available."""

        try:
            return bool(self.microphone.is_available())
        except Exception as error:
            _emit_log(self.logger, "warning", "Microphone availability check failed", error=str(error))
            return False

    def detect_devices(self, *, refresh: bool = False) -> tuple[AudioDeviceInfo, ...]:
        """Return the known input devices, optionally refreshing the cache."""

        if self._cached_devices is not None and not refresh:
            return self._cached_devices

        try:
            self._cached_devices = self.microphone.list_devices()
        except Exception as error:
            _emit_log(self.logger, "warning", "Microphone device detection failed", error=str(error))
            self._cached_devices = ()
        return self._cached_devices

    def active_device(self) -> AudioDeviceInfo | None:
        """Return the first available input device, if one exists."""

        for device in self.detect_devices():
            if device.available:
                return device
        return None

    def start(self) -> None:
        """Open the microphone backend for capture."""

        self.microphone.start()

    def stop(self) -> None:
        """Close the microphone backend if it is open."""

        self.microphone.stop()

    def capture_frames(self, *, max_frames: int = 16) -> list[AudioFrame]:
        """Capture a bounded list of frames from the active microphone."""

        if max_frames <= 0:
            return []

        if not self.is_available():
            _emit_log(self.logger, "warning", "Microphone capture requested while backend is unavailable")
            return []

        class _Collector:
            def __init__(self) -> None:
                self.frames: list[AudioFrame] = []

            def write(self, frame: AudioFrame) -> None:
                self.frames.append(frame)

        collector = _Collector()
        session = AudioCaptureSession(self.microphone)
        try:
            session.run(collector, max_frames=max_frames)
        except Exception as error:
            _emit_log(self.logger, "warning", "Microphone capture failed", error=str(error))
            return []
        return collector.frames

    def dependency_warnings(self) -> list[str]:
        """Return warnings describing degraded microphone availability."""

        warnings: list[str] = []
        if not self.is_available():
            warnings.append("PyAudio backend unavailable or no microphone device detected.")
        if not self.detect_devices():
            warnings.append("No microphone input devices were detected.")
        return warnings
