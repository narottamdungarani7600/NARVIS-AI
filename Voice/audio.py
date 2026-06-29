"""Audio primitives and transport abstractions for the NARVIS Voice package.

This module contains reusable audio data structures and sink interfaces that
provide a stable foundation for future microphone, speech, and speaker
components without embedding device-specific behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class AudioFormat:
    """Describes the format of audio data."""

    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2


@dataclass(slots=True)
class AudioFrame:
    """Represents a chunk of audio data.

    Attributes:
        data: Raw audio bytes for the current frame.
        format: Audio format metadata describing the frame.
    """

    data: bytes
    format: AudioFormat = field(default_factory=AudioFormat)


class AudioSink(Protocol):
    """Protocol for components that can consume audio frames."""

    def write(self, frame: AudioFrame) -> None:
        """Consume an audio frame."""
