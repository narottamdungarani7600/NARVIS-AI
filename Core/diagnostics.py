"""Passive, immutable runtime diagnostics and health reporting.

Diagnostics in this module consume registration and lifecycle metadata only.
They never resolve services, probe dependencies, call providers, perform I/O,
or execute runtime capabilities.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Protocol

from .capabilities import (
    RuntimeCapabilityManifest,
    RuntimeCapabilityManifestService,
    RuntimeCapabilitySource,
)
from .dependency_graph import (
    RuntimeDependencyGraph,
    RuntimeDependencyGraphSnapshot,
    RuntimeDependencyValidationReport,
    RuntimeFeatureCompatibilityReport,
    RuntimeFeatureRelationshipSummary,
)
from .features import RuntimeFeatureRegistry, RuntimeFeatureRegistrySnapshot
from .logger import LogLevel, Logger, NullLogger
from .observability import (
    RuntimeObservabilityReport,
    RuntimeSnapshot,
    RuntimeSnapshotEngine,
    RuntimeSnapshotSource,
)
from .service_registry import (
    RuntimeCompatibilityStatus,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeServiceRegistry,
    RuntimeServiceRegistrySnapshot,
)
from .runtime_state import (
    RuntimeDependencyImpactSummary,
    RuntimeReadinessSummary,
    RuntimeStateCompatibilitySummary,
    RuntimeStateEngine,
    RuntimeStateHealthSummary,
    RuntimeStateSnapshot,
    RuntimeStateSource,
)
from .system import BaseSystemComponent, ComponentState, SystemEvent

RUNTIME_DIAGNOSTICS_STARTED_EVENT = "runtime.diagnostics.started"
RUNTIME_DIAGNOSTICS_STOPPED_EVENT = "runtime.diagnostics.stopped"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def _text(value: object, name: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise ValueError(
            f"{name} must be normalized non-empty text of at most {maximum} characters"
        )
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of identifiers")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    for value in result:
        _text(value, name, maximum=128)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("metadata keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(slots=True, frozen=True)
class RuntimeBuildMetadata:
    """Immutable product checkpoint metadata supplied by composition."""

    version: str
    milestone: int
    sprint: int
    build_id: str
    environment: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.version, "version", maximum=64)
        _text(self.build_id, "build_id", maximum=128)
        _text(self.environment, "environment", maximum=128)
        for name in ("milestone", "sprint"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.attributes, Mapping):
            raise TypeError("attributes must be a mapping")
        object.__setattr__(self, "attributes", _freeze(self.attributes))


@dataclass(slots=True, frozen=True)
class RuntimeLifecycleMetadata:
    """Immutable application and diagnostics lifecycle facts."""

    state: RuntimeLifecycleState
    started: bool
    bootstrapped: bool
    shutting_down: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeLifecycleState):
            raise TypeError("state must be a RuntimeLifecycleState")
        for name in ("started", "bootstrapped", "shutting_down"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")


@dataclass(slots=True, frozen=True)
class RuntimeCompatibilityMetadata:
    """Immutable compatibility facts derived from service names only."""

    status: RuntimeCompatibilityStatus
    required_services: tuple[str, ...]
    registered_services: tuple[str, ...]
    missing_services: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeCompatibilityStatus):
            raise TypeError("status must be a RuntimeCompatibilityStatus")
        required = _identifiers(self.required_services, "required_services")
        registered = _identifiers(self.registered_services, "registered_services")
        missing = _identifiers(self.missing_services, "missing_services")
        if tuple(sorted(required)) != required:
            raise ValueError("required_services must be sorted")
        if tuple(sorted(registered)) != registered:
            raise ValueError("registered_services must be sorted")
        if tuple(sorted(missing)) != missing:
            raise ValueError("missing_services must be sorted")
        if not set(missing).issubset(required):
            raise ValueError("missing_services must be a subset of required_services")
        if set(required) - set(registered) != set(missing):
            raise ValueError("missing_services must match registration metadata")
        if self.status is RuntimeCompatibilityStatus.COMPATIBLE and missing:
            raise ValueError("compatible metadata cannot report missing services")
        object.__setattr__(self, "required_services", required)
        object.__setattr__(self, "registered_services", registered)
        object.__setattr__(self, "missing_services", missing)


@dataclass(slots=True, frozen=True)
class RuntimeHealthContext:
    """Metadata-only inputs used by the deterministic health calculator."""

    lifecycle_state: RuntimeLifecycleState
    ai_manager_registered: bool
    conversation_runtime_state: RuntimeHealthStatus
    event_bus_available: bool
    logger_available: bool
    compatibility_status: RuntimeCompatibilityStatus

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        if not isinstance(self.conversation_runtime_state, RuntimeHealthStatus):
            raise TypeError("conversation_runtime_state must be a RuntimeHealthStatus")
        if not isinstance(self.compatibility_status, RuntimeCompatibilityStatus):
            raise TypeError("compatibility_status must be a RuntimeCompatibilityStatus")
        for name in (
            "ai_manager_registered",
            "event_bus_available",
            "logger_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")


@dataclass(slots=True, frozen=True)
class RuntimeHealthReport:
    """Immutable result of metadata-only runtime health calculation."""

    status: RuntimeHealthStatus
    issues: tuple[str, ...] = ()
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeHealthStatus):
            raise TypeError("status must be a RuntimeHealthStatus")
        issues = _identifiers(self.issues, "issues")
        if self.status is RuntimeHealthStatus.HEALTHY and issues:
            raise ValueError("healthy reports cannot contain issues")
        if self.calculated_from_metadata is not True:
            raise ValueError("runtime health must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("runtime health cannot use active probes")
        object.__setattr__(self, "issues", issues)


class RuntimeHealthCalculator:
    """Calculate health deterministically from an immutable metadata context."""

    @staticmethod
    def calculate(context: RuntimeHealthContext) -> RuntimeHealthReport:
        """Return status and ordered issue codes without active inspection."""

        if not isinstance(context, RuntimeHealthContext):
            raise TypeError("context must be a RuntimeHealthContext")
        terminal = {
            RuntimeLifecycleState.INITIALIZING: (
                RuntimeHealthStatus.INITIALIZING,
                ("runtime_initializing",),
            ),
            RuntimeLifecycleState.STOPPED: (
                RuntimeHealthStatus.STOPPED,
                ("runtime_stopped",),
            ),
            RuntimeLifecycleState.FAILED: (
                RuntimeHealthStatus.FAILED,
                ("runtime_failed",),
            ),
            RuntimeLifecycleState.UNKNOWN: (
                RuntimeHealthStatus.UNKNOWN,
                ("runtime_state_unknown",),
            ),
        }
        if context.lifecycle_state in terminal:
            status, issues = terminal[context.lifecycle_state]
            return RuntimeHealthReport(status=status, issues=issues)

        issues: list[str] = []
        if not context.ai_manager_registered:
            issues.append("ai_manager_unregistered")
        if context.conversation_runtime_state is not RuntimeHealthStatus.HEALTHY:
            issues.append("conversation_runtime_unavailable")
        if not context.event_bus_available:
            issues.append("event_bus_unavailable")
        if not context.logger_available:
            issues.append("logger_unavailable")
        if context.compatibility_status is not RuntimeCompatibilityStatus.COMPATIBLE:
            issues.append(f"compatibility_{context.compatibility_status.value}")
        return RuntimeHealthReport(
            status=(
                RuntimeHealthStatus.DEGRADED
                if issues
                else RuntimeHealthStatus.HEALTHY
            ),
            issues=tuple(issues),
        )


@dataclass(slots=True, frozen=True)
class RuntimeDiagnosticsSummary:
    """Compact deterministic diagnostics summary for callers and tests."""

    status: RuntimeHealthStatus
    service_count: int
    passed_checks: int
    total_checks: int
    issues: tuple[str, ...]
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeHealthStatus):
            raise TypeError("status must be a RuntimeHealthStatus")
        for name in ("service_count", "passed_checks", "total_checks"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.passed_checks > self.total_checks:
            raise ValueError("passed_checks cannot exceed total_checks")
        object.__setattr__(self, "issues", _identifiers(self.issues, "issues"))
        _text(self.message, "message", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeDiagnosticsSnapshot:
    """Complete immutable snapshot of passive NARVIS runtime metadata."""

    startup_timestamp: datetime | None
    uptime: timedelta
    registered_runtime_services: tuple[str, ...]
    ai_manager_registered: bool
    conversation_runtime_state: RuntimeHealthStatus
    event_bus_available: bool
    logger_available: bool
    lifecycle: RuntimeLifecycleMetadata
    compatibility: RuntimeCompatibilityMetadata
    runtime_version: str
    build_metadata: RuntimeBuildMetadata
    health: RuntimeHealthReport
    diagnostics_summary: RuntimeDiagnosticsSummary
    captured_at: datetime
    service_registry_snapshot: RuntimeServiceRegistrySnapshot | None = None
    capability_manifest: RuntimeCapabilityManifest | None = None
    feature_registry_snapshot: RuntimeFeatureRegistrySnapshot | None = None
    dependency_graph_snapshot: RuntimeDependencyGraphSnapshot | None = None
    relationship_summary: RuntimeFeatureRelationshipSummary | None = None
    validation_report: RuntimeDependencyValidationReport | None = None
    compatibility_report: RuntimeFeatureCompatibilityReport | None = None
    runtime_state_snapshot: RuntimeStateSnapshot | None = None
    readiness_summary: RuntimeReadinessSummary | None = None
    dependency_impact_summary: RuntimeDependencyImpactSummary | None = None
    state_compatibility_summary: RuntimeStateCompatibilitySummary | None = None
    state_health_summary: RuntimeStateHealthSummary | None = None
    runtime_snapshot: RuntimeSnapshot | None = None
    observability_report: RuntimeObservabilityReport | None = None

    def __post_init__(self) -> None:
        if self.startup_timestamp is not None:
            _time(self.startup_timestamp, "startup_timestamp")
        if not isinstance(self.uptime, timedelta) or self.uptime < timedelta(0):
            raise ValueError("uptime must be a non-negative timedelta")
        services = _identifiers(
            self.registered_runtime_services,
            "registered_runtime_services",
        )
        if tuple(sorted(services)) != services:
            raise ValueError("registered_runtime_services must be sorted")
        for name in (
            "ai_manager_registered",
            "event_bus_available",
            "logger_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if not isinstance(self.conversation_runtime_state, RuntimeHealthStatus):
            raise TypeError("conversation_runtime_state must be a RuntimeHealthStatus")
        if not isinstance(self.lifecycle, RuntimeLifecycleMetadata):
            raise TypeError("lifecycle must be RuntimeLifecycleMetadata")
        if not isinstance(self.compatibility, RuntimeCompatibilityMetadata):
            raise TypeError("compatibility must be RuntimeCompatibilityMetadata")
        if not isinstance(self.build_metadata, RuntimeBuildMetadata):
            raise TypeError("build_metadata must be RuntimeBuildMetadata")
        if not isinstance(self.health, RuntimeHealthReport):
            raise TypeError("health must be RuntimeHealthReport")
        if not isinstance(self.diagnostics_summary, RuntimeDiagnosticsSummary):
            raise TypeError("diagnostics_summary must be RuntimeDiagnosticsSummary")
        if (
            self.service_registry_snapshot is not None
            and not isinstance(
                self.service_registry_snapshot,
                RuntimeServiceRegistrySnapshot,
            )
        ):
            raise TypeError(
                "service_registry_snapshot must be a RuntimeServiceRegistrySnapshot"
            )
        if (
            self.service_registry_snapshot is not None
            and self.service_registry_snapshot.diagnostics_timestamp
            != self.captured_at
        ):
            raise ValueError(
                "service registry and diagnostics timestamps must match"
            )
        if (
            self.capability_manifest is not None
            and not isinstance(self.capability_manifest, RuntimeCapabilityManifest)
        ):
            raise TypeError(
                "capability_manifest must be a RuntimeCapabilityManifest"
            )
        if (
            self.capability_manifest is not None
            and self.capability_manifest.diagnostics_timestamp != self.captured_at
        ):
            raise ValueError(
                "capability manifest and diagnostics timestamps must match"
            )
        if (
            self.feature_registry_snapshot is not None
            and not isinstance(
                self.feature_registry_snapshot,
                RuntimeFeatureRegistrySnapshot,
            )
        ):
            raise TypeError(
                "feature_registry_snapshot must be a RuntimeFeatureRegistrySnapshot"
            )
        if (
            self.feature_registry_snapshot is not None
            and self.feature_registry_snapshot.diagnostics_timestamp
            != self.captured_at
        ):
            raise ValueError(
                "feature registry and diagnostics timestamps must match"
            )
        graph_exports = (
            (
                "dependency_graph_snapshot",
                self.dependency_graph_snapshot,
                RuntimeDependencyGraphSnapshot,
            ),
            (
                "relationship_summary",
                self.relationship_summary,
                RuntimeFeatureRelationshipSummary,
            ),
            (
                "validation_report",
                self.validation_report,
                RuntimeDependencyValidationReport,
            ),
            (
                "compatibility_report",
                self.compatibility_report,
                RuntimeFeatureCompatibilityReport,
            ),
        )
        for name, value, expected_type in graph_exports:
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
            if (
                value is not None
                and value.diagnostics_timestamp != self.captured_at
            ):
                raise ValueError(f"{name} and diagnostics timestamps must match")
        if self.dependency_graph_snapshot is not None:
            expected_exports = (
                self.dependency_graph_snapshot.relationship_summary,
                self.dependency_graph_snapshot.validation_report,
                self.dependency_graph_snapshot.compatibility_report,
            )
            if (
                self.relationship_summary,
                self.validation_report,
                self.compatibility_report,
            ) != expected_exports:
                raise ValueError(
                    "diagnostics graph reports must match dependency graph snapshot"
                )
        state_exports = (
            ("runtime_state_snapshot", self.runtime_state_snapshot, RuntimeStateSnapshot),
            ("readiness_summary", self.readiness_summary, RuntimeReadinessSummary),
            (
                "dependency_impact_summary",
                self.dependency_impact_summary,
                RuntimeDependencyImpactSummary,
            ),
            (
                "state_compatibility_summary",
                self.state_compatibility_summary,
                RuntimeStateCompatibilitySummary,
            ),
            (
                "state_health_summary",
                self.state_health_summary,
                RuntimeStateHealthSummary,
            ),
        )
        for name, value, expected_type in state_exports:
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
        if self.runtime_state_snapshot is not None:
            state_snapshot = self.runtime_state_snapshot
            if state_snapshot.diagnostics_timestamp != self.captured_at:
                raise ValueError(
                    "runtime state and diagnostics timestamps must match"
                )
            if (
                state_snapshot.service_registry_snapshot,
                state_snapshot.capability_manifest,
                state_snapshot.feature_registry_snapshot,
                state_snapshot.dependency_graph_snapshot,
            ) != (
                self.service_registry_snapshot,
                self.capability_manifest,
                self.feature_registry_snapshot,
                self.dependency_graph_snapshot,
            ):
                raise ValueError(
                    "runtime state inputs must match diagnostics snapshot exports"
                )
            expected_state_exports = (
                state_snapshot.readiness_summary,
                state_snapshot.dependency_impact_summary,
                state_snapshot.compatibility_summary,
                state_snapshot.health_summary,
            )
            if (
                self.readiness_summary,
                self.dependency_impact_summary,
                self.state_compatibility_summary,
                self.state_health_summary,
            ) != expected_state_exports:
                raise ValueError(
                    "diagnostics state reports must match runtime state snapshot"
                )
        if self.runtime_snapshot is not None and not isinstance(
            self.runtime_snapshot,
            RuntimeSnapshot,
        ):
            raise TypeError("runtime_snapshot must be a RuntimeSnapshot")
        if self.observability_report is not None and not isinstance(
            self.observability_report,
            RuntimeObservabilityReport,
        ):
            raise TypeError(
                "observability_report must be a RuntimeObservabilityReport"
            )
        if self.runtime_snapshot is not None:
            runtime_snapshot = self.runtime_snapshot
            if runtime_snapshot.captured_at != self.captured_at:
                raise ValueError(
                    "runtime snapshot and diagnostics timestamps must match"
                )
            if (
                runtime_snapshot.service_snapshot,
                runtime_snapshot.capability_snapshot,
                runtime_snapshot.feature_snapshot,
                runtime_snapshot.dependency_snapshot,
                runtime_snapshot.state_snapshot,
            ) != (
                self.service_registry_snapshot,
                self.capability_manifest,
                self.feature_registry_snapshot,
                self.dependency_graph_snapshot,
                self.runtime_state_snapshot,
            ):
                raise ValueError(
                    "runtime snapshot inputs must match diagnostics exports"
                )
            if self.observability_report != runtime_snapshot.observability_report:
                raise ValueError(
                    "observability report must match runtime snapshot"
                )
        _text(self.runtime_version, "runtime_version", maximum=64)
        if self.runtime_version != self.build_metadata.version:
            raise ValueError("runtime_version must match build metadata")
        captured = _time(self.captured_at, "captured_at")
        if self.startup_timestamp is not None and captured < self.startup_timestamp:
            raise ValueError("captured_at cannot precede startup_timestamp")
        object.__setattr__(self, "registered_runtime_services", services)


class RuntimeRegistrationReader(Protocol):
    """Read-only dependency registration metadata used by diagnostics."""

    def is_registered(self, name: str) -> bool:
        """Return whether a service name is registered."""

    def registered_services(self) -> tuple[str, ...]:
        """Return service names without resolving them."""


class RuntimeComponentRegistry(Protocol):
    """Read-only component state metadata used by diagnostics."""

    def get_component(self, name: str) -> object | None:
        """Return a lifecycle component by name."""


class RuntimeStateReader(Protocol):
    """Application lifecycle flags consumed without mutation."""

    started: bool
    bootstrapped: bool
    shutting_down: bool


class EventPublisher(Protocol):
    """Existing EventBus publication contract."""

    def publish(self, event: SystemEvent) -> None:
        """Publish one lifecycle event."""


class RuntimeDiagnosticsEvents:
    """Single publisher for diagnostics lifecycle events only."""

    def __init__(
        self,
        event_bus: EventPublisher | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        if event_bus is not None and not callable(getattr(event_bus, "publish", None)):
            raise TypeError("event_bus must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.runtime.diagnostics.events")

    def publish(self, event_name: str, **payload: object) -> None:
        """Publish non-sensitive lifecycle facts through the existing EventBus."""

        _text(event_name, "event_name", maximum=128)
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=dict(payload)))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish runtime diagnostics lifecycle event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


class RuntimeDiagnostics:
    """Create passive runtime snapshots from injected metadata contracts."""

    _REQUIRED_COMPATIBILITY_SERVICES = tuple(
        sorted(
            (
                "ai_manager",
                "ai_provider",
                "ai_runtime_adapter",
                "brain_engine",
                "brain_provider",
                "conversation_manager",
            )
        )
    )
    _TOTAL_HEALTH_CHECKS = 5

    def __init__(
        self,
        service_registry: RuntimeRegistrationReader,
        component_registry: RuntimeComponentRegistry,
        runtime_state: RuntimeStateReader,
        build_metadata: RuntimeBuildMetadata,
        *,
        runtime_service_registry: RuntimeServiceRegistry | None = None,
        capability_manifest_service: RuntimeCapabilityManifestService | None = None,
        runtime_feature_registry: RuntimeFeatureRegistry | None = None,
        runtime_dependency_graph: RuntimeDependencyGraph | None = None,
        runtime_state_engine: RuntimeStateEngine | None = None,
        runtime_snapshot_engine: RuntimeSnapshotEngine | None = None,
        event_bus: object | None = None,
        logger: Logger | None = None,
        events: RuntimeDiagnosticsEvents | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not all(
            callable(getattr(service_registry, method, None))
            for method in ("is_registered", "registered_services")
        ):
            raise TypeError("service_registry does not implement its read-only contract")
        if not callable(getattr(component_registry, "get_component", None)):
            raise TypeError("component_registry must provide get_component")
        if not all(
            hasattr(runtime_state, name)
            for name in ("started", "bootstrapped", "shutting_down")
        ):
            raise TypeError("runtime_state does not expose lifecycle flags")
        if not isinstance(build_metadata, RuntimeBuildMetadata):
            raise TypeError("build_metadata must be RuntimeBuildMetadata")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if events is not None and not callable(getattr(events, "publish", None)):
            raise TypeError("events must provide a publish method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if runtime_service_registry is not None and not callable(
            getattr(runtime_service_registry, "snapshot", None)
        ):
            raise TypeError("runtime_service_registry must provide snapshot")
        if capability_manifest_service is not None and not callable(
            getattr(capability_manifest_service, "snapshot", None)
        ):
            raise TypeError("capability_manifest_service must provide snapshot")
        if runtime_feature_registry is not None and not callable(
            getattr(runtime_feature_registry, "snapshot", None)
        ):
            raise TypeError("runtime_feature_registry must provide snapshot")
        if runtime_dependency_graph is not None and not callable(
            getattr(runtime_dependency_graph, "snapshot", None)
        ):
            raise TypeError("runtime_dependency_graph must provide snapshot")
        if runtime_state_engine is not None and not callable(
            getattr(runtime_state_engine, "snapshot", None)
        ):
            raise TypeError("runtime_state_engine must provide snapshot")
        if runtime_snapshot_engine is not None and not callable(
            getattr(runtime_snapshot_engine, "snapshot", None)
        ):
            raise TypeError("runtime_snapshot_engine must provide snapshot")
        self._service_registry = service_registry
        self._runtime_service_registry = runtime_service_registry
        self._capability_manifest_service = capability_manifest_service
        self._runtime_feature_registry = runtime_feature_registry
        self._runtime_dependency_graph = runtime_dependency_graph
        self._runtime_state_engine = runtime_state_engine
        self._runtime_snapshot_engine = runtime_snapshot_engine
        self._component_registry = component_registry
        self._runtime_state = runtime_state
        self._build_metadata = build_metadata
        self._event_bus = event_bus
        self._observed_logger = logger
        self._logger = logger or NullLogger("narvis.runtime.diagnostics")
        self._events = events or RuntimeDiagnosticsEvents(
            event_bus if callable(getattr(event_bus, "publish", None)) else None,
            logger=self._logger,
        )
        self._clock = clock
        self._state = RuntimeLifecycleState.INITIALIZING
        self._startup_timestamp: datetime | None = None
        self._stopped_at: datetime | None = None

    @property
    def lifecycle_state(self) -> RuntimeLifecycleState:
        """Return the diagnostics component's retained lifecycle state."""

        return self._state

    @property
    def startup_timestamp(self) -> datetime | None:
        """Return the most recent diagnostics lifecycle startup timestamp."""

        return self._startup_timestamp

    def start(self) -> None:
        """Record lifecycle startup metadata without inspecting dependencies."""

        if self._state is RuntimeLifecycleState.RUNNING:
            return
        started_at = self._now()
        self._startup_timestamp = started_at
        self._stopped_at = None
        self._state = RuntimeLifecycleState.RUNNING
        self._events.publish(
            RUNTIME_DIAGNOSTICS_STARTED_EVENT,
            status=RuntimeLifecycleState.RUNNING.value,
            startup_timestamp=started_at.isoformat(),
            service_registry_registered=self._service_registry.is_registered(
                "runtime_service_registry"
            ),
            capability_manifest_registered=self._service_registry.is_registered(
                "runtime_capability_manifest"
            ),
            feature_registry_registered=self._service_registry.is_registered(
                "runtime_feature_registry"
            ),
            dependency_graph_registered=self._service_registry.is_registered(
                "runtime_dependency_graph"
            ),
            state_engine_registered=self._service_registry.is_registered(
                "runtime_state_engine"
            ),
            snapshot_engine_registered=self._service_registry.is_registered(
                "runtime_snapshot_engine"
            ),
        )
        self._log(LogLevel.INFO, "Runtime diagnostics started")

    def stop(self) -> None:
        """Record lifecycle shutdown metadata without touching runtime services."""

        if self._state is RuntimeLifecycleState.STOPPED:
            return
        stopped_at = self._now()
        if (
            self._startup_timestamp is not None
            and stopped_at < self._startup_timestamp
        ):
            raise ValueError("diagnostics stop time cannot precede startup")
        self._stopped_at = stopped_at
        self._state = RuntimeLifecycleState.STOPPED
        uptime = self._uptime(stopped_at)
        self._events.publish(
            RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
            status=RuntimeLifecycleState.STOPPED.value,
            uptime_seconds=uptime.total_seconds(),
            service_registry_registered=self._service_registry.is_registered(
                "runtime_service_registry"
            ),
            capability_manifest_registered=self._service_registry.is_registered(
                "runtime_capability_manifest"
            ),
            feature_registry_registered=self._service_registry.is_registered(
                "runtime_feature_registry"
            ),
            dependency_graph_registered=self._service_registry.is_registered(
                "runtime_dependency_graph"
            ),
            state_engine_registered=self._service_registry.is_registered(
                "runtime_state_engine"
            ),
            snapshot_engine_registered=self._service_registry.is_registered(
                "runtime_snapshot_engine"
            ),
        )
        self._log(LogLevel.INFO, "Runtime diagnostics stopped")

    def snapshot(self, *, at: datetime | None = None) -> RuntimeDiagnosticsSnapshot:
        """Return one immutable snapshot using passive registration metadata only."""

        captured_at = self._at(at)
        services = tuple(sorted(self._service_registry.registered_services()))
        ai_manager_registered = self._service_registry.is_registered("ai_manager")
        lifecycle = self._lifecycle_metadata()
        conversation_state = self._conversation_state(lifecycle.state)
        compatibility = self._compatibility(services)
        service_registry_snapshot = (
            self._runtime_service_registry.snapshot(
                lifecycle_state=lifecycle.state,
                runtime_compatibility_status=compatibility.status,
                diagnostics_timestamp=captured_at,
            )
            if self._runtime_service_registry is not None
            else None
        )
        event_bus_available = all(
            callable(getattr(self._event_bus, method, None))
            for method in ("publish", "subscribe")
        )
        logger_available = callable(getattr(self._observed_logger, "log", None))
        health_context = RuntimeHealthContext(
            lifecycle_state=lifecycle.state,
            ai_manager_registered=ai_manager_registered,
            conversation_runtime_state=conversation_state,
            event_bus_available=event_bus_available,
            logger_available=logger_available,
            compatibility_status=compatibility.status,
        )
        health = RuntimeHealthCalculator.calculate(health_context)
        passed_checks = sum(
            (
                ai_manager_registered,
                conversation_state is RuntimeHealthStatus.HEALTHY,
                event_bus_available,
                logger_available,
                compatibility.status is RuntimeCompatibilityStatus.COMPATIBLE,
            )
        )
        summary = RuntimeDiagnosticsSummary(
            status=health.status,
            service_count=len(services),
            passed_checks=passed_checks,
            total_checks=self._TOTAL_HEALTH_CHECKS,
            issues=health.issues,
            message=self._summary_message(health),
        )
        capability_manifest = (
            self._capability_manifest_service.snapshot(
                RuntimeCapabilitySource(
                    runtime_version=self._build_metadata.version,
                    build_version=self._build_metadata.build_id,
                    registered_runtime_services=services,
                    lifecycle_state=lifecycle.state,
                    diagnostics_health=health.status,
                    service_registry_health=(
                        service_registry_snapshot.health.status
                        if service_registry_snapshot is not None
                        else RuntimeHealthStatus.UNKNOWN
                    ),
                    event_bus_available=event_bus_available,
                    compatibility_mode=compatibility.status,
                    service_registry_snapshot=service_registry_snapshot,
                    diagnostics_timestamp=captured_at,
                    feature_registry_available=(
                        self._runtime_feature_registry is not None
                    ),
                    dependency_graph_available=(
                        self._runtime_dependency_graph is not None
                    ),
                    state_engine_available=(
                        self._runtime_state_engine is not None
                    ),
                    snapshot_engine_available=(
                        self._runtime_snapshot_engine is not None
                    ),
                )
            )
            if self._capability_manifest_service is not None
            else None
        )
        feature_registry_snapshot = None
        if self._runtime_feature_registry is not None:
            if (
                service_registry_snapshot is not None
                and capability_manifest is not None
            ):
                feature_registry_snapshot = self._runtime_feature_registry.snapshot(
                    service_registry_snapshot=service_registry_snapshot,
                    capability_manifest=capability_manifest,
                    diagnostics_timestamp=captured_at,
                )
            else:
                feature_registry_snapshot = self._runtime_feature_registry.snapshot(
                    diagnostics_timestamp=captured_at,
                )
        dependency_graph_snapshot = None
        if self._runtime_dependency_graph is not None:
            dependency_graph_snapshot = self._runtime_dependency_graph.snapshot(
                feature_registry_snapshot=feature_registry_snapshot,
                diagnostics_timestamp=captured_at,
            )
        runtime_state_snapshot = None
        if self._runtime_state_engine is not None:
            runtime_state_snapshot = self._runtime_state_engine.snapshot(
                RuntimeStateSource(
                    lifecycle_state=lifecycle.state,
                    diagnostics_health=health.status,
                    diagnostics_issues=tuple(sorted(health.issues)),
                    diagnostics_timestamp=captured_at,
                    service_registry_snapshot=service_registry_snapshot,
                    capability_manifest=capability_manifest,
                    feature_registry_snapshot=feature_registry_snapshot,
                    dependency_graph_snapshot=dependency_graph_snapshot,
                )
            )
        runtime_snapshot = None
        if self._runtime_snapshot_engine is not None:
            runtime_snapshot = self._runtime_snapshot_engine.snapshot(
                RuntimeSnapshotSource(
                    runtime_version=self._build_metadata.version,
                    build_version=self._build_metadata.build_id,
                    lifecycle_state=lifecycle.state,
                    diagnostics_health=health.status,
                    diagnostics_issues=tuple(sorted(health.issues)),
                    registered_runtime_services=services,
                    compatibility_status=compatibility.status,
                    ai_manager_registered=ai_manager_registered,
                    conversation_runtime_state=conversation_state,
                    event_bus_available=event_bus_available,
                    logger_available=logger_available,
                    passed_diagnostics_checks=passed_checks,
                    total_diagnostics_checks=self._TOTAL_HEALTH_CHECKS,
                    diagnostics_summary=summary.message,
                    startup_timestamp=self._startup_timestamp,
                    uptime_seconds=self._uptime(captured_at).total_seconds(),
                    captured_at=captured_at,
                    service_registry_snapshot=service_registry_snapshot,
                    capability_manifest=capability_manifest,
                    feature_registry_snapshot=feature_registry_snapshot,
                    dependency_graph_snapshot=dependency_graph_snapshot,
                    runtime_state_snapshot=runtime_state_snapshot,
                    metadata={
                        "environment": self._build_metadata.environment,
                        "milestone": str(self._build_metadata.milestone),
                        "sprint": str(self._build_metadata.sprint),
                    },
                )
            )
        return RuntimeDiagnosticsSnapshot(
            startup_timestamp=self._startup_timestamp,
            uptime=self._uptime(captured_at),
            registered_runtime_services=services,
            ai_manager_registered=ai_manager_registered,
            conversation_runtime_state=conversation_state,
            event_bus_available=event_bus_available,
            logger_available=logger_available,
            lifecycle=lifecycle,
            compatibility=compatibility,
            runtime_version=self._build_metadata.version,
            build_metadata=self._build_metadata,
            health=health,
            diagnostics_summary=summary,
            captured_at=captured_at,
            service_registry_snapshot=service_registry_snapshot,
            capability_manifest=capability_manifest,
            feature_registry_snapshot=feature_registry_snapshot,
            dependency_graph_snapshot=dependency_graph_snapshot,
            relationship_summary=(
                dependency_graph_snapshot.relationship_summary
                if dependency_graph_snapshot is not None
                else None
            ),
            validation_report=(
                dependency_graph_snapshot.validation_report
                if dependency_graph_snapshot is not None
                else None
            ),
            compatibility_report=(
                dependency_graph_snapshot.compatibility_report
                if dependency_graph_snapshot is not None
                else None
            ),
            runtime_state_snapshot=runtime_state_snapshot,
            readiness_summary=(
                runtime_state_snapshot.readiness_summary
                if runtime_state_snapshot is not None
                else None
            ),
            dependency_impact_summary=(
                runtime_state_snapshot.dependency_impact_summary
                if runtime_state_snapshot is not None
                else None
            ),
            state_compatibility_summary=(
                runtime_state_snapshot.compatibility_summary
                if runtime_state_snapshot is not None
                else None
            ),
            state_health_summary=(
                runtime_state_snapshot.health_summary
                if runtime_state_snapshot is not None
                else None
            ),
            runtime_snapshot=runtime_snapshot,
            observability_report=(
                runtime_snapshot.observability_report
                if runtime_snapshot is not None
                else None
            ),
        )

    def health(self, *, at: datetime | None = None) -> RuntimeHealthReport:
        """Return the typed health portion of a passive diagnostics snapshot."""

        return self.snapshot(at=at).health

    def _lifecycle_metadata(self) -> RuntimeLifecycleMetadata:
        started = self._flag("started")
        bootstrapped = self._flag("bootstrapped")
        shutting_down = self._flag("shutting_down")
        state = self._state
        if state is RuntimeLifecycleState.RUNNING and not started:
            state = RuntimeLifecycleState.INITIALIZING
        return RuntimeLifecycleMetadata(
            state=state,
            started=started,
            bootstrapped=bootstrapped,
            shutting_down=shutting_down,
        )

    def _conversation_state(
        self,
        lifecycle_state: RuntimeLifecycleState,
    ) -> RuntimeHealthStatus:
        if lifecycle_state is RuntimeLifecycleState.INITIALIZING:
            return RuntimeHealthStatus.INITIALIZING
        if lifecycle_state is RuntimeLifecycleState.STOPPED:
            return RuntimeHealthStatus.STOPPED
        if lifecycle_state is RuntimeLifecycleState.FAILED:
            return RuntimeHealthStatus.FAILED
        if lifecycle_state is RuntimeLifecycleState.UNKNOWN:
            return RuntimeHealthStatus.UNKNOWN
        conversation_registered = self._service_registry.is_registered(
            "conversation_manager"
        )
        adapter_registered = self._service_registry.is_registered(
            "ai_runtime_adapter"
        )
        component = self._component_registry.get_component("ai_runtime")
        component_state = getattr(component, "state", None)
        if (
            conversation_registered
            and adapter_registered
            and component_state is ComponentState.INITIALIZED
        ):
            return RuntimeHealthStatus.HEALTHY
        if conversation_registered or adapter_registered:
            return RuntimeHealthStatus.DEGRADED
        return RuntimeHealthStatus.UNKNOWN

    def _compatibility(
        self,
        registered_services: tuple[str, ...],
    ) -> RuntimeCompatibilityMetadata:
        required = self._REQUIRED_COMPATIBILITY_SERVICES
        registered = tuple(sorted(set(registered_services)))
        missing = tuple(sorted(set(required) - set(registered)))
        present = set(required) & set(registered)
        if not present:
            status = RuntimeCompatibilityStatus.UNKNOWN
        elif not missing:
            status = RuntimeCompatibilityStatus.COMPATIBLE
        elif {"ai_manager", "brain_engine"} & set(missing):
            status = RuntimeCompatibilityStatus.INCOMPATIBLE
        else:
            status = RuntimeCompatibilityStatus.DEGRADED
        return RuntimeCompatibilityMetadata(
            status=status,
            required_services=required,
            registered_services=registered,
            missing_services=missing,
        )

    def _uptime(self, captured_at: datetime) -> timedelta:
        if self._startup_timestamp is None:
            return timedelta(0)
        end = self._stopped_at or captured_at
        if end < self._startup_timestamp:
            raise ValueError("diagnostics timestamp cannot precede startup")
        return end - self._startup_timestamp

    def _at(self, value: datetime | None) -> datetime:
        captured = self._now() if value is None else _time(value, "at")
        if self._startup_timestamp is not None and captured < self._startup_timestamp:
            raise ValueError("at cannot precede diagnostics startup")
        if self._stopped_at is not None and captured < self._stopped_at:
            raise ValueError("at cannot precede diagnostics shutdown")
        return captured

    def _now(self) -> datetime:
        return _time(self._clock(), "clock result")

    def _flag(self, name: str) -> bool:
        value = getattr(self._runtime_state, name, False)
        return value if isinstance(value, bool) else False

    @staticmethod
    def _summary_message(health: RuntimeHealthReport) -> str:
        if health.status is RuntimeHealthStatus.HEALTHY:
            return "Runtime metadata reports all required diagnostics healthy."
        if health.issues:
            return (
                f"Runtime metadata reports {health.status.value}: "
                f"{', '.join(health.issues)}."
            )
        return f"Runtime metadata reports {health.status.value}."

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


