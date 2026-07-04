"""Main application orchestration for the NARVIS AI assistant.

This module wires the Core lifecycle, dependency injection container, logging,
configuration, event bus, plugin hooks, and major domain packages into a single
application entry point.
"""

from __future__ import annotations

import asyncio
import logging
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
from Automation import build_automation_services, register_automation_services
from Computer import (
    ApplicationManager,
    ApplicationResolver,
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
    build_desktop_control_service,
    register_computer_services,
)
from Core.config import AppConfig
from Core.engine import EngineStatus, NARVISRuntimeEngine
from Core.logger import ConsoleLogger, LogLevel
from Core.optimization import register_runtime_optimization_services
from Core.plugins import ManagedPluginHook, PluginDescriptor, PluginRegistry, register_plugin_services
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
from Dashboard import (
    DashboardLogBuffer,
    DashboardLogger,
    DashboardRuntimeActions,
    attach_dashboard_log_handler,
    build_dashboard_services,
    register_dashboard_services,
)
from Internet import (
    NullBrowser,
    NullFileDownloader,
    NullNewsProvider,
    NullHttpClient,
    NullSearchProvider,
    NullWeatherProvider,
    NullYouTubeProvider,
    build_internet_services,
    register_internet_services,
)
from Memory import (
    build_memory_integration_service,
    build_memory_services,
    register_memory_integration_services,
    register_memory_services,
)
from Skills import (
    build_builtin_skills,
    build_desktop_command_services,
    build_skill_services,
    DesktopCommandSkill,
    register_desktop_command_services,
    register_skill_services,
)
from Vision import build_vision_services, register_vision_services
from Voice import build_voice_services, register_voice_services


