"""Wake-word detection contracts and services for the Voice module."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from .audio import AudioFrame, _emit_log


@dataclass(slots=True)
class WakeWordEvent:
    """Represent a detected wake-word event."""

    keyword: str
    confidence: float
    source: str = "audio"


class WakeWordDetector(Protocol):
    """Protocol for wake-word detection engines."""

    keyword: str

    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Process an audio frame and return a wake-word event if detected."""


class BaseWakeWordDetector(ABC):
    """Abstract base class for wake-word detector implementations."""

    def __init__(self, keyword: str = "narvis", logger: Any | None = None) -> None:
        self.keyword = keyword.lower()
        self.logger = logger

    @abstractmethod
    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Process audio and return an event when the wake word is detected."""

    def is_available(self) -> bool:
        """Return whether the detector can operate on runtime audio."""

        return True


class NullWakeWordDetector(BaseWakeWordDetector):
    """A no-op wake-word detector for non-runtime or test environments."""

    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Always return ``None``."""

        return None

    def is_available(self) -> bool:
        """Return ``False`` because the detector is intentionally disabled."""

        return False


class KeywordWakeWordDetector(BaseWakeWordDetector):
    """Fallback wake-word detector based on simple audio energy heuristics."""

    def __init__(self, keyword: str = "narvis", threshold: float = 0.6, logger: Any | None = None) -> None:
        super().__init__(keyword=keyword, logger=logger)
        self.threshold = threshold

    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Treat energetic audio frames as potential wake-word candidates."""

        if frame.is_empty():
            return None

        try:
            import array

            audio_data = array.array("h", frame.data)
            if len(audio_data) == 0:
                return None
            energy = sum(sample * sample for sample in audio_data) / len(audio_data)
            confidence = min(0.99, energy / 100000.0)
            if confidence >= self.threshold:
                return WakeWordEvent(keyword=self.keyword, confidence=confidence, source="audio")
            return None
        except Exception as error:
            _emit_log(self.logger, "debug", "Wake-word audio heuristic failed", error=str(error))
            return None


class PorcupineWakeWordDetector(BaseWakeWordDetector):
    """Optional Porcupine-backed wake-word detector placeholder."""

    def __init__(self, keyword: str = "narvis", logger: Any | None = None) -> None:
        super().__init__(keyword=keyword, logger=logger)
        self._porcupine = None

    def is_available(self) -> bool:
        """Return whether a concrete Porcupine backend has been configured."""

        return self._porcupine is not None

    def process(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Return ``None`` until a real Porcupine integration is provided."""

        return None


class WakeWordService:
    """Provide wake-word checks across both audio and recognized text."""

    def __init__(
        self,
        detector: WakeWordDetector | None = None,
        *,
        keyword: str = "narvis",
        logger: Any | None = None,
    ) -> None:
        self.keyword = keyword.lower()
        self.detector = detector or NullWakeWordDetector(keyword=keyword, logger=logger)
        self.logger = logger
        self._text_pattern = re.compile(rf"^\s*{re.escape(self.keyword)}[\s,:-]*", re.IGNORECASE)

    def process_audio(self, frame: AudioFrame) -> WakeWordEvent | None:
        """Attempt wake-word detection on a raw audio frame."""

        try:
            return self.detector.process(frame)
        except Exception as error:
            _emit_log(self.logger, "warning", "Wake-word audio detection failed", error=str(error))
            return None

    def detect_text(self, text: str) -> WakeWordEvent | None:
        """Detect the configured wake word at the beginning of a transcript."""

        if not text.strip():
            return None
        if self._text_pattern.match(text):
            return WakeWordEvent(keyword=self.keyword, confidence=1.0, source="text")
        return None

    def strip_wake_word(self, text: str) -> str:
        """Remove the configured wake word prefix from a recognized transcript."""

        return self._text_pattern.sub("", text, count=1).strip()

    def is_available(self) -> bool:
        """Return whether a wake-word detector is configured."""

        detector_available = getattr(self.detector, "is_available", lambda: True)()
        return bool(detector_available or self.keyword)