class RuntimeDiagnosticsLifecycleAdapter(BaseSystemComponent):
    """Register passive diagnostics through the existing Core lifecycle."""

    def __init__(
        self,
        diagnostics: RuntimeDiagnostics,
        *,
        name: str = "runtime_diagnostics",
    ) -> None:
        if not all(
            callable(getattr(diagnostics, method, None))
            for method in ("start", "stop", "snapshot")
        ):
            raise TypeError("diagnostics does not implement its lifecycle contract")
        _text(name, "name", maximum=128)
        super().__init__(name)
        self._diagnostics = diagnostics

    @property
    def diagnostics(self) -> RuntimeDiagnostics:
        """Return the injected diagnostics service."""

        return self._diagnostics

    def _initialize(self, context: Any) -> None:
        self._diagnostics.start()

    def _shutdown(self) -> None:
        self._diagnostics.stop()


__all__ = [
    "RUNTIME_DIAGNOSTICS_STARTED_EVENT",
    "RUNTIME_DIAGNOSTICS_STOPPED_EVENT",
    "RuntimeBuildMetadata",
    "RuntimeCompatibilityMetadata",
    "RuntimeCompatibilityStatus",
    "RuntimeDiagnostics",
    "RuntimeDiagnosticsEvents",
    "RuntimeDiagnosticsLifecycleAdapter",
    "RuntimeDiagnosticsSnapshot",
    "RuntimeDiagnosticsSummary",
    "RuntimeHealthCalculator",
    "RuntimeHealthContext",
    "RuntimeHealthReport",
    "RuntimeHealthStatus",
    "RuntimeLifecycleMetadata",
    "RuntimeLifecycleState",
]