@dataclass(slots=True)
class NARVISConfig(AppConfig):
    """Concrete application configuration for the NARVIS runtime."""

    version: str = "1.0 Stable"
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
    bootstrapped: bool = False
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
        base_logger = ConsoleLogger(name="narvis")
        self.dashboard_log_buffer = DashboardLogBuffer()
        self.dashboard_log_handler = attach_dashboard_log_handler(self.dashboard_log_buffer)
        self.logger = DashboardLogger(delegate=base_logger, log_buffer=self.dashboard_log_buffer, name="narvis")
        self.container = DependencyContainer()
        self.event_bus = EventBus()
        self.coordinator = SystemCoordinator()
        self.module_loader = ModuleLoader(self.container)
        self.health_checker = HealthChecker()
        self.exception_handler = ExceptionHandler(self.logger)
        self.startup_manager = StartupManager()
        self.plugin_loader = PluginLoader()
        self.plugin_registry = PluginRegistry(logger=self.logger)
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
        if self.runtime_status.started:
            self.logger.log(LogLevel.INFO, "NARVIS runtime start requested while already running")
            return

        self.runtime_status.shutting_down = False
        if self.runtime_status.bootstrapped:
            self.lifecycle_manager.start(self._build_startup_context())
            self.engine.status = EngineStatus.RUNNING
        else:
            self.engine.start()
        self.runtime_status.started = True
        self.logger.log(LogLevel.INFO, "NARVIS runtime started")

    def shutdown(self) -> None:
        """Gracefully stop the runtime and all registered subsystems."""
        if self.runtime_status.shutting_down or not self.runtime_status.started:
            return

        self.runtime_status.shutting_down = True
        try:
            self.engine.stop()
            self.runtime_status.started = False
            self.logger.log(LogLevel.INFO, "NARVIS runtime stopped")
        finally:
            self.runtime_status.shutting_down = False

    def restart(self) -> None:
        """Restart the runtime while preserving the registered dashboard service."""

        self.logger.log(LogLevel.INFO, "Restarting NARVIS runtime")
        if self.runtime_status.started:
            self.shutdown()
        self.start()

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

    def _build_startup_context(self) -> StartupContext:
        """Create the startup context used by the lifecycle manager."""

        return StartupContext(config=self.config, logger=self.logger)

    def _bootstrap_runtime(self) -> None:
        """Build the runtime environment, load services, and initialize lifecycle."""
        self._create_directories()
        self._load_configuration()
        self._initialize_logging()
        self._register_services()
        self._register_plugins()
        self._register_health_checks()
        self.lifecycle_manager.start(self._build_startup_context())
        self.runtime_status.bootstrapped = True

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
        logging.getLogger().setLevel(logging.INFO if self.config.debug else logging.WARNING)
        self.dashboard_log_handler.setLevel(logging.INFO if self.config.debug else logging.WARNING)
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
        self.container.register_instance("dashboard_log_buffer", self.dashboard_log_buffer)
        self.container.register_instance("application", self)
        self.container.register_instance("engine", self.engine)
        self.container.register_instance("startup_manager", self.startup_manager)
        self.container.register_instance("lifecycle_manager", self.lifecycle_manager)
        self.container.register_instance("runtime_status", self.runtime_status)
        register_plugin_services(
            self.container,
            registry=self.plugin_registry,
            loader=self.plugin_loader,
            logger=self.logger,
        )

    def _build_computer_services(self) -> ComputerServices:
        """Create the concrete Computer services used by the desktop runtime."""
        application_resolver = ApplicationResolver(logger=self.logger)
        return ComputerServices(
            application_manager=ApplicationManager(
                resolver=application_resolver,
                logger=self.logger,
            ),
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
        runtime_optimizer = register_runtime_optimization_services(self.container, logger=self.logger)
        memory_services = build_memory_services(
            database_path=self.config.data_dir / "memory.sqlite3",
            logger=self.logger,
        )
        register_memory_services(self.container, services=memory_services, logger=self.logger)
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
            logger=self.logger,
        )
        register_memory_integration_services(self.container, memory_integration, logger=self.logger)
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
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            engine=self.engine,
            skill_executor=None,
            memory_integration=memory_integration,
            runtime_optimizer=runtime_optimizer,
            logger=self.logger,
        )

        computer_services = self._build_computer_services()
        desktop_control = build_desktop_control_service(computer_services, logger=self.logger)
        register_computer_services(
            self.container,
            services=computer_services,
            desktop_control=desktop_control,
            logger=self.logger,
        )
        desktop_control_service = self.container.resolve("desktop_control_service")
        desktop_command_services = build_desktop_command_services(
            desktop_control=desktop_control_service,
            intent_analyzer=intent_analyzer,
            router=router,
            logger=self.logger,
        )
        register_desktop_command_services(self.container, desktop_command_services, logger=self.logger)
        automation_services = build_automation_services(
            workspace_root=Path.cwd(),
            clipboard_manager=ClipboardAutomationAdapter(computer_services.clipboard_manager),
            keyboard_controller=KeyboardAutomationAdapter(computer_services.keyboard_controller),
            mouse_controller=MouseAutomationAdapter(computer_services.mouse_controller),
            logger=self.logger,
        )
        vision_services = build_vision_services(
            screenshot_capture=ScreenshotVisionAdapter(computer_services.screenshot_manager),
            screenshot_output_dir=self.config.data_dir / "screenshots",
            logger=self.logger,
        )
        voice_services = build_voice_services(logger=self.logger)
        internet_services = build_internet_services(
            browser=NullBrowser(),
            download_manager=NullFileDownloader(),
            news_provider=NullNewsProvider(),
            weather_provider=NullWeatherProvider(),
            youtube_provider=NullYouTubeProvider(),
            ai_provider=provider,
            runtime_optimizer=runtime_optimizer,
            logger=self.logger,
        )
        register_internet_services(self.container, internet_services, logger=self.logger)
        skill_services = build_skill_services(logger=self.logger)
        builtin_skills = build_builtin_skills(
            memory_service=memory_integration,
            internet_service=internet_services.internet_service,
            desktop_control=desktop_control_service,
            desktop_command_pipeline=desktop_command_services.pipeline,
            health_provider=self.health,
            catalog_provider=lambda: self._skill_catalog(skill_services.registry),
            logger=self.logger,
        )
        for skill in builtin_skills:
            skill_services.registry.register(skill)
        skill_services.registry.register(
            DesktopCommandSkill(
                name="desktop.command",
                description="Natural language desktop command skill",
                desktop_control=desktop_control_service,
                command_pipeline=desktop_command_services.pipeline,
                logger=self.logger,
            )
        )
        register_skill_services(self.container, skill_services, logger=self.logger)
        brain_engine.skill_executor = skill_services.executor
        register_automation_services(self.container, automation_services, logger=self.logger)
        self._register_builtin_plugins(skill_services.registry.count())

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
        self.container.register_instance("context_manager", context_manager)
        register_vision_services(self.container, services=vision_services, logger=self.logger)
        register_voice_services(self.container, services=voice_services, logger=self.logger)
        dashboard_services = build_dashboard_services(
            narvis_version=self.config.version,
            logger=self.logger,
            runtime_actions=DashboardRuntimeActions(
                start_callback=self.start,
                stop_callback=self.shutdown,
                restart_callback=self.restart,
                running_callback=lambda: self.runtime_status.started and not self.runtime_status.shutting_down,
                test_callback=self.health,
            ),
            health_provider=self.health,
            log_buffer=self.dashboard_log_buffer,
            insights_provider=self._dashboard_insights,
        )
        register_dashboard_services(self.container, dashboard_services)

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
                initializer=lambda context: voice_services.voice_runtime_service.initialize(context),
                shutdown_handler=voice_services.voice_runtime_service.shutdown,
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="vision",
                initializer=lambda context: vision_services.vision_service.initialize(context),
                shutdown_handler=vision_services.vision_service.shutdown,
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
        self.coordinator.register(
            RuntimeServiceComponent(
                name="skills",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Skill services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Skill services shutdown"),
            )
        )
        self.coordinator.register(
            RuntimeServiceComponent(
                name="dashboard",
                initializer=lambda context: self.logger.log(LogLevel.INFO, "Dashboard services initialized"),
                shutdown_handler=lambda: self.logger.log(LogLevel.INFO, "Dashboard services shutdown"),
            )
        )

        self.startup_manager.register(self._startup_hook)

    def _register_plugins(self) -> None:
        """Register plugin hooks for future integrations."""
        self.plugin_loader.register_hook(
            ManagedPluginHook(
                PluginDescriptor(
                    name="cloud.integration",
                    version=self.config.version,
                    description="Future cloud integration hook for NARVIS.",
                    kind="cloud",
                    services=("brain_provider", "event_bus"),
                ),
                self._cloud_plugin_hook,
                self.plugin_registry,
                logger=self.logger,
            )
        )
        self.plugin_loader.load_all(self.container, self.event_bus, self.logger)

    def _register_health_checks(self) -> None:
        """Register health checks for core services."""
        self.health_checker.register("brain_engine", lambda: HealthReport(name="brain_engine", status="ok", details={"module": "AI"}))
        self.health_checker.register("voice", lambda: self.container.resolve("voice_runtime_service").health_report())
        self.health_checker.register("vision", lambda: self.container.resolve("vision_service").health_report())
        self.health_checker.register(
            "memory",
            lambda: HealthReport(
                name="memory",
                status="ok",
                details={"module": "Memory", **self._dashboard_insights()["memory_details"]},
            ),
        )
        self.health_checker.register(
            "automation",
            lambda: HealthReport(
                name="automation",
                status="ok",
                details={"module": "Automation", "queued_actions": self.container.resolve("automation_service").pending_action_count()},
            ),
        )
        self.health_checker.register(
            "computer",
            lambda: HealthReport(
                name="computer",
                status="ok",
                details={
                    "module": "Computer",
                    **self.container.resolve("desktop_control").runtime_status(),
                },
            ),
        )
        self.health_checker.register(
            "internet",
            lambda: HealthReport(
                name="internet",
                status="ok",
                details={
                    "module": "Internet",
                    **self.container.resolve("internet_service").capabilities(),
                },
            ),
        )
        self.health_checker.register(
            "skills",
            lambda: HealthReport(
                name="skills",
                status="ok",
                details={"module": "Skills", "count": self.container.resolve("skill_registry").count()},
            ),
        )
        self.health_checker.register(
            "plugins",
            lambda: HealthReport(
                name="plugins",
                status="ok",
                details={
                    "module": "Plugins",
                    "registered": self.plugin_registry.total_count(),
                    "loaded": self.plugin_registry.loaded_count(),
                },
            ),
        )
        self.health_checker.register("dashboard", lambda: HealthReport(name="dashboard", status="ok", details={"module": "Dashboard"}))

    def _startup_hook(self, context: StartupContext) -> None:
        """Initialization hook triggered during startup."""
        self.logger.log(LogLevel.INFO, "Starting subsystems")
        self.event_bus.publish(SystemEvent(name="startup.begin", payload={"module": "core"}))

    def _cloud_plugin_hook(self, container: DependencyContainer, event_bus: EventBus, logger: Any) -> None:
        """Prepare a future cloud integration hook without performing real network work."""
        logger.log(LogLevel.INFO, "Cloud integration hook registered")
        event_bus.publish(SystemEvent(name="plugin.cloud.ready", payload={"module": "cloud"}))

    def _skill_catalog(self, registry: Any) -> list[dict[str, str]]:
        """Return a compact skill catalog for the help skill and dashboard use."""

        return [
            {"name": skill.name, "description": skill.description}
            for skill in registry.list_skills()
        ]

    def _register_builtin_plugins(self, skill_count: int) -> None:
        """Register the built-in runtime extension packs in the plugin registry."""

        for descriptor in (
            PluginDescriptor(
                name="skills.builtin",
                version=self.config.version,
                description="Built-in stable skill pack for the NARVIS runtime.",
                kind="skills",
                services=("skill_registry", "skill_executor"),
                metadata={"skill_count": skill_count},
            ),
            PluginDescriptor(
                name="automation.runtime",
                version=self.config.version,
                description="Stable automation runtime services and safe workspace adapters.",
                kind="automation",
                services=("automation_service", "scheduler", "task_queue", "workflow"),
            ),
            PluginDescriptor(
                name="internet.runtime",
                version=self.config.version,
                description="Stable internet runtime services with caching and aggregation.",
                kind="internet",
                services=("internet_service", "browser", "http_client"),
            ),
        ):
            self.plugin_registry.register(descriptor)
            self.plugin_registry.mark_loaded(descriptor.name)

    def _dashboard_insights(self) -> dict[str, Any]:
        """Return runtime counts displayed by the dashboard."""

        memory_snapshot = self.container.resolve("memory_service").snapshot_counts()
        return {
            "loaded_skills": self.container.resolve("skill_registry").count(),
            "loaded_plugins": self.plugin_registry.loaded_count(),
            "stored_memories": memory_snapshot.total_entries,
            "queued_actions": self.container.resolve("automation_service").pending_action_count(),
            "memory_details": {
                "total_entries": memory_snapshot.total_entries,
                "short_term_entries": memory_snapshot.short_term_entries,
                "long_term_entries": memory_snapshot.long_term_entries,
                "conversation_history_entries": memory_snapshot.conversation_history_entries,
            },
        }


async def _interactive_console_session(
    application: NARVISApplication,
    *,
    input_reader: Any | None = None,
    output_writer: Any | None = None,
) -> int:
    """Run the interactive console session on the main thread."""

    read_input = input if input_reader is None else input_reader
    write_output = print if output_writer is None else output_writer

    write_output("NARVIS Ready.")
    write_output("Type commands (type 'exit' to quit).")
    while True:
        command = read_input("> ")
        normalized_command = command.strip()
        if not normalized_command:
            continue
        if normalized_command.lower() == "exit":
            return 0
        response = await application.process_text_async(normalized_command)
        write_output(response)


async def main(*, input_reader: Any | None = None, output_writer: Any | None = None) -> int:
    """Start the NARVIS runtime and host an interactive console session."""

    application = NARVISApplication()
    try:
        await application.async_start()
        return await _interactive_console_session(
            application,
            input_reader=input_reader,
            output_writer=output_writer,
        )
    except (EOFError, KeyboardInterrupt):
        application.logger.log(LogLevel.INFO, "NARVIS runtime interrupted by user")
        return 0
    finally:
        await application.async_shutdown()


__all__ = ["NARVISApplication", "NARVISConfig", "RuntimeStatus", "main"]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
