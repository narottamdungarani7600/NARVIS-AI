"""Runtime integration helpers and service objects for the NARVIS dashboard."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Mapping, Protocol

from Core.logger import BaseLogger, LogLevel
from Core.system import HealthReport

from .status import (
    DashboardRuntimeActions,
    DashboardSnapshot,
    LogEntry,
    MetricsProvider,
    ModuleStatus,
    PlatformSystemMetricsProvider,
    RuntimeInsights,
    utc_now,
)


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by the dashboard."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class EventPublisher(Protocol):
    """Protocol for optional event publishers used during registration."""

    def publish(self, event: Any) -> None:
        """Publish a runtime event."""


class DashboardLogBuffer:
    """Thread-safe rolling buffer of runtime log entries."""

    def __init__(self, capacity: int = 250) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=capacity)
        self._lock = Lock()

    def append(
        self,
        *,
        level: str,
        source: str,
        message: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Append a new runtime log entry to the buffer."""

        entry = LogEntry(
            timestamp=utc_now(),
            level=level,
            source=source,
            message=message,
            context=dict(context or {}),
        )
        with self._lock:
            self._entries.append(entry)

    def entries(self) -> tuple[LogEntry, ...]:
        """Return the currently buffered log entries in arrival order."""

        with self._lock:
            return tuple(self._entries)


class DashboardStdlibLogHandler(logging.Handler):
    """Logging handler that mirrors stdlib log records into the dashboard buffer."""

    def __init__(self, log_buffer: DashboardLogBuffer) -> None:
        super().__init__()
        self.log_buffer = log_buffer

    def emit(self, record: logging.LogRecord) -> None:
        """Mirror the stdlib log record into the dashboard log buffer."""

        try:
            self.log_buffer.append(
                level=record.levelname,
                source=record.name,
                message=record.getMessage(),
            )
        except Exception:  # pragma: no cover - logging must never raise
            return


def attach_dashboard_log_handler(log_buffer: DashboardLogBuffer) -> DashboardStdlibLogHandler:
    """Attach a dashboard log handler to the root stdlib logger once."""

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, DashboardStdlibLogHandler) and handler.log_buffer is log_buffer:
            return handler

    handler = DashboardStdlibLogHandler(log_buffer)
    root_logger.addHandler(handler)
    return handler


class DashboardLogger(BaseLogger):
    """Logger wrapper that forwards messages and stores them for the dashboard."""

    def __init__(self, delegate: Any, log_buffer: DashboardLogBuffer, name: str = "narvis") -> None:
        super().__init__(name=name)
        self._delegate = delegate
        self._log_buffer = log_buffer

    def log(self, level: LogLevel, message: str, **context: Any) -> None:
        """Record the message for the dashboard and forward it downstream."""

        self._log_buffer.append(level=level.value, source=self.name, message=message, context=context)
        self._delegate.log(level, message, **context)


