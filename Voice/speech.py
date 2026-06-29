"""Speech recognition and synthesis abstractions for the NARVIS Voice package.

The module provides reusable interfaces for speech-to-text and text-to-speech
services so future engines such as Whisper, Vosk, Azure Speech, and
pyttsx3 can be integrated through dependency injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .audio import AudioFrame


class SpeechToTextEngine(Protocol):
    """Protocol for speech-to-text engines."""

    def transcribe(self, audio: AudioFrame) -> str:
        """Convert an audio frame into text."""


class TextToSpeechEngine(Protocol):
    """Protocol for text-to-speech engines."""

    def synthesize(self, text: str) -> AudioFrame:
        """Convert a text message into an audio frame."""


class BaseSpeechToTextEngine(ABC):
    """Abstract base class for speech-to-text implementations."""

    @abstractmethod
    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio into text."""


class BaseTextToSpeechEngine(ABC):
    """Abstract base class for text-to-speech implementations."""

    @abstractmethod
    def synthesize(self, text: str) -> AudioFrame:
        """Synthesize spoken audio from text."""


class PassthroughSpeechToText(BaseSpeechToTextEngine):
    """A placeholder speech-to-text engine that returns empty text."""

    def transcribe(self, audio: AudioFrame) -> str:
        """Return an empty transcription by default."""
        return ""


class PassthroughTextToSpeech(BaseTextToSpeechEngine):
    """A placeholder text-to-speech engine that returns empty audio."""

    def synthesize(self, text: str) -> AudioFrame:
        """Return an empty audio frame."""
        return AudioFrame(data=b"")
