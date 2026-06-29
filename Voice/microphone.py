"""Microphone input abstractions for the NARVIS Voice package.

This module defines reusable interfaces and a default implementation for audio
capture from a microphone source. It is intentionally generic and can be
extended for different hardware or streaming backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .audio import AudioFrame, AudioSink


class Microphone(Protocol):
    """Protocol for microphone input sources."""

    def start(self) -> None:
        """Begin capturing audio."""

    def stop(self) -> None:
        """Stop capturing audio."""

    def stream(self, sink: AudioSink) -> None:
        """Stream captured audio to a sink."""


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
    def stream(self, sink: AudioSink) -> None:
        """Stream captured audio to a sink."""


class NullMicrophone(BaseMicrophone):
    """A no-op microphone implementation for testing and offline use."""

    def start(self) -> None:
        """Do nothing."""

    def stop(self) -> None:
        """Do nothing."""

    def stream(self, sink: AudioSink) -> None:
        """Emit no frames."""
        return None


class AudioCaptureSession:
    """Convenience wrapper that captures microphone audio into a sink."""

    def __init__(self, microphone: Microphone) -> None:
        self._microphone = microphone

    def run(self, sink: AudioSink) -> None:
        """Start the capture process and stream audio into the given sink."""
        self._microphone.start()
        try:
            self._microphone.stream(sink)
        finally:
            self._microphone.stop()
