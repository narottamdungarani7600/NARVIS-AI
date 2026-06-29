"""Speaker orchestration for the NARVIS Voice package.

The speaker module provides reusable abstractions for text-to-speech output and
can be extended with engines such as ElevenLabs or pyttsx3 through dependency
injection.
"""

from __future__ import annotations

from typing import Protocol

from .audio import AudioFrame
from .speech import TextToSpeechEngine


class Speaker(Protocol):
    """Protocol for speaker orchestrators."""

    def speak(self, text: str) -> AudioFrame:
        """Convert text to audio and return the result."""


class VoiceSpeaker:
    """Orchestrates text-to-speech synthesis for the Voice package."""

    def __init__(self, text_to_speech_engine: TextToSpeechEngine) -> None:
        self.text_to_speech_engine = text_to_speech_engine

    def speak(self, text: str) -> AudioFrame:
        """Synthesize speech from the supplied text."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return self.text_to_speech_engine.synthesize(text)
