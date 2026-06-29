"""Real speech-to-text and text-to-speech implementations for NARVIS Voice."""

from __future__ import annotations

import asyncio
import io
import logging
import os
from abc import ABC, abstractmethod

from .audio import AudioFrame, AudioFormat


class RealSpeechToTextEngine(ABC):
    """Base class for real speech-to-text implementations."""

    def __init__(self, language: str = "en-US", logger: logging.Logger | None = None) -> None:
        self.language = language
        self.logger = logger or logging.getLogger("narvis.voice.stt")

    @abstractmethod
    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio into text."""

    async def transcribe_async(self, audio: AudioFrame) -> str:
        """Transcribe audio asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.transcribe, audio)


class GoogleSpeechRecognitionEngine(RealSpeechToTextEngine):
    """Speech-to-text using the Google Speech Recognition API."""

    def __init__(self, language: str = "en-US", logger: logging.Logger | None = None) -> None:
        super().__init__(language=language, logger=logger)
        try:
            import speech_recognition as sr
            self.recognizer = sr.Recognizer()
        except ImportError:
            self.recognizer = None
            self.logger.warning("speech_recognition library not installed; STT disabled")

    def transcribe(self, audio: AudioFrame) -> str:
        """Transcribe audio using Google Speech Recognition."""
        if self.recognizer is None:
            return ""
        if not audio.data:
            return ""
        try:
            import speech_recognition as sr
            audio_data = sr.AudioData(audio.data, audio.format.sample_rate, audio.format.sample_width)
            text = self.recognizer.recognize_google(audio_data, language=self.language)
            self.logger.debug(f"Transcribed: {text}")
            return text
        except Exception as e:
            self.logger.warning(f"Transcription failed: {e}")
            return ""


class RealTextToSpeechEngine(ABC):
    """Base class for real text-to-speech implementations."""

    def __init__(self, language: str = "en-US", logger: logging.Logger | None = None) -> None:
        self.language = language
        self.logger = logger or logging.getLogger("narvis.voice.tts")

    @abstractmethod
    def synthesize(self, text: str) -> AudioFrame:
        """Synthesize speech from text."""

    async def synthesize_async(self, text: str) -> AudioFrame:
        """Synthesize speech asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.synthesize, text)


class Pyttsx3TextToSpeechEngine(RealTextToSpeechEngine):
    """Text-to-speech using the pyttsx3 library."""

    def __init__(self, language: str = "en-US", logger: logging.Logger | None = None, rate: int = 150) -> None:
        super().__init__(language=language, logger=logger)
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", rate)
        except ImportError:
            self.engine = None
            self.logger.warning("pyttsx3 library not installed; TTS disabled")
        except Exception as e:
            self.engine = None
            self.logger.warning(f"pyttsx3 initialization failed; TTS disabled: {e}")

    def synthesize(self, text: str) -> AudioFrame:
        """Synthesize speech from text using pyttsx3."""
        if self.engine is None:
            return AudioFrame(data=b"", format=AudioFormat())
        if not text:
            return AudioFrame(data=b"", format=AudioFormat())

        try:
            output_file = "/tmp/narvis_tts_output.wav"
            if os.name == "nt":
                output_file = "narvis_tts_output.wav"
            
            self.engine.save_to_file(text, output_file)
            self.engine.runAndWait()
            
            if os.path.exists(output_file):
                with open(output_file, "rb") as f:
                    audio_data = f.read()
                try:
                    os.remove(output_file)
                except Exception:
                    pass
                self.logger.debug(f"Synthesized {len(audio_data)} bytes for text: {text[:50]}")
                return AudioFrame(data=audio_data, format=AudioFormat())
            return AudioFrame(data=b"", format=AudioFormat())
        except Exception as e:
            self.logger.warning(f"Synthesis failed: {e}")
            return AudioFrame(data=b"", format=AudioFormat())