class DashboardModule:
    """Dashboard service registered inside the NARVIS dependency container."""

    def __init__(
        self,
        *,
        narvis_version: str,
        logger: Any,
        runtime_actions: DashboardRuntimeActions,
        health_provider: Callable[[], Mapping[str, HealthReport]],
        log_buffer: DashboardLogBuffer,
        metrics_provider: MetricsProvider | None = None,
        insights_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self._narvis_version = narvis_version
        self._logger = logger
        self._runtime_actions = runtime_actions
        self._health_provider = health_provider
        self._log_buffer = log_buffer
        self._metrics_provider = metrics_provider or PlatformSystemMetricsProvider()
        self._insights_provider = insights_provider

    def run(self) -> None:
        """Launch the Tkinter dashboard window and block until it closes."""

        self._logger.log(LogLevel.INFO, "Launching dashboard UI")
        from .ui import DashboardUI

        ui = DashboardUI(self)
        ui.run()
        self._logger.log(LogLevel.INFO, "Dashboard UI closed")

    def get_snapshot(self) -> DashboardSnapshot:
        """Collect a full dashboard snapshot for the current runtime state."""

        runtime_state = "running" if self._runtime_actions.is_running() else "stopped"
        reports = self._read_health_reports()
        metrics = self._metrics_provider.snapshot(self._narvis_version)
        insights = self._read_runtime_insights()
        modules = self._build_module_statuses(reports, runtime_state=runtime_state)
        return DashboardSnapshot(
            runtime_state=runtime_state,
            metrics=metrics,
            insights=insights,
            modules=modules,
            logs=self._log_buffer.entries(),
            refreshed_at=utc_now(),
        )

    def start_runtime(self) -> None:
        """Start the runtime from the dashboard."""

        self._logger.log(LogLevel.INFO, "Dashboard requested runtime start")
        self._runtime_actions.start()

    def stop_runtime(self) -> None:
        """Stop the runtime from the dashboard."""

        self._logger.log(LogLevel.INFO, "Dashboard requested runtime stop")
        self._runtime_actions.stop()

    def restart_runtime(self) -> None:
        """Restart the runtime from the dashboard."""

        self._logger.log(LogLevel.INFO, "Dashboard requested runtime restart")
        self._runtime_actions.restart()

    def test_modules(self) -> tuple[ModuleStatus, ...]:
        """Run module tests through the injected runtime action contract."""

        if not self._runtime_actions.is_running():
            self._logger.log(LogLevel.WARNING, "Module test requested while the runtime is stopped")
            return self._build_module_statuses(self._read_health_reports(), runtime_state="stopped")

        reports = self._coerce_reports(self._runtime_actions.test_modules())
        summary = {name: report.status for name, report in reports.items()}
        self._logger.log(LogLevel.INFO, "Module test completed", results=summary)
        return self._build_module_statuses(reports, runtime_state="running")

    def record_ui_error(self, error: Exception) -> None:
        """Record an unexpected dashboard UI error through the shared logger."""

        self._logger.log(LogLevel.ERROR, "Dashboard UI error", error=str(error))

    def _read_health_reports(self) -> dict[str, HealthReport]:
        """Safely read the registered runtime health reports."""

        try:
            return self._coerce_reports(self._health_provider())
        except Exception as error:  # pragma: no cover - defensive handling
            self._logger.log(LogLevel.ERROR, "Unable to collect dashboard health snapshot", error=str(error))
            return {}

    def _read_runtime_insights(self) -> RuntimeInsights:
        """Safely read runtime-level insight counts for the dashboard."""

        if self._insights_provider is None:
            return RuntimeInsights()
        try:
            return self._coerce_insights(self._insights_provider())
        except Exception as error:  # pragma: no cover - defensive handling
            self._logger.log(LogLevel.ERROR, "Unable to collect dashboard runtime insights", error=str(error))
            return RuntimeInsights()

    def _build_module_statuses(
        self,
        reports: Mapping[str, HealthReport],
        *,
        runtime_state: str,
    ) -> tuple[ModuleStatus, ...]:
        """Convert runtime health reports into dashboard-friendly statuses."""

        statuses: list[ModuleStatus] = []
        for name, report in reports.items():
            description = str(report.details.get("module", name))
            if runtime_state != "running":
                status = "stopped"
                description = f"{description} is currently stopped"
            else:
                status = report.status
            statuses.append(
                ModuleStatus(
                    name=name,
                    status=status,
                    description=description,
                    details=dict(report.details),
                )
            )

        if not statuses:
            statuses.append(
                ModuleStatus(
                    name="dashboard",
                    status="running" if runtime_state == "running" else "stopped",
                    description="Dashboard service",
                    details={"module": "Dashboard"},
                )
            )

        return tuple(sorted(statuses, key=lambda item: item.name))

    @staticmethod
    def _coerce_reports(payload: Mapping[str, Any]) -> dict[str, HealthReport]:
        """Normalize health payloads into ``HealthReport`` instances."""

        reports: dict[str, HealthReport] = {}
        for name, value in payload.items():
            if isinstance(value, HealthReport):
                reports[name] = value
            else:
                status = getattr(value, "status", "unknown")
                details = dict(getattr(value, "details", {}))
                reports[name] = HealthReport(name=name, status=status, details=details)
        return reports

    @staticmethod
    def _coerce_insights(payload: Mapping[str, Any]) -> RuntimeInsights:
        """Normalize runtime insight payloads into ``RuntimeInsights``."""

        return RuntimeInsights(
            loaded_skills=int(payload.get("loaded_skills", 0)),
            loaded_plugins=int(payload.get("loaded_plugins", 0)),
            stored_memories=int(payload.get("stored_memories", 0)),
            queued_actions=int(payload.get("queued_actions", 0)),
        )


@dataclass(slots=True)
class DashboardServices:
    """Container for the concrete dashboard services registered at runtime."""

    dashboard: DashboardModule
    log_buffer: DashboardLogBuffer
    logger: DashboardLogger


def build_dashboard_services(
    *,
    narvis_version: str,
    logger: DashboardLogger,
    runtime_actions: DashboardRuntimeActions,
    health_provider: Callable[[], Mapping[str, HealthReport]],
    log_buffer: DashboardLogBuffer,
    metrics_provider: MetricsProvider | None = None,
    insights_provider: Callable[[], Mapping[str, Any]] | None = None,
) -> DashboardServices:
    """Build the dashboard service bundle using constructor injection."""

    dashboard = DashboardModule(
        narvis_version=narvis_version,
        logger=logger,
        runtime_actions=runtime_actions,
        health_provider=health_provider,
        log_buffer=log_buffer,
        metrics_provider=metrics_provider,
        insights_provider=insights_provider,
    )
    logger.log(LogLevel.INFO, "Built dashboard services")
    return DashboardServices(dashboard=dashboard, log_buffer=log_buffer, logger=logger)


def register_dashboard_services(container: DependencyRegistrar, services: DashboardServices) -> DashboardServices:
    """Register the dashboard services in a dependency-injection container."""

    container.register_instance("dashboard", services.dashboard)
    container.register_instance("dashboard_log_buffer", services.log_buffer)
    container.register_instance("dashboard_logger", services.logger)
    return services


class DashboardRuntimeHook:
    """Runtime hook that registers dashboard services and emits a ready event."""

    def __init__(self, services: DashboardServices) -> None:
        self.services = services

    def load(
        self,
        container: DependencyRegistrar,
        event_bus: EventPublisher | None = None,
        logger: Any | None = None,
    ) -> None:
        """Register dashboard services and publish a readiness event."""

        register_dashboard_services(container, self.services)
        resolved_logger = logger or self.services.logger
        if event_bus is not None:
            try:
                from Core.system import SystemEvent

                event_bus.publish(SystemEvent(name="dashboard.services.registered", payload={"module": "Dashboard"}))
            except Exception:
                resolved_logger.log(LogLevel.WARNING, "Unable to publish dashboard registration event")
        resolved_logger.log(LogLevel.INFO, "Dashboard runtime hook completed")


__all__ = [
    "DashboardLogBuffer",
    "DashboardLogger",
    "DashboardModule",
    "DashboardRuntimeHook",
    "DashboardServices",
    "DashboardStdlibLogHandler",
    "attach_dashboard_log_handler",
    "build_dashboard_services",
    "register_dashboard_services",
]
