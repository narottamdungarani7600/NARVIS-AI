"""Tests for the Voice module runtime registration and fallbacks."""

from __future__ import annotations

import shutil
import unittest
from unittest import mock
from pathlib import Path
from uuid import uuid4

from Core.system import DependencyContainer, EventBus
from Voice import (
    AudioDeviceInfo,
    AudioFormat,
    AudioFrame,
    AudioInputService,
    BaseSpeechToTextEngine,
    BaseTextToSpeechEngine,
    MicrophoneService,
    NullMicrophone,
    NullSpeechToTextEngine,
    NullTextToSpeechEngine,
    SpeechRecognitionService,
    VoiceListener,
    VoiceRuntimeHook,
    WakeWordService,
    build_voice_services,
    register_voice_services,
)
from Voice.manager import VoiceCommandProcessor
from Voice.microphone import BaseMicrophone
import narvis
from narvis import NARVISApplication


class _FakeSpeechEngine(BaseSpeechToTextEngine):
    """Speech engine stub used to control transcription behavior."""

    def __init__(self, name: str, text: str, available: bool = True) -> None:
        super().__init__(name=name)
        self._text = text
        self._available = available

    def is_available(self) -> bool:
        """Return the configured availability state."""

        return self._available

    def transcribe(self, audio: AudioFrame) -> str:
        """Return the preconfigured transcript."""

        return self._text


class _FakeTextToSpeechEngine(BaseTextToSpeechEngine):
    """Text-to-speech engine stub used for deterministic testing."""

    def __init__(self, available: bool = True) -> None:
        super().__init__(name="fake-tts")
        self._available = available

    def is_available(self) -> bool:
        """Return the configured availability state."""

        return self._available

    def synthesize(self, text: str) -> AudioFrame:
        """Return a synthetic frame for the supplied text."""

        return AudioFrame(data=text.encode("utf-8"), format=AudioFormat())


class _FakeMicrophone(BaseMicrophone):
    """Microphone stub that records start and stop calls."""

    def __init__(self, frames: list[AudioFrame] | None = None, available: bool = True) -> None:
        super().__init__(sample_rate=16000)
        self.frames = frames or []
        self.available = available
        self.start_calls = 0
        self.stop_calls = 0
        self.stream_calls = 0

    def start(self) -> None:
        """Record that audio capture started."""

        self.start_calls += 1

    def stop(self) -> None:
        """Record that audio capture stopped."""

        self.stop_calls += 1

    def stream(self, sink, *, max_frames: int | None = None) -> None:  # type: ignore[override]
        """Send the configured frames into the sink."""

        self.stream_calls += 1
        frames = self.frames if max_frames is None else self.frames[:max_frames]
        for frame in frames:
            sink.write(frame)

    def is_available(self) -> bool:
        """Return the configured availability state."""

        return self.available

    def list_devices(self) -> tuple[AudioDeviceInfo, ...]:
        """Return a single fake input device when available."""

        if not self.available:
            return ()
        return (
            AudioDeviceInfo(
                index=0,
                name="Fake Microphone",
                max_input_channels=1,
                default_sample_rate=16000,
            ),
        )


class VoiceRuntimeRegistrationTests(unittest.TestCase):
    """Verify Voice runtime registration and lifecycle behavior."""

    def test_register_voice_services_exposes_runtime_dependencies(self) -> None:
        container = DependencyContainer()
        services = build_voice_services(
            microphone=NullMicrophone(),
            offline_speech_engine=NullSpeechToTextEngine(),
            online_speech_engine=NullSpeechToTextEngine(),
            text_to_speech_engine=NullTextToSpeechEngine(),
        )

        register_voice_services(container, services=services)

        self.assertIs(container.resolve("voice_runtime_service"), services.voice_runtime_service)
        self.assertIs(container.resolve("voice_manager"), services.voice_manager)
        self.assertIs(container.resolve("voice_system"), services.voice_manager)
        self.assertIs(container.resolve("microphone_service"), services.microphone_service)
        self.assertIs(container.resolve("audio_input_service"), services.audio_input_service)
        self.assertIs(container.resolve("speech_recognition_service"), services.speech_recognition_service)
        self.assertIs(container.resolve("speaker_service"), services.speaker_service)
        self.assertIs(container.resolve("wake_word_service"), services.wake_word_service)
        self.assertIs(container.resolve("microphone"), services.microphone)

    def test_runtime_hook_publishes_registration_event(self) -> None:
        container = DependencyContainer()
        event_bus = EventBus()
        published: list[str] = []
        event_bus.subscribe("voice.services.registered", lambda event: published.append(event.name))
        services = build_voice_services(
            microphone=NullMicrophone(),
            offline_speech_engine=NullSpeechToTextEngine(),
            online_speech_engine=NullSpeechToTextEngine(),
            text_to_speech_engine=NullTextToSpeechEngine(),
        )

        hook = VoiceRuntimeHook(services=services)
        hook.load(container, event_bus=event_bus)

        self.assertIn("voice.services.registered", published)
        self.assertIs(container.resolve("voice_runtime_service"), services.voice_runtime_service)

    def test_voice_runtime_service_reports_degraded_health_with_null_backends(self) -> None:
        services = build_voice_services(
            microphone=NullMicrophone(),
            offline_speech_engine=NullSpeechToTextEngine(),
            online_speech_engine=NullSpeechToTextEngine(),
            text_to_speech_engine=NullTextToSpeechEngine(),
        )
        runtime_service = services.voice_runtime_service

        self.assertEqual(runtime_service.health_report().status, "stopped")

        runtime_service.initialize()
        health = runtime_service.health_report()

        self.assertEqual(health.status, "degraded")
        self.assertTrue(health.details["initialized"])
        self.assertTrue(health.details["optional_dependency_warnings"])

        runtime_service.shutdown()
        self.assertEqual(runtime_service.health_report().status, "stopped")


