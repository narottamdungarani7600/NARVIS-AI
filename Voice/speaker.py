"""Text-to-speech orchestration services for the Voice module."""

from __future__ import annotations

from typing import Any, Protocol

from .audio import AudioFrame, _emit_log
from .speech import TextToSpeechEngine


class Speaker(Protocol):
    """Protocol for speaker orchestrators."""

    def speak(self, text: str) -> AudioFrame:
        """Convert text to audio and return the result."""


class SpeakerService:
    """High-level service that wraps a text-to-speech engine."""

    def __init__(self, text_to_speech_engine: TextToSpeechEngine, logger: Any | None = None) -> None:
        self.text_to_speech_engine = text_to_speech_engine
        self.logger = logger

    def is_available(self) -> bool:
        """Return whether the configured TTS backend is available."""

        return bool(self.text_to_speech_engine.is_available())

    def speak(self, text: str) -> AudioFrame:
        """Synthesize speech from the supplied text."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            return AudioFrame(data=b"", metadata={"reason": "empty_text"})

        frame = self.text_to_speech_engine.synthesize(text)
        if frame.is_empty():
            _emit_log(self.logger, "warning", "Text-to-speech returned empty audio", engine=self.text_to_speech_engine.name)
        else:
            _emit_log(self.logger, "info", "Text-to-speech synthesized audio", engine=self.text_to_speech_engine.name)
        return frame

    def dependency_warnings(self) -> list[str]:
        """Return warnings describing unavailable TTS backends."""

        if self.is_available():
            return []
        return ["pyttsx3 backend unavailable for text-to-speech output."]


class VoiceSpeaker(SpeakerService):
    """Backward-compatible alias for the primary speaker service."""
