"""Concrete speech engines with optional dependency fallbacks."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Any

from .audio import AudioFrame, AudioFormat, _emit_log
from .speech import BaseSpeechToTextEngine, BaseTextToSpeechEngine


def _load_speech_recognition_module() -> Any | None:
    """Return the optional ``speech_recognition`` module if it is installed."""

    try:
        import speech_recognition as sr
    except ImportError:
        return None
    return sr


def _load_pyttsx3_module() -> Any | None:
    """Return the optional ``pyttsx3`` module if it is installed."""

    try:
        import pyttsx3
    except ImportError:
        return None
    return pyttsx3


class RealSpeechToTextEngine(BaseSpeechToTextEngine, ABC):
    """Base class for optional speech-to-text backends."""

    def __init__(self, name: str, language: str = "en-US", logger: Any | None = None) -> None:
        super().__init__(name=name, logger=logger)
        self.language = language

    async def transcribe_async(self, audio: AudioFrame) -> str:
        """Transcribe audio asynchronously."""

        return await asyncio.to_thread(self.transcribe, audio)


class OfflineSpeechRecognitionEngine(RealSpeechToTextEngine):
    """Offline recognizer using SpeechRecognition with PocketSphinx when available."""

    def __init__(self, language: str = "en-US", logger: Any | None = None) -> None:
        super().__init__(name="offline-sphinx", language=language, logger=logger)
        self._sr = _load_speech_recognition_module()
        self._recognizer = self._sr.Recognizer() if self._sr is not None else None
        self._sphinx_available = importlib.util.find_spec("pocketsphinx") is not None
        if self._sr is None:
            _emit_log(self.logger, "warning", "SpeechRecognition not installed; offline STT disabled")
        elif not self._sphinx_available:
            _emit_log(self.logger, "warning", "PocketSphinx not installed; offline STT disabled")

    def is_available(self) -> bool:
        """Return whether offline recognition is ready."""

        return self._recognizer is not None and self._sphinx_available

    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio with PocketSphinx if it is available."""

        if not self.is_available() or audio.is_empty():
            return ""

        try:
            audio_data = self._sr.AudioData(audio.data, audio.format.sample_rate, audio.format.sample_width)
            return str(self._recognizer.recognize_sphinx(audio_data, language=self.language)).strip()
        except Exception as error:
            _emit_log(self.logger, "warning", "Offline transcription failed", error=str(error))
            return ""


class GoogleSpeechRecognitionEngine(RealSpeechToTextEngine):
    """Online recognizer using the Google backend from SpeechRecognition."""

    def __init__(self, language: str = "en-US", logger: Any | None = None) -> None:
        super().__init__(name="google-speech", language=language, logger=logger)
        self._sr = _load_speech_recognition_module()
        self._recognizer = self._sr.Recognizer() if self._sr is not None else None
        if self._sr is None:
            _emit_log(self.logger, "warning", "SpeechRecognition not installed; online STT disabled")

    def is_available(self) -> bool:
        """Return whether the SpeechRecognition dependency is available."""

        return self._recognizer is not None

    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio using the Google Speech Recognition provider."""

        if not self.is_available() or audio.is_empty():
            return ""

        try:
            audio_data = self._sr.AudioData(audio.data, audio.format.sample_rate, audio.format.sample_width)
            return str(self._recognizer.recognize_google(audio_data, language=self.language)).strip()
        except Exception as error:
            _emit_log(self.logger, "warning", "Online transcription failed", error=str(error))
            return ""


class RealTextToSpeechEngine(BaseTextToSpeechEngine, ABC):
    """Base class for optional text-to-speech backends."""

    def __init__(self, name: str, language: str = "en-US", logger: Any | None = None) -> None:
        super().__init__(name=name, logger=logger)
        self.language = language

    async def synthesize_async(self, text: str) -> AudioFrame:
        """Synthesize speech asynchronously."""

        return await asyncio.to_thread(self.synthesize, text)


class Pyttsx3TextToSpeechEngine(RealTextToSpeechEngine):
    """Offline text-to-speech using the optional ``pyttsx3`` library."""

    def __init__(
        self,
        language: str = "en-US",
        logger: Any | None = None,
        rate: int = 150,
    ) -> None:
        super().__init__(name="pyttsx3", language=language, logger=logger)
        self._pyttsx3 = _load_pyttsx3_module()
        self._engine = None
        self.rate = rate

        if self._pyttsx3 is None:
            _emit_log(self.logger, "warning", "pyttsx3 not installed; TTS disabled")
            return

        try:
            self._engine = self._pyttsx3.init()
            self._engine.setProperty("rate", rate)
        except Exception as error:
            self._engine = None
            _emit_log(self.logger, "warning", "pyttsx3 initialization failed", error=str(error))

    def is_available(self) -> bool:
        """Return whether the pyttsx3 engine initialized successfully."""

        return self._engine is not None

    def synthesize(self, text: str) -> AudioFrame:
        """Synthesize audio bytes using pyttsx3 without auto-playing them."""

        if not self.is_available() or not text.strip():
            return AudioFrame(data=b"", format=AudioFormat(), metadata={"reason": "tts_unavailable"})

        file_descriptor, output_path = tempfile.mkstemp(prefix="narvis_tts_", suffix=".wav")
        os.close(file_descriptor)
        try:
            self._engine.save_to_file(text, output_path)
            self._engine.runAndWait()
            if not os.path.exists(output_path):
                return AudioFrame(data=b"", format=AudioFormat(), metadata={"reason": "tts_output_missing"})
            with open(output_path, "rb") as handle:
                payload = handle.read()
            return AudioFrame(
                data=payload,
                format=AudioFormat(),
                metadata={"engine": self.name, "text": text},
            )
        except Exception as error:
            _emit_log(self.logger, "warning", "Text-to-speech synthesis failed", error=str(error))
            return AudioFrame(data=b"", format=AudioFormat(), metadata={"reason": "tts_error"})
        finally:
            try:
                os.remove(output_path)
            except OSError:
                pass
