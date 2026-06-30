"""Speech recognition and synthesis abstractions for the Voice module."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .audio import AudioFrame, _emit_log


class SpeechToTextEngine(Protocol):
    """Protocol for speech-to-text engines."""

    name: str

    def transcribe(self, audio: AudioFrame) -> str:
        """Convert an audio frame into text."""

    def is_available(self) -> bool:
        """Return whether the engine is ready to process requests."""


class TextToSpeechEngine(Protocol):
    """Protocol for text-to-speech engines."""

    name: str

    def synthesize(self, text: str) -> AudioFrame:
        """Convert text into an audio frame."""

    def is_available(self) -> bool:
        """Return whether the engine is ready to synthesize audio."""


class BaseSpeechToTextEngine(ABC):
    """Abstract base class for speech-to-text implementations."""

    def __init__(self, name: str, logger: Any | None = None) -> None:
        self.name = name
        self.logger = logger

    def is_available(self) -> bool:
        """Return whether the engine is currently available."""

        return True

    @abstractmethod
    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio into text."""


class BaseTextToSpeechEngine(ABC):
    """Abstract base class for text-to-speech implementations."""

    def __init__(self, name: str, logger: Any | None = None) -> None:
        self.name = name
        self.logger = logger

    def is_available(self) -> bool:
        """Return whether the engine is currently available."""

        return True

    @abstractmethod
    def synthesize(self, text: str) -> AudioFrame:
        """Synthesize spoken audio from text."""


class NullSpeechToTextEngine(BaseSpeechToTextEngine):
    """Placeholder speech recognizer used when real engines are unavailable."""

    def __init__(self, logger: Any | None = None) -> None:
        super().__init__(name="null-stt", logger=logger)

    def is_available(self) -> bool:
        """Return ``False`` because the engine does not perform recognition."""

        return False

    def transcribe(self, audio: AudioFrame) -> str:
        """Return an empty transcription."""

        return ""


class NullTextToSpeechEngine(BaseTextToSpeechEngine):
    """Placeholder synthesizer used when real engines are unavailable."""

    def __init__(self, logger: Any | None = None) -> None:
        super().__init__(name="null-tts", logger=logger)

    def is_available(self) -> bool:
        """Return ``False`` because the engine does not synthesize audio."""

        return False

    def synthesize(self, text: str) -> AudioFrame:
        """Return an empty audio frame."""

        return AudioFrame(data=b"", metadata={"reason": "tts_unavailable"})


class PassthroughSpeechToText(NullSpeechToTextEngine):
    """Backward-compatible alias for the null speech recognizer."""


class PassthroughTextToSpeech(NullTextToSpeechEngine):
    """Backward-compatible alias for the null text-to-speech engine."""


class SpeechRecognitionService:
    """Transcribe audio using offline-first recognition with online fallback."""

    def __init__(
        self,
        *,
        offline_engine: SpeechToTextEngine | None = None,
        online_engine: SpeechToTextEngine | None = None,
        prefer_offline: bool = True,
        logger: Any | None = None,
    ) -> None:
        self.offline_engine = offline_engine or NullSpeechToTextEngine(logger=logger)
        self.online_engine = online_engine or NullSpeechToTextEngine(logger=logger)
        self.prefer_offline = prefer_offline
        self.logger = logger

    def is_available(self) -> bool:
        """Return whether any configured recognition backend is available."""

        return self.offline_engine.is_available() or self.online_engine.is_available()

    def primary_engine(self) -> SpeechToTextEngine:
        """Return the preferred speech engine for compatibility registration."""

        if self.prefer_offline:
            return self.offline_engine if self.offline_engine.is_available() else self.online_engine
        return self.online_engine if self.online_engine.is_available() else self.offline_engine

    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio using the configured provider order."""

        if audio.is_empty():
            return ""

        providers = (
            (self.offline_engine, True),
            (self.online_engine, False),
        )
        if not self.prefer_offline:
            providers = tuple(reversed(providers))

        for engine, is_offline in providers:
            if not engine.is_available():
                continue
            try:
                text = engine.transcribe(audio).strip()
            except Exception as error:
                _emit_log(
                    self.logger,
                    "warning",
                    "Speech recognition provider failed",
                    provider=engine.name,
                    offline=is_offline,
                    error=str(error),
                )
                continue
            if text:
                _emit_log(
                    self.logger,
                    "info",
                    "Speech recognized",
                    provider=engine.name,
                    offline=is_offline,
                )
                return text

        _emit_log(self.logger, "warning", "Speech recognition produced no transcript")
        return ""

    def health_details(self) -> dict[str, Any]:
        """Return provider availability details for runtime health checks."""

        return {
            "offline_engine": self.offline_engine.name,
            "offline_available": self.offline_engine.is_available(),
            "online_engine": self.online_engine.name,
            "online_available": self.online_engine.is_available(),
            "prefer_offline": self.prefer_offline,
            "any_available": self.is_available(),
        }

    def dependency_warnings(self) -> list[str]:
        """Return warnings describing unavailable recognition backends."""

        warnings: list[str] = []
        if not self.offline_engine.is_available():
            warnings.append("Offline speech recognition backend unavailable.")
        if not self.online_engine.is_available():
            warnings.append("Online speech recognition fallback unavailable.")
        return warnings