class VoiceBehaviorTests(unittest.TestCase):
    """Verify command processing, fallback order, and safe initialization."""

    def test_speech_recognition_service_falls_back_to_online_provider(self) -> None:
        service = SpeechRecognitionService(
            offline_engine=_FakeSpeechEngine("offline", "", available=True),
            online_engine=_FakeSpeechEngine("online", "hello narvis", available=True),
            prefer_offline=True,
        )

        result = service.transcribe(AudioFrame(data=b"audio"))

        self.assertEqual(result, "hello narvis")
        self.assertTrue(service.health_details()["any_available"])

    def test_voice_listener_strips_wake_word_from_transcript(self) -> None:
        microphone = _FakeMicrophone(frames=[AudioFrame(data=b"pcm")])
        listener = VoiceListener(
            audio_input_service=AudioInputService(MicrophoneService(microphone), default_max_frames=4),
            wake_word_service=WakeWordService(keyword="narvis"),
            speech_recognition_service=SpeechRecognitionService(
                offline_engine=_FakeSpeechEngine("offline", "Narvis open notes"),
                online_engine=_FakeSpeechEngine("online", ""),
            ),
        )

        result = listener.listen(require_wake_word=True)

        self.assertEqual(result, "open notes")
        self.assertEqual(listener.last_wake_word, "narvis")

    def test_voice_runtime_initialize_does_not_start_microphone_capture(self) -> None:
        microphone = _FakeMicrophone(frames=[AudioFrame(data=b"audio")], available=True)
        services = build_voice_services(
            microphone=microphone,
            offline_speech_engine=_FakeSpeechEngine("offline", "narvis hello"),
            online_speech_engine=NullSpeechToTextEngine(),
            text_to_speech_engine=_FakeTextToSpeechEngine(),
        )

        services.voice_runtime_service.initialize()

        self.assertEqual(microphone.start_calls, 0)
        self.assertEqual(microphone.stream_calls, 0)


class VoiceRuntimeIntegrationTests(unittest.TestCase):
    """Verify application startup remains healthy when audio dependencies are missing."""

    def test_narvis_application_starts_with_missing_audio_dependencies(self) -> None:
        temp_dir = Path.cwd() / "data" / "voice_test_tmp" / f"case_{uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        with mock.patch("Voice.realmic._load_pyaudio_module", return_value=None), mock.patch(
            "Voice.engines._load_speech_recognition_module",
            return_value=None,
        ), mock.patch("Voice.engines._load_pyttsx3_module", return_value=None):
            application = NARVISApplication(
                config=narvis.NARVISConfig(
                    data_dir=temp_dir / "data",
                    log_dir=temp_dir / "logs",
                )
            )
            try:
                application.start()
                voice_health = application.health()["voice"]
            finally:
                application.shutdown()

        self.assertTrue(application.runtime_status.bootstrapped)
        self.assertEqual(voice_health.status, "degraded")
        warnings = voice_health.details["optional_dependency_warnings"]
        self.assertTrue(any("PyAudio" in warning or "SpeechRecognition" in warning or "pyttsx3" in warning for warning in warnings))

    def test_narvis_application_wires_voice_command_processor_to_process_text(self) -> None:
        temp_dir = Path.cwd() / "data" / "voice_test_tmp" / f"case_{uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        with mock.patch("Voice.realmic._load_pyaudio_module", return_value=None), mock.patch(
            "Voice.engines._load_speech_recognition_module",
            return_value=None,
        ), mock.patch("Voice.engines._load_pyttsx3_module", return_value=None):
            application = NARVISApplication(
                config=narvis.NARVISConfig(
                    data_dir=temp_dir / "data",
                    log_dir=temp_dir / "logs",
                )
            )
            try:
                application.start()
                processor = application.container.resolve("voice_command_processor")
            finally:
                application.shutdown()

        handler = processor.command_handler
        self.assertIsNotNone(handler)
        self.assertIs(getattr(handler, "__self__", None), application)
        self.assertIs(getattr(handler, "__func__", None), NARVISApplication.process_text)


if __name__ == "__main__":
    unittest.main()
