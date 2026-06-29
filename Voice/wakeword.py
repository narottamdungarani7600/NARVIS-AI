"""Wake-word detection abstractions for the NARVIS Voice package.

This module defines reusable interfaces and a default no-op implementation for
wake-word detection so future engines can be integrated through dependency
injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from .audio import AudioFrame


@dataclass(slots=True)
class WakeWordEvent:
    """Represents a detected wake-word event."""

    keyword: str
    confidence: float


class WakeWordDetector(Protocol):
    """Protocol for wake-word detection engines."""

    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Process an audio frame and return a wake-word event if detected."""


class BaseWakeWordDetector(ABC):
    """Abstract base class for wake-word detector implementations."""

    def __init__(self, keyword: str = "narvis") -> None:
        self.keyword = keyword

    @abstractmethod
    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Process audio and return an event when the wake word is detected."""


class NullWakeWordDetector(BaseWakeWordDetector):
    """A no-op wake-word detector for non-runtime or test environments."""

    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Always return None."""
        return None
