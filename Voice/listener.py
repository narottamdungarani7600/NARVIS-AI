"""Listener orchestration for microphone capture, wake-word checks, and STT."""

from __future__ import annotations

from typing import Any, Protocol

from .audio import _emit_log
from .microphone import AudioInputService
from .speech import SpeechRecognitionService
from .wakeword import WakeWordEvent, WakeWordService


class Listener(Protocol):
    """Protocol for listener orchestrators."""

    def listen(self, *, require_wake_word: bool = True, max_frames: int | None = None) -> str:
        """Capture audio and return a transcription."""


class VoiceListener:
    """Capture audio, recognize speech, and enforce wake-word rules."""

    def __init__(
        self,
        *,
        audio_input_service: AudioInputService,
        wake_word_service: WakeWordService,
        speech_recognition_service: SpeechRecognitionService,
        logger: Any | None = None,
        strip_wake_word: bool = True,
    ) -> None:
        self.audio_input_service = audio_input_service
        self.wake_word_service = wake_word_service
        self.speech_recognition_service = speech_recognition_service
        self.logger = logger
        self.strip_wake_word = strip_wake_word
        self._last_wake_word: WakeWordEvent | None = None

    def listen(self, *, require_wake_word: bool = True, max_frames: int | None = None) -> str:
        """Capture a single bounded audio block and return a transcript."""

        audio = self.audio_input_service.capture_audio(max_frames=max_frames)
        if audio.is_empty():
            _emit_log(self.logger, "warning", "Voice listener captured no audio")
            self._last_wake_word = None
            return ""

        audio_event = self.wake_word_service.process_audio(audio)
        transcript = self.speech_recognition_service.transcribe(audio)
        text_event = self.wake_word_service.detect_text(transcript)
        self._last_wake_word = text_event or audio_event

        if require_wake_word and self._last_wake_word is None:
            _emit_log(self.logger, "info", "Transcript ignored because wake word was not detected")
            return ""

        if self.strip_wake_word and text_event is not None:
            return self.wake_word_service.strip_wake_word(transcript)
        return transcript

    @property
    def last_wake_word(self) -> str | None:
        """Return the most recent detected wake word, if any."""

        return None if self._last_wake_word is None else self._last_wake_word.keyword
