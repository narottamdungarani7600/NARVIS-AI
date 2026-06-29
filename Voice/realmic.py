"""Real microphone input implementations for NARVIS Voice."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .audio import AudioFrame, AudioFormat, AudioSink

if TYPE_CHECKING:
    import pyaudio


class RealMicrophone:
    """Real microphone implementation using PyAudio."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        channels: int = 1,
        sample_width: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.sample_width = sample_width
        self.logger = logger or logging.getLogger("narvis.voice.microphone")
        self._stream = None
        self._audio = None
        self._is_recording = False

    def start(self) -> None:
        """Begin capturing audio from the microphone."""
        try:
            import pyaudio
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                format=pyaudio.paInt16 if self.sample_width == 2 else pyaudio.paInt8,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
            )
            self._is_recording = True
            self.logger.debug("Microphone started")
        except ImportError:
            self.logger.warning("PyAudio not installed; microphone disabled")
            self._is_recording = False
        except Exception as e:
            self.logger.error(f"Failed to start microphone: {e}")
            self._is_recording = False

    def stop(self) -> None:
        """Stop capturing audio from the microphone."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                self.logger.warning(f"Error closing stream: {e}")
        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception as e:
                self.logger.warning(f"Error terminating audio: {e}")
        self._is_recording = False
        self.logger.debug("Microphone stopped")

    def stream(self, sink: AudioSink) -> None:
        """Stream captured audio to a sink."""
        if not self._is_recording or self._stream is None:
            return

        try:
            while self._is_recording:
                data = self._stream.read(self.chunk_size, exception_on_overflow=False)
                frame = AudioFrame(
                    data=data,
                    format=AudioFormat(
                        sample_rate=self.sample_rate,
                        channels=self.channels,
                        sample_width=self.sample_width,
                    ),
                )
                sink.write(frame)
        except Exception as e:
            self.logger.error(f"Error streaming audio: {e}")


class VoiceActivityDetector:
    """Detects voice activity in audio frames using energy-based thresholding."""

    def __init__(self, threshold: float = 500.0, logger: logging.Logger | None = None) -> None:
        self.threshold = threshold
        self.logger = logger or logging.getLogger("narvis.voice.vad")

    def is_active(self, frame: AudioFrame) -> bool:
        """Determine if the frame contains voice activity."""
        if not frame.data:
            return False
        try:
            import array
            audio_data = array.array("h", frame.data)
            energy = sum(x * x for x in audio_data) / len(audio_data)
            return energy > self.threshold
        except Exception as e:
            self.logger.debug(f"VAD check failed: {e}")
            return len(frame.data) > 0

    async def is_active_async(self, frame: AudioFrame) -> bool:
        """Asynchronously determine if the frame contains voice activity."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.is_active, frame)
