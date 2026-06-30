"""Concrete microphone implementations and device helpers for Voice."""

from __future__ import annotations

import asyncio
from typing import Any

from .audio import AudioDeviceInfo, AudioFrame, AudioFormat, AudioSink, _emit_log
from .microphone import BaseMicrophone


def _load_pyaudio_module() -> Any | None:
    """Return the optional ``pyaudio`` module if it is installed."""

    try:
        import pyaudio
    except ImportError:
        return None
    return pyaudio


class RealMicrophone(BaseMicrophone):
    """PyAudio-backed microphone implementation with graceful degradation."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        channels: int = 1,
        sample_width: int = 2,
        device_index: int | None = None,
        logger: Any | None = None,
    ) -> None:
        super().__init__(sample_rate=sample_rate)
        self.chunk_size = chunk_size
        self.channels = channels
        self.sample_width = sample_width
        self.device_index = device_index
        self.logger = logger
        self._stream: Any | None = None
        self._audio: Any | None = None
        self._is_recording = False

    def is_available(self) -> bool:
        """Return whether PyAudio and at least one input device are available."""

        return bool(self.list_devices())

    def list_devices(self) -> tuple[AudioDeviceInfo, ...]:
        """Return the currently detected input devices."""

        pyaudio = _load_pyaudio_module()
        if pyaudio is None:
            return ()

        audio = None
        devices: list[AudioDeviceInfo] = []
        try:
            audio = pyaudio.PyAudio()
            for index in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(index)
                if int(info.get("maxInputChannels", 0)) <= 0:
                    continue
                devices.append(
                    AudioDeviceInfo(
                        index=index,
                        name=str(info.get("name", f"device-{index}")),
                        max_input_channels=int(info.get("maxInputChannels", 0)),
                        default_sample_rate=int(float(info.get("defaultSampleRate", self.sample_rate))),
                        metadata={"host_api": info.get("hostApi")},
                    )
                )
        except Exception as error:
            _emit_log(self.logger, "warning", "Unable to enumerate microphone devices", error=str(error))
            return ()
        finally:
            if audio is not None:
                try:
                    audio.terminate()
                except Exception:
                    pass
        return tuple(devices)

    def start(self) -> None:
        """Open the input stream when the backend and device are available."""

        pyaudio = _load_pyaudio_module()
        if pyaudio is None:
            _emit_log(self.logger, "warning", "PyAudio not installed; microphone backend disabled")
            self._is_recording = False
            return

        available_devices = self.list_devices()
        if not available_devices:
            _emit_log(self.logger, "warning", "No microphone devices detected; audio capture disabled")
            self._is_recording = False
            return

        if self.device_index is None:
            self.device_index = available_devices[0].index

        try:
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                format=pyaudio.paInt16 if self.sample_width == 2 else pyaudio.paInt8,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
            )
            self._is_recording = True
            _emit_log(self.logger, "info", "Microphone stream opened", device_index=self.device_index)
        except Exception as error:
            _emit_log(self.logger, "warning", "Failed to open microphone stream", error=str(error))
            self._is_recording = False
            self.stop()

    def stop(self) -> None:
        """Close the active stream and release the PyAudio handle."""

        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as error:
                _emit_log(self.logger, "warning", "Error while closing microphone stream", error=str(error))
            finally:
                self._stream = None

        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception as error:
                _emit_log(self.logger, "warning", "Error while terminating PyAudio", error=str(error))
            finally:
                self._audio = None

        self._is_recording = False

    def stream(self, sink: AudioSink, *, max_frames: int | None = None) -> None:
        """Capture a bounded number of audio frames into the provided sink."""

        if not self._is_recording or self._stream is None:
            return

        emitted = 0
        try:
            while self._is_recording:
                if max_frames is not None and emitted >= max_frames:
                    break
                data = self._stream.read(self.chunk_size, exception_on_overflow=False)
                sink.write(
                    AudioFrame(
                        data=data,
                        format=AudioFormat(
                            sample_rate=self.sample_rate,
                            channels=self.channels,
                            sample_width=self.sample_width,
                        ),
                        metadata={"device_index": self.device_index},
                    )
                )
                emitted += 1
        except Exception as error:
            _emit_log(self.logger, "warning", "Error while reading microphone stream", error=str(error))
        finally:
            self._is_recording = False


class VoiceActivityDetector:
    """Detect voice activity in audio frames using simple energy heuristics."""

    def __init__(self, threshold: float = 500.0, logger: Any | None = None) -> None:
        self.threshold = threshold
        self.logger = logger

    def is_active(self, frame: AudioFrame) -> bool:
        """Return whether the supplied frame appears to contain voice energy."""

        if frame.is_empty():
            return False
        try:
            import array

            audio_data = array.array("h", frame.data)
            if len(audio_data) == 0:
                return False
            energy = sum(sample * sample for sample in audio_data) / len(audio_data)
            return energy > self.threshold
        except Exception as error:
            _emit_log(self.logger, "debug", "Voice activity detection fallback path used", error=str(error))
            return bool(frame.data)

    async def is_active_async(self, frame: AudioFrame) -> bool:
        """Asynchronously determine whether the frame contains voice activity."""

        return await asyncio.to_thread(self.is_active, frame)
