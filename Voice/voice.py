"""Runtime composition, health monitoring, and DI registration for Voice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from Core.system import HealthReport

from .audio import AudioDeviceInfo, _emit_log
from .engines import GoogleSpeechRecognitionEngine, OfflineSpeechRecognitionEngine, Pyttsx3TextToSpeechEngine
from .listener import VoiceListener
from .manager import VoiceCommandProcessor, VoiceSessionManager, VoiceSystemManager
from .microphone import AudioInputService, Microphone, MicrophoneService
from .realmic import RealMicrophone
from .speaker import SpeakerService, VoiceSpeaker
from .speech import (
    NullSpeechToTextEngine,
    NullTextToSpeechEngine,
    SpeechRecognitionService,
    SpeechToTextEngine,
    TextToSpeechEngine,
)
from .wakeword import KeywordWakeWordDetector, WakeWordDetector, WakeWordService


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Voice."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class EventPublisher(Protocol):
    """Protocol for runtime event publishers used by Voice hooks."""

    def publish(self, event: Any) -> None:
        """Publish a runtime event."""


@dataclass(slots=True)
class VoiceConfiguration:
    """Typed configuration for the Voice module."""

    wake_word: str = "narvis"
    language: str = "en-US"
    sample_rate: int = 16000
    chunk_size: int = 1024
    channels: int = 1
    sample_width: int = 2
    device_index: int | None = None
    prefer_offline: bool = True
    enable_online_fallback: bool = True
    default_capture_frames: int = 16
    auto_strip_wake_word: bool = True
    startup_listen_enabled: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VoiceServices:
    """Container for the concrete services that make up the Voice module."""

    voice_runtime_service: "VoiceRuntimeService"
    voice_manager: VoiceSystemManager
    voice_listener: VoiceListener
    voice_speaker: VoiceSpeaker
    microphone_service: MicrophoneService
    audio_input_service: AudioInputService
    speech_recognition_service: SpeechRecognitionService
    speaker_service: SpeakerService
    wake_word_service: WakeWordService
    voice_command_processor: VoiceCommandProcessor
    session_manager: VoiceSessionManager
    microphone: Microphone
    offline_speech_engine: SpeechToTextEngine
    online_speech_engine: SpeechToTextEngine
    text_to_speech_engine: TextToSpeechEngine
    wake_word_detector: WakeWordDetector
    config: VoiceConfiguration


class VoiceRuntimeService:
    """Lifecycle and health service for the complete Voice subsystem."""

    def __init__(
        self,
        *,
        config: VoiceConfiguration,
        microphone_service: MicrophoneService,
        audio_input_service: AudioInputService,
        speech_recognition_service: SpeechRecognitionService,
        speaker_service: SpeakerService,
        wake_word_service: WakeWordService,
        voice_command_processor: VoiceCommandProcessor,
        voice_manager: VoiceSystemManager,
        logger: Any | None = None,
    ) -> None:
        self.config = config
        self.microphone_service = microphone_service
        self.audio_input_service = audio_input_service
        self.speech_recognition_service = speech_recognition_service
        self.speaker_service = speaker_service
        self.wake_word_service = wake_word_service
        self.voice_command_processor = voice_command_processor
        self.voice_manager = voice_manager
        self.logger = logger
        self._initialized = False
        _emit_log(self.logger, "info", "Voice runtime service constructed")

    @property
    def initialized(self) -> bool:
        """Return whether the Voice runtime service has been initialized."""

        return self._initialized

    def initialize(self, context: Any | None = None) -> None:
        """Initialize the Voice runtime service without starting active capture."""

        if self._initialized:
            _emit_log(self.logger, "warning", "Voice runtime initialize requested while already initialized")
            return

        devices = self.microphone_service.detect_devices(refresh=True)
        _emit_log(
            self.logger,
            "info",
            "Voice runtime initialized",
            detected_devices=len(devices),
            context_type=type(context).__name__ if context is not None else "none",
            startup_listen_enabled=self.config.startup_listen_enabled,
        )
        self._initialized = True

    def shutdown(self) -> None:
        """Shutdown Voice services and release any open microphone resources."""

        self.voice_manager.stop()
        self.microphone_service.stop()
        self._initialized = False
        _emit_log(self.logger, "info", "Voice runtime shutdown")

    def optional_dependency_warnings(self) -> list[str]:
        """Return a deduplicated list of degraded dependency warnings."""

        warnings = (
            self.microphone_service.dependency_warnings()
            + self.speech_recognition_service.dependency_warnings()
            + self.speaker_service.dependency_warnings()
        )
        unique: list[str] = []
        for warning in warnings:
            if warning not in unique:
                unique.append(warning)
        return unique

    def health_report(self) -> HealthReport:
        """Return a structured health snapshot for the Voice module."""

        devices = self.microphone_service.detect_devices()
        microphone_available = self.microphone_service.is_available()
        recognition_details = self.speech_recognition_service.health_details()
        speaker_available = self.speaker_service.is_available()
        warnings = self.optional_dependency_warnings()

        status = "ok"
        if not self._initialized:
            status = "stopped"
        elif not microphone_available or not recognition_details["any_available"] or not speaker_available:
            status = "degraded"

        return HealthReport(
            name="voice",
            status=status,
            details={
                "module": "Voice",
                "initialized": self._initialized,
                "wake_word": self.config.wake_word,
                "microphone_available": microphone_available,
                "detected_devices": [self._device_summary(device) for device in devices],
                "speech_recognition": recognition_details,
                "text_to_speech_available": speaker_available,
                "manager_state": self.voice_manager.get_state(),
                "optional_dependency_warnings": warnings,
            },
        )

    @staticmethod
    def _device_summary(device: AudioDeviceInfo) -> dict[str, Any]:
        """Return a serializable summary for a detected audio device."""

        return {
            "index": device.index,
            "name": device.name,
            "max_input_channels": device.max_input_channels,
            "default_sample_rate": device.default_sample_rate,
        }


def build_voice_services(
    *,
    config: VoiceConfiguration | None = None,
    microphone: Microphone | None = None,
    microphone_service: MicrophoneService | None = None,
    audio_input_service: AudioInputService | None = None,
    offline_speech_engine: SpeechToTextEngine | None = None,
    online_speech_engine: SpeechToTextEngine | None = None,
    speech_recognition_service: SpeechRecognitionService | None = None,
    text_to_speech_engine: TextToSpeechEngine | None = None,
    speaker_service: SpeakerService | None = None,
    wake_word_detector: WakeWordDetector | None = None,
    wake_word_service: WakeWordService | None = None,
    voice_listener: VoiceListener | None = None,
    voice_command_processor: VoiceCommandProcessor | None = None,
    voice_manager: VoiceSystemManager | None = None,
    session_manager: VoiceSessionManager | None = None,
    command_handler: Callable[[str], str | None] | None = None,
    logger: Any | None = None,
) -> VoiceServices:
    """Build the Voice service bundle using constructor injection."""

    resolved_config = config or VoiceConfiguration()
    resolved_microphone = microphone or RealMicrophone(
        sample_rate=resolved_config.sample_rate,
        chunk_size=resolved_config.chunk_size,
        channels=resolved_config.channels,
        sample_width=resolved_config.sample_width,
        device_index=resolved_config.device_index,
        logger=logger,
    )
    resolved_microphone_service = microphone_service or MicrophoneService(resolved_microphone, logger=logger)
    resolved_audio_input = audio_input_service or AudioInputService(
        microphone_service=resolved_microphone_service,
        default_max_frames=resolved_config.default_capture_frames,
    )
    resolved_offline_engine = offline_speech_engine or OfflineSpeechRecognitionEngine(
        language=resolved_config.language,
        logger=logger,
    )
    resolved_online_engine = online_speech_engine or (
        GoogleSpeechRecognitionEngine(language=resolved_config.language, logger=logger)
        if resolved_config.enable_online_fallback
        else NullSpeechToTextEngine(logger=logger)
    )
    resolved_speech_service = speech_recognition_service or SpeechRecognitionService(
        offline_engine=resolved_offline_engine,
        online_engine=resolved_online_engine,
        prefer_offline=resolved_config.prefer_offline,
        logger=logger,
    )
    resolved_tts_engine = text_to_speech_engine or Pyttsx3TextToSpeechEngine(
        language=resolved_config.language,
        logger=logger,
    )
    resolved_speaker_service = speaker_service or VoiceSpeaker(resolved_tts_engine, logger=logger)
    resolved_wake_word_detector = wake_word_detector or KeywordWakeWordDetector(
        keyword=resolved_config.wake_word,
        logger=logger,
    )
    resolved_wake_word_service = wake_word_service or WakeWordService(
        resolved_wake_word_detector,
        keyword=resolved_config.wake_word,
        logger=logger,
    )
    resolved_listener = voice_listener or VoiceListener(
        audio_input_service=resolved_audio_input,
        wake_word_service=resolved_wake_word_service,
        speech_recognition_service=resolved_speech_service,
        logger=logger,
        strip_wake_word=resolved_config.auto_strip_wake_word,
    )
    resolved_session_manager = session_manager or VoiceSessionManager(logger=logger)
    resolved_command_processor = voice_command_processor or VoiceCommandProcessor(
        command_handler=command_handler,
        logger=logger,
    )
    resolved_manager = voice_manager or VoiceSystemManager(
        listener=resolved_listener,
        speaker=resolved_speaker_service,
        command_processor=resolved_command_processor,
        session_manager=resolved_session_manager,
        logger=logger,
    )
    runtime_service = VoiceRuntimeService(
        config=resolved_config,
        microphone_service=resolved_microphone_service,
        audio_input_service=resolved_audio_input,
        speech_recognition_service=resolved_speech_service,
        speaker_service=resolved_speaker_service,
        wake_word_service=resolved_wake_word_service,
        voice_command_processor=resolved_command_processor,
        voice_manager=resolved_manager,
        logger=logger,
    )
    _emit_log(
        logger,
        "info",
        "Built voice services",
        microphone_type=type(resolved_microphone).__name__,
        offline_engine=resolved_offline_engine.name,
        online_engine=resolved_online_engine.name,
        tts_engine=resolved_tts_engine.name,
    )
    return VoiceServices(
        voice_runtime_service=runtime_service,
        voice_manager=resolved_manager,
        voice_listener=resolved_listener,
        voice_speaker=resolved_speaker_service if isinstance(resolved_speaker_service, VoiceSpeaker) else VoiceSpeaker(resolved_tts_engine, logger=logger),
        microphone_service=resolved_microphone_service,
        audio_input_service=resolved_audio_input,
        speech_recognition_service=resolved_speech_service,
        speaker_service=resolved_speaker_service,
        wake_word_service=resolved_wake_word_service,
        voice_command_processor=resolved_command_processor,
        session_manager=resolved_session_manager,
        microphone=resolved_microphone,
        offline_speech_engine=resolved_offline_engine,
        online_speech_engine=resolved_online_engine,
        text_to_speech_engine=resolved_tts_engine,
        wake_word_detector=resolved_wake_word_detector,
        config=resolved_config,
    )


def register_voice_services(
    container: DependencyRegistrar,
    *,
    services: VoiceServices | None = None,
    config: VoiceConfiguration | None = None,
    logger: Any | None = None,
) -> VoiceServices:
    """Register Voice services in the shared dependency-injection container."""

    resolved_services = services or build_voice_services(config=config, logger=logger)
    container.register_instance("voice_runtime_service", resolved_services.voice_runtime_service)
    container.register_instance("voice_service", resolved_services.voice_runtime_service)
    container.register_instance("voice_manager", resolved_services.voice_manager)
    container.register_instance("voice_system", resolved_services.voice_manager)
    container.register_instance("voice_listener", resolved_services.voice_listener)
    container.register_instance("voice_speaker", resolved_services.voice_speaker)
    container.register_instance("microphone_service", resolved_services.microphone_service)
    container.register_instance("audio_input_service", resolved_services.audio_input_service)
    container.register_instance("speech_recognition_service", resolved_services.speech_recognition_service)
    container.register_instance("speaker_service", resolved_services.speaker_service)
    container.register_instance("wake_word_service", resolved_services.wake_word_service)
    container.register_instance("voice_command_processor", resolved_services.voice_command_processor)
    container.register_instance("voice_session_manager", resolved_services.session_manager)
    container.register_instance("voice_config", resolved_services.config)

    container.register_instance("microphone", resolved_services.microphone)
    container.register_instance("wake_word_detector", resolved_services.wake_word_detector)
    container.register_instance("speech_to_text_engine", resolved_services.speech_recognition_service.primary_engine())
    container.register_instance("text_to_speech_engine", resolved_services.text_to_speech_engine)
    _emit_log(logger, "info", "Registered voice services in container")
    return resolved_services


class VoiceRuntimeHook:
    """Runtime hook that registers Voice services during startup or plugin load."""

    def __init__(
        self,
        *,
        services: VoiceServices | None = None,
        config: VoiceConfiguration | None = None,
        logger: Any | None = None,
    ) -> None:
        self.services = services
        self.config = config
        self.logger = logger

    def load(
        self,
        container: DependencyRegistrar,
        event_bus: EventPublisher | None = None,
        logger: Any | None = None,
    ) -> None:
        """Register Voice services and publish a readiness event if possible."""

        resolved_logger = logger or self.logger
        self.services = register_voice_services(
            container,
            services=self.services,
            config=self.config,
            logger=resolved_logger,
        )
        if event_bus is not None:
            try:
                from Core.system import SystemEvent

                event_bus.publish(SystemEvent(name="voice.services.registered", payload={"module": "Voice"}))
            except Exception:
                _emit_log(resolved_logger, "warning", "Unable to publish voice registration event")
        _emit_log(resolved_logger, "info", "Voice runtime hook completed")


__all__ = [
    "DependencyRegistrar",
    "EventPublisher",
    "VoiceConfiguration",
    "VoiceRuntimeHook",
    "VoiceRuntimeService",
    "VoiceServices",
    "build_voice_services",
    "register_voice_services",
]
