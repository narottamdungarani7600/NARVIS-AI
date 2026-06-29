"""Main application orchestration for the NARVIS AI assistant.

This module wires the Core lifecycle, dependency injection container, logging,
configuration, event bus, plugin hooks, and major domain packages into a single
application entry point.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from AI.brain import BrainEngine
from AI.conversation import ChatHistoryManager, SessionManager
from AI.context import InMemoryContextManager
from AI.intent import IntentAnalyzer, RuleBasedIntentClassifier
from AI.prompts import PromptBuilder
from AI.providers import ProviderFactory
from AI.response import ResponseBuilder, ResponseGenerationOptions
from AI.router import IntentRouter
from Automation.files import NullFileManager
from Automation.folders import NullFolderManager
from Automation.scheduler import NullScheduler
from Automation.tasks import InMemoryTaskQueue
from Automation.workflow import SequentialWorkflow
from Computer import (
    ApplicationManager,
    ClipboardAutomationAdapter,
    ClipboardManager,
    ComputerServices,
    KeyboardAutomationAdapter,
    KeyboardController,
    MouseAutomationAdapter,
    MouseController,
    ScreenshotManager,
    ScreenshotVisionAdapter,
    WindowManager,
)
from Core.config import AppConfig
from Core.engine import ExecutionContext, NARVISRuntimeEngine
from Core.logger import ConsoleLogger, LogLevel
from Core.startup import StartupContext, StartupManager
from Core.system import (
    BaseSystemComponent,
    DependencyContainer,
    EventBus,
    ExceptionHandler,
    HealthChecker,
    HealthReport,
    LifecycleManager,
    ModuleLoader,
    PluginLoader,
    SystemCoordinator,
    SystemEvent,
)
from Internet.browser import NullBrowser
from Internet.downloader import NullFileDownloader
from Internet.news import NullNewsProvider
from Internet.requests import NullHttpClient
from Internet.search import NullSearchProvider
from Internet.weather import NullWeatherProvider
from Internet.wikipedia import NullWikipediaProvider
from Internet.youtube import NullYouTubeProvider
from Memory.long_term import InMemoryLongTermMemory
from Memory.profile import InMemoryProfileMemory
from Memory.ranking import ImportanceRanker
from Memory.search import SimpleMemorySearch
from Memory.session import InMemorySessionMemory
from Memory.short_term import InMemoryShortTermMemory
from Memory.storage import SQLiteMemoryStore
from Vision.analyzer import CompositeVisionAnalyzer
from Vision.camera import NullCamera
from Vision.detector import DetectionAnalyzer, NullFaceDetector, NullObjectDetector
from Vision.image import FileImageLoader, PassthroughImagePreprocessor
from Vision.ocr import NullOCRService, OCRAnalyzer
from Vision.vision import AnalysisResult
from Voice import (
    GoogleSpeechRecognitionEngine,
    KeywordWakeWordDetector,
    Pyttsx3TextToSpeechEngine,
    RealMicrophone,
    VoiceListener,
    VoiceSpeaker,
    VoiceSystemManager,
)


@dataclass(slots=True)
class NARVISConfig(AppConfig):
    """Concrete application configuration for the NARVIS runtime."""

    environment: str = "development"
    data_dir: Path = field(default_factory=lambda: Path("data"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    debug: bool = True
    ai_provider: str = "openai"
    ai_timeout_seconds: int = 20
    ai_max_retries: int = 3
    ai_temperature: float = 0.2
    ai_max_tokens: int = 512
    ai_stream: bool = False


@dataclass(slots=True)
class RuntimeStatus:
    """Represents the current runtime state of the application."""

    started: bool = False
    shutting_down: bool = False
    health: dict[str, HealthReport] = field(default_factory=dict)


class RuntimeServiceComponent(BaseSystemComponent):
    """Adapter that exposes arbitrary runtime services as system components."""

    def __init__(self, name: str, initializer: Any | None = None, shutdown_handler: Any | None = None) -> None:
        super().__init__(name)
        self._initializer = initializer
        self._shutdown_handler = shutdown_handler

    def _initialize(self, context: Any) -> None:
        if self._initializer is not None:
            self._initializer(context)

    def _shutdown(self) -> None:
        if self._shutdown_handler is not None:
            self._shutdown_handler()


class NARVISApplication:
    """Main orchestrator for the NARVIS AI assistant runtime."""

    def __init__(self, config: NARVISConfig | None = None) -> None:
        self.config = config or NARVISConfig()
        self.logger = ConsoleLogger(name="narvis")
        self.container = DependencyContainer()
        self.event_bus = EventBus()
        self.coordinator = SystemCoordinator()
        self.module_loader = ModuleLoader(self.container)
        self.health_checker = HealthChecker()
        self.exception_handler = ExceptionHandler(self.logger)
        self.startup_manager = StartupManager()
        self.plugin_loader = PluginLoader()
        self.lifecycle_manager = LifecycleManager(
            startup_manager=self.startup_manager,
            coordinator=self.coordinator,
            event_bus=self.event_bus,
            exception_handler=self.exception_handler,
        )
        self.runtime_status = RuntimeStatus()
        self.engine = NARVISRuntimeEngine(
            name="narvis-runtime",
            bootstrap=self._bootstrap_runtime,
            teardown=self._teardown_runtime,
        )
        self._register_default_services()

    def start(self) -> None:
        """Initialize the runtime services and mark the application as started."""
        self.engine.start()
        self.runtime_status.started = True
        self.logger.log(LogLevel.INFO, "NARVIS runtime started")

    def shutdown(self) -> None:
        """Gracefully stop the runtime and all registered subsystems."""
        if self.runtime_status.shutting_down:
            return
        self.runtime_status.shutting_down = True
        self.engine.stop()
        self.logger.log(LogLevel.INFO, "NARVIS runtime stopped")

    async def async_start(self) -> None:
        """Initialize the runtime asynchronously."""
        await asyncio.to_thread(self.start)

    async def async_shutdown(self) -> None:
        """Shut down the runtime asynchronously."""
        await asyncio.to_thread(self.shutdown)

    async def process_text_async(self, text: str) -> str:
        """Route text through the Brain engine asynchronously and return its response message."""
        brain_engine = self.container.resolve("brain_engine")
        response = await brain_engine.chat(text)
        return response.message

    def process_text(self, text: str) -> str:
        """Route text through the Brain engine and return its response message."""
        brain_engine = self.container.resolve("brain_engine")
        response = brain_engine.receive_text(text)
        return response.message

    def health(self) -> dict[str, HealthReport]:
        """Return the current health status for the runtime components."""
        self.runtime_status.health = self.health_checker.check_all()
        return self.runtime_status.health

    def _bootstrap_runtime(self) -> None:
        """Build the runtime environment, load services, and initialize lifecycle."""
        self._create_directories()
        self._load_configuration()
        self._initialize_logging()
        self._register_services()
        self._register_plugins()
        self._register_health_checks()
        self.lifecycle_manager.start(StartupContext(config=self.config, logger=self.logger))

    def _teardown_runtime(self) -> None:
        """Stop the runtime and release orchestration resources."""
        self.lifecycle_manager.stop()

    def _create_directories(self) -> None:
        """Create standard runtime directories for configuration and logging."""
        for path in (self.config.data_dir, self.config.log_dir):
            Path(path).mkdir(parents=True, exist_ok=True)

    def _load_configuration(self) -> None:
        """Load runtime configuration from the environment."""
        self.config.environment = os.getenv("NARVIS_ENV", self.config.environment)
        self.config.debug = os.getenv("NARVIS_DEBUG", "1") == "1"
        self.config.ai_provider = os.getenv("NARVIS_PROVIDER", self.config.ai_provider)
        self.config.ai_timeout_seconds = int(os.getenv("NARVIS_TIMEOUT_SECONDS", self.config.ai_timeout_seconds))
        self.config.ai_max_retries = int(os.getenv("NARVIS_MAX_RETRIES", self.config.ai_max_retries))
        self.config.ai_temperature = float(os.getenv("NARVIS_TEMPERATURE", self.config.ai_temperature))
        self.config.ai_max_tokens = int(os.getenv("NARVIS_MAX_TOKENS", self.config.ai_max_tokens))
        self.config.ai_stream = os.getenv("NARVIS_STREAM", "0") == "1"

    def _initialize_logging(self) -> None:
        """Ensure the logger reflects the configured debug level."""
        if self.config.debug:
            self.logger.log(LogLevel.INFO, "Debug logging enabled")

    def _register_default_services(self) -> None:
        """Register foundational services used by the orchestrator."""
        self.container.register_instance("config", self.config)
        self.container.register_instance("logger", self.logger)
        self.container.register_instance("event_bus", self.event_bus)
        self.container.register_instance("coordinator", self.coordinator)
        self.container.register_instance("module_loader", self.module_loader)
        self.container.register_instance("health_checker", self.health_checker)
        self.container.register_instance("exception_handler", self.exception_handler)

    def _build_computer_services(self) -> ComputerServices:
        """Create the concrete Computer services used by the desktop runtime."""
        return ComputerServices(
            application_manager=ApplicationManager(),
            clipboard_manager=ClipboardManager(),
            keyboard_controller=KeyboardController(),
            mouse_controller=MouseController(),
            screenshot_manager=ScreenshotManager(output_dir=self.config.data_dir / "screenshots"),
            window_manager=WindowManager(),
        )

    def _shutdown_computer_services(self, computer_services: ComputerServices) -> None:
        """Shutdown the concrete Computer services and log their lifecycle."""
        computer_services.shutdown()
        self.logger.log(LogLevel.INFO, "Computer services shutdown")

    def _register_services(self) -> None:
        """Register concrete runtime services for the package ecosystem."""
        storage = SQLiteMemoryStore(database_path=self.config.data_dir / "memory.sqlite3")
        short_term = InMemoryShortTermMemory(repository=storage)
        long_term = InMemoryLongTermMemory(repository=storage)
        session_memory = InMemorySessionMemory(repository=storage)
        profile_memory = InMemoryProfileMemory(repository=storage)
        ranking = ImportanceRanker()
        search = SimpleMemorySearch(repository=storage)
        session_manager = SessionManager(logger=self.logger)
        chat_history_manager = ChatHistoryManager(max_turns=50, logger=self.logger)
        context_manager = InMemoryContextManager(
            session_manager=session_manager,
            chat_history_manager=chat_history_manager,
            logger=self.logger,
        )
        intent_classifier = RuleBasedIntentClassifier(logger=self.logger)
        intent_analyzer = IntentAnalyzer(classifier=intent_classifier, logger=self.logger)
        router = IntentRouter(logger=self.logger)
        prompt_builder = PromptBuilder()

        provider = ProviderFactory.create_default(
            provider_name=self.config.ai_provider,
            logger=self.logger,
            timeout_seconds=self.config.ai_timeout_seconds,
            max_retries=self.config.ai_max_retries,
        )
        response_builder = ResponseBuilder(
            provider=provider,
            prompt_builder=prompt_builder,
            options=ResponseGenerationOptions(
                max_tokens=self.config.ai_max_tokens,
                temperature=self.config.ai_temperature,
                stream=self.config.ai_stream,
            ),
            logger=self.logger,
        )
        brain_engine = BrainEngine(
            intent_classifier=intent_classifier,
            intent_analyzer=intent_analyzer,
            context_manager=context_manager,
            router=router,
            response_builder=response_builder,
            provider=provider,
            prompt_builder=prompt_builder,
            session_manager=session_manager,
            chat_history_manager=chat_history_manager,
            short_term_memory=short_term,
            long_term_memory=long_term,
            engine=self.engine,
            logger=self.logger,
        )

        microphone = RealMicrophone(sample_rate=16000)
        wake_word_detector = KeywordWakeWordDetector(keyword="narvis")
        speech_to_text_engine = GoogleSpeechRecognitionEngine(language="en-US")
        text_to_speech_engine = Pyttsx3TextToSpeechEngine(language="en-US")
        voice_listener = VoiceListener(
            microphone=microphone,
            wake_word_detector=wake_word_detector,
            speech_to_text_engine=speech_to_text_engine,
        )
        voice_speaker = VoiceSpeaker(text_to_speech_engine=text_to_speech_engine)
        voice_system = VoiceSystemManager(
            microphone=microphone,
            wake_word_detector=wake_word_detector,
            speech_to_text_engine=speech_to_text_engine,
            text_to_speech_engine=text_to_speech_engine,
        )

        computer_services = self._build_computer_services()
        camera = NullCamera()
        screenshot_capture = ScreenshotVisionAdapter(computer_services.screenshot_manager)
        image_loader = FileImageLoader()
        image_preprocessor = PassthroughImagePreprocessor()
        ocr_service = NullOCRService()
        ocr_analyzer = OCRAnalyzer(ocr_service=ocr_service)
        detector = NullObjectDetector()
        face_detector = NullFaceDetector()
        detection_analyzer = DetectionAnalyzer(object_detector=detector, face_detector=face_detector)
        vision_analyzer = CompositeVisionAnalyzer(
            camera=camera,
            screenshot_capture=screenshot_capture,
            ocr_analyzer=ocr_analyzer,
            detection_analyzer=detection_analyzer,
        )

        self.container.register_instance("brain_engine", brain_engine)
        self.container.register_instance("ai_provider", provider)
        self.container.register_instance("brain_provider", provider)
        self.container.register_instance("intent_classifier", intent_classifier)
        self.container.register_instance("intent_analyzer", intent_analyzer)
        self.container.register_instance("intent_router", router)
        self.container.register_instance("prompt_builder", prompt_builder)
        self.container.register_instance("response_builder", response_builder)
        self.container.register_instance("session_manager", session_manager)
        self.container.register_instance("chat_history_manager", chat_history_manager)
        self.container.register_instance("voice_listener", voice_listener)
        self.container.register_instance("voice_speaker", voice_speaker)
        self.container.register_instance("voice_system", voice_system)
        self.container.register_instance("microphone", microphone)
        self.container.register_instance("wake_word_detector", wake_word_detector)
        self.container.register_instance("speech_to_text_engine", speech_to_text_engine)
        self.container.register_instance("text_to_speech_engine", text_to_speech_engine)
        self.container.register_instance("vision_analyzer", vision_analyzer)
        self.container.register_instance("memory_storage", storage)
        self.container.register_instance("short_term_memory", short_term)
        self.container.register_instance("long_term_memory", long_term)
        self.container.register_instance("session_memory", session_memory)
        self.container.register_instance("profile_memory", profile_memory)
        self.container.register_instance("memory_ranker", ranking)
        self.container.register_instance("memory_search", search)
        self.container.register_instance("context_manager", context_manager)
        self.container.register_instance("computer_services", computer_services)
        self.container.register_instance("application_manager", computer_services.application_manager)
        self.container.register_instance("window_manager", computer_services.window_manager)
        self.container.register_instance("screenshot_manager", computer_services.screenshot_manager)
        self.container.register_instance("computer_application_manager", computer_services.application_manager)
        self.container.register_instance("computer_clipboard_manager", computer_services.clipboard_manager)
        self.container.register_instance("computer_keyboard_controller", computer_services.keyboard_controller)
        self.container.register_instance("computer_mouse_controller", computer_services.mouse_controller)
        self.container.register_instance("computer_screenshot_manager", computer_services.screenshot_manager)
        self.container.register_instance("computer_window_manager", computer_services.window_manager)
        self.container.register_instance("file_manager", NullFileManager())
        self.container.register_instance("folder_manager", NullFolderManager())
        self.container.register_instance("clipboard_manager", ClipboardAutomationAdapter(computer_services.clipboard_manager))
        self.container.register_instance("keyboard_controller", KeyboardAutomationAdapter(computer_services.keyboard_controller))
        self.container.register_instance("mouse_controller", MouseAutomationAdapter(computer_services.mouse_controller))
        self.container.register_instance("scheduler", NullScheduler())
        self.container.register_instance("task_queue", InMemoryTaskQueue())
        self.container.register_instance("workflow", SequentialWorkflow())
        self.container.register_instance("browser", NullBrowser())
        self.container.register_instance("http_client", NullHttpClient())
        self.container.register_instance("download_manager", NullFileDownloader())
        self.container.register_instance("search_provider", NullSearchProvider())
        self.container.register_instance("news_provider", NullNewsProvider())
        self.container.register_instance("weather_provider", NullWeatherProvider())
        self.container.register_instance("wikipedia_provider", NullWikipediaProvider())
        self.container.register_instance("youtube_provider", NullYouTubeProvider())
        self.container.register_instance("image_loader", image_loader)
        self.container.register_instance("image_preprocessor", image_preprocessor)
        self.container.register_instance("ocr_analyzer", ocr_analyzer)
        self.container.register_instance("detector", detection_analyzer)
        self.container.register_instance("camera", camera)
        self.container.register_instance("screenshot_capture", screenshot_capture)
        self.container.register_instance("voice_listener", voice_listener)
        self.container.register_instance("voice_speaker", voice_speaker)

        self.coordinator.register(
            RuntimeServiceComponent(
                name="brain_engine",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Brain engine initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Brain engine shutdown"),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="voice",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Voice services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Voice services shutdown"),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="vision",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Vision services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Vision services shutdown"),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="memory",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Memory services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Memory services shutdown"),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="automation",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Automation services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Automation services shutdown"),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="computer",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Computer services initialized"),
                shutdown_handler=lambda: self._shutdown_computer_services(computer_services),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="internet",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Internet services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Internet services shutdown"),
            )
        )

        self.startup_manager.register(self._startup_hook)

    def _register_plugins(self) -> None:
        """Register plugin hooks for future integrations."""
        self.plugin_loader.register_hook(self._cloud_plugin_hook)
        self.plugin_loader.load_all(self.container, self.event_bus, self.logger)

    def _register_health_checks(self) -> None:
        """Register health checks for core services."""
        self.health_checker.register("brain_engine", lambda: HealthReport(name="brain_engine", status="ok", details={"module": "AI"}))
        self.health_checker.register("voice", lambda: HealthReport(name="voice", status="ok", details={"module": "Voice"}))
        self.health_checker.register("vision", lambda: HealthReport(name="vision", status="ok", details={"module": "Vision"}))
        self.health_checker.register("memory", lambda: HealthReport(name="memory", status="ok", details={"module": "Memory"}))
        self.health_checker.register("automation", lambda: HealthReport(name="automation", status="ok", details={"module": "Automation"}))
        self.health_checker.register(
            "computer",
            lambda: HealthReport(
                name="computer",
                status="ok",
                details={
                    "module": "Computer",
                    "services": [
                        "application_manager",
                        "clipboard_manager",
                        "keyboard_controller",
                        "mouse_controller",
                        "screenshot_manager",
                        "window_manager",
                    ],
                },
            ),
        )
        self.health_checker.register("internet", lambda: HealthReport(name="internet", status="ok", details={"module": "Internet"}))

    def _startup_hook(self, context: StartupContext) -> None:
        """Initialization hook triggered during startup."""
        self.logger.log(LogLevel.INFO, "Starting subsystems")
        self.event_bus.publish(SystemEvent(name="startup.begin", payload={"module": "core"}))

    def _cloud_plugin_hook(self, container: DependencyContainer, event_bus: EventBus, logger: Any) -> None:
        """Prepare a future cloud integration hook without performing real network work."""
        logger.log(LogLevel.INFO, "Cloud integration hook registered")
        event_bus.publish(SystemEvent(name="plugin.cloud.ready", payload={"module": "cloud"}))


__all__ = ["NARVISApplication", "NARVISConfig", "RuntimeStatus"]
