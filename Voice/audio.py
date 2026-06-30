"""Core audio models and helpers for the NARVIS Voice package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a structured log message through either supported logger contract."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


@dataclass(slots=True)
class AudioFormat:
    """Describe the format of a PCM audio payload."""

    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    encoding: str = "pcm_s16le"

    @property
    def bytes_per_second(self) -> int:
        """Return the theoretical transfer rate for the format."""

        return self.sample_rate * self.channels * self.sample_width


@dataclass(slots=True)
class AudioDeviceInfo:
    """Describe an audio input device discovered at runtime."""

    index: int | None
    name: str
    max_input_channels: int = 0
    default_sample_rate: int | None = None
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioFrame:
    """Represent a chunk of audio data plus transport metadata."""

    data: bytes = b""
    format: AudioFormat = field(default_factory=AudioFormat)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        """Return the payload size in bytes."""

        return len(self.data)

    @property
    def duration_seconds(self) -> float:
        """Return the approximate playback duration of the frame."""

        if self.format.bytes_per_second <= 0:
            return 0.0
        return self.size_bytes / self.format.bytes_per_second

    def is_empty(self) -> bool:
        """Return whether the frame contains any audio payload."""

        return self.size_bytes == 0


class AudioSink(Protocol):
    """Protocol for components that consume audio frames."""

    def write(self, frame: AudioFrame) -> None:
        """Consume an audio frame."""


def combine_audio_frames(frames: Sequence[AudioFrame]) -> AudioFrame:
    """Merge multiple frames into a single frame for downstream processing."""

    if not frames:
        return AudioFrame(metadata={"frame_count": 0})

    combined_data = b"".join(frame.data for frame in frames)
    metadata: dict[str, Any] = {"frame_count": len(frames)}
    for frame in frames:
        metadata.update(frame.metadata)
    return AudioFrame(
        data=combined_data,
        format=frames[0].format,
        metadata=metadata,
    )
