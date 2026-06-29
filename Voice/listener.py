"""Listener orchestration for the NARVIS Voice package.

The listener coordinates microphone capture, wake-word detection, and speech
recognition in a reusable orchestration layer that can be extended with future
engines such as Whisper, Vosk, Google Speech, or Azure Speech.
"""

from __future__ import annotations

from typing import Protocol

from .audio import AudioFrame, AudioSink
from .microphone import Microphone
from .speech import SpeechToTextEngine
from .wakeword import WakeWordDetector


class Listener(Protocol):
    """Protocol for listener orchestrators."""

    def listen(self) -> str:
        """Capture audio and return a transcription."""


class VoiceListener:
    """Orchestrates microphone input, wake-word detection, and transcription."""

    def __init__(
        self,
        microphone: Microphone,
        wake_word_detector: WakeWordDetector,
        speech_to_text_engine: SpeechToTextEngine,
    ) -> None:
        self.microphone = microphone
        self.wake_word_detector = wake_word_detector
        self.speech_to_text_engine = speech_to_text_engine

    def listen(self) -> str:
        """Capture a single audio stream and return a transcription."""
        class _Sink(AudioSink):
            def __init__(self, parent: "VoiceListener") -> None:
                self.parent = parent
                self.frames: list[AudioFrame] = []

            def write(self, frame: AudioFrame) -> None:
                self.frames.append(frame)
                event = self.parent.wake_word_detector.process(frame)
                if event is not None:
                    self.parent._last_wake_word = event

        sink = _Sink(self)
        self._last_wake_word = None
        self.microphone.start()
        try:
            self.microphone.stream(sink)
        finally:
            self.microphone.stop()

        if not sink.frames:
            return ""

        combined = b"".join(frame.data for frame in sink.frames)
        audio_frame = AudioFrame(data=combined)
        return self.speech_to_text_engine.transcribe(audio_frame)

    @property
    def last_wake_word(self) -> str | None:
        """Return the most recent detected wake word, if any."""
        return None if self._last_wake_word is None else self._last_wake_word.keyword
