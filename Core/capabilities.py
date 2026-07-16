"""Immutable runtime capability manifests and passive readiness reporting.

This module consumes immutable runtime metadata only. It never resolves
services, discovers external capabilities, probes the operating system or
network, invokes providers, or performs execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from .runtime_metadata import RUNTIME_CAPABILITY_MANIFEST_VERSION
from .runtime_config import RUNTIME_CONFIGURATION_VERSION
from .service_registry import (
    RuntimeCompatibilityStatus,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeServiceRegistrySnapshot,
)


class RuntimeReadinessLevel(str, Enum):
    """Deterministic readiness classifications for the current runtime."""

    NOT_READY = "not_ready"
    PARTIAL = "partial"
    READY = "ready"
    READINESS_UNKNOWN = "readiness_unknown"


class RuntimeExecutionMode(str, Enum):
    """Execution modes advertised without enabling runtime behavior."""

    DISABLED = "disabled"
    ARCHITECTURE_ONLY = "architecture_only"
    UNKNOWN = "unknown"


class RuntimeProviderMode(str, Enum):
    """Provider modes derived from registration metadata only."""

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


def _text(value: object, name: str, *, maximum: int = 512) -> str:
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


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
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


def _feature_flags(values: Mapping[str, bool]) -> Mapping[str, bool]:
    if not isinstance(values, Mapping):
        raise TypeError("feature_flags must be a mapping")
    normalized: dict[str, bool] = {}
    for name, enabled in sorted(values.items()):
        _text(name, "feature flag", maximum=128)
        if not isinstance(enabled, bool):
            raise TypeError("feature flag values must be bools")
        normalized[name] = enabled
    return MappingProxyType(normalized)


@dataclass(slots=True, frozen=True)
class RuntimeCapabilitySource:
    """One immutable set of diagnostics facts used to build a manifest."""

    runtime_version: str
    build_version: str
    registered_runtime_services: tuple[str, ...]
    lifecycle_state: RuntimeLifecycleState
    diagnostics_health: RuntimeHealthStatus
    service_registry_health: RuntimeHealthStatus
    event_bus_available: bool
    compatibility_mode: RuntimeCompatibilityStatus
    service_registry_snapshot: RuntimeServiceRegistrySnapshot | None
    diagnostics_timestamp: datetime
    feature_registry_available: bool = False
    dependency_graph_available: bool = False
    state_engine_available: bool = False
    snapshot_engine_available: bool = False
    metadata_catalog_available: bool = False
    configuration_registry_available: bool = False

    def __post_init__(self) -> None:
        _text(self.runtime_version, "runtime_version", maximum=64)
        _text(self.build_version, "build_version", maximum=128)
        services = _identifiers(
            self.registered_runtime_services,
            "registered_runtime_services",
        )
        if tuple(sorted(services)) != services:
            raise ValueError("registered_runtime_services must be sorted")
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        for name in ("diagnostics_health", "service_registry_health"):
            if not isinstance(getattr(self, name), RuntimeHealthStatus):
                raise TypeError(f"{name} must be a RuntimeHealthStatus")
        if not isinstance(self.event_bus_available, bool):
            raise TypeError("event_bus_available must be a bool")
        if not isinstance(self.feature_registry_available, bool):
            raise TypeError("feature_registry_available must be a bool")
        if not isinstance(self.dependency_graph_available, bool):
            raise TypeError("dependency_graph_available must be a bool")
        if not isinstance(self.state_engine_available, bool):
            raise TypeError("state_engine_available must be a bool")
        if not isinstance(self.snapshot_engine_available, bool):
            raise TypeError("snapshot_engine_available must be a bool")
        if not isinstance(self.metadata_catalog_available, bool):
            raise TypeError("metadata_catalog_available must be a bool")
        if not isinstance(self.configuration_registry_available, bool):
            raise TypeError("configuration_registry_available must be a bool")
        if not isinstance(self.compatibility_mode, RuntimeCompatibilityStatus):
            raise TypeError(
                "compatibility_mode must be a RuntimeCompatibilityStatus"
            )
        captured = _time(self.diagnostics_timestamp, "diagnostics_timestamp")
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
            and self.service_registry_snapshot.diagnostics_timestamp != captured
        ):
            raise ValueError("registry and capability source timestamps must match")
        object.__setattr__(self, "registered_runtime_services", services)


@dataclass(slots=True, frozen=True)
class RuntimeReadinessContext:
    """Immutable metadata-only inputs to readiness calculation."""

    lifecycle_state: RuntimeLifecycleState
    diagnostics_health: RuntimeHealthStatus
    service_registry_health: RuntimeHealthStatus
    lifecycle_support: bool
    conversation_support: bool
    ai_manager_available: bool
    runtime_service_registry_available: bool
    diagnostics_available: bool
    event_bus_available: bool
    compatibility_mode: RuntimeCompatibilityStatus
    execution_mode: RuntimeExecutionMode
    provider_mode: RuntimeProviderMode
    diagnostics_timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        for name in ("diagnostics_health", "service_registry_health"):
            if not isinstance(getattr(self, name), RuntimeHealthStatus):
                raise TypeError(f"{name} must be a RuntimeHealthStatus")
        for name in (
            "lifecycle_support",
            "conversation_support",
            "ai_manager_available",
            "runtime_service_registry_available",
            "diagnostics_available",
            "event_bus_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if not isinstance(self.compatibility_mode, RuntimeCompatibilityStatus):
            raise TypeError(
                "compatibility_mode must be a RuntimeCompatibilityStatus"
            )
        if not isinstance(self.execution_mode, RuntimeExecutionMode):
            raise TypeError("execution_mode must be a RuntimeExecutionMode")
        if not isinstance(self.provider_mode, RuntimeProviderMode):
            raise TypeError("provider_mode must be a RuntimeProviderMode")
        _time(self.diagnostics_timestamp, "diagnostics_timestamp")


@dataclass(slots=True, frozen=True)
class RuntimeReadinessReport:
    """Immutable deterministic readiness result."""

    level: RuntimeReadinessLevel
    required_capabilities: tuple[str, ...]
    available_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    diagnostics_timestamp: datetime
    summary: str
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.level, RuntimeReadinessLevel):
            raise TypeError("level must be a RuntimeReadinessLevel")
        required = _identifiers(
            self.required_capabilities,
            "required_capabilities",
        )
        available = _identifiers(
            self.available_capabilities,
            "available_capabilities",
        )
        missing = _identifiers(self.missing_capabilities, "missing_capabilities")
        if not set(available).issubset(required) or not set(missing).issubset(required):
            raise ValueError("readiness capabilities must be required capabilities")
        if set(available) & set(missing):
            raise ValueError("available and missing capabilities cannot overlap")
        if set(available) | set(missing) != set(required):
            raise ValueError("readiness capabilities must partition requirements")
        _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        _text(self.summary, "summary", maximum=2000)
        if self.calculated_from_metadata is not True:
            raise ValueError("readiness must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("readiness cannot use active probes")
        object.__setattr__(self, "required_capabilities", required)
        object.__setattr__(self, "available_capabilities", available)
        object.__setattr__(self, "missing_capabilities", missing)


class RuntimeReadinessCalculator:
    """Calculate readiness using ordered immutable runtime facts only."""

    _REQUIREMENTS = (
        "lifecycle_support",
        "runtime_diagnostics",
        "runtime_service_registry",
        "event_bus",
        "conversation_runtime",
        "ai_manager",
        "runtime_compatibility",
        "diagnostics_health",
        "service_registry_health",
        "architecture_only_execution",
        "provider_execution_disabled",
    )

    @classmethod
    def calculate(cls, context: RuntimeReadinessContext) -> RuntimeReadinessReport:
        """Return one deterministic readiness report without active inspection."""

        if not isinstance(context, RuntimeReadinessContext):
            raise TypeError("context must be a RuntimeReadinessContext")
        checks = {
            "lifecycle_support": context.lifecycle_support,
            "runtime_diagnostics": context.diagnostics_available,
            "runtime_service_registry": context.runtime_service_registry_available,
            "event_bus": context.event_bus_available,
            "conversation_runtime": context.conversation_support,
            "ai_manager": context.ai_manager_available,
            "runtime_compatibility": (
                context.compatibility_mode
                is RuntimeCompatibilityStatus.COMPATIBLE
            ),
            "diagnostics_health": (
                context.diagnostics_health is RuntimeHealthStatus.HEALTHY
            ),
            "service_registry_health": (
                context.service_registry_health is RuntimeHealthStatus.HEALTHY
            ),
            "architecture_only_execution": (
                context.execution_mode is RuntimeExecutionMode.ARCHITECTURE_ONLY
            ),
            "provider_execution_disabled": (
                context.provider_mode is RuntimeProviderMode.DISABLED
            ),
        }
        available = tuple(name for name in cls._REQUIREMENTS if checks[name])
        missing = tuple(name for name in cls._REQUIREMENTS if not checks[name])
        if context.lifecycle_state is RuntimeLifecycleState.UNKNOWN:
            level = RuntimeReadinessLevel.READINESS_UNKNOWN
        elif context.lifecycle_state is not RuntimeLifecycleState.RUNNING:
            level = RuntimeReadinessLevel.NOT_READY
        elif not missing:
            level = RuntimeReadinessLevel.READY
        elif any(
            (
                context.lifecycle_support,
                context.diagnostics_available,
                context.runtime_service_registry_available,
                context.event_bus_available,
            )
        ):
            level = RuntimeReadinessLevel.PARTIAL
        else:
            level = RuntimeReadinessLevel.READINESS_UNKNOWN
        summary = (
            f"Runtime readiness metadata reports {level.value}: "
            f"{len(available)} of {len(cls._REQUIREMENTS)} requirements available"
            + (f"; missing {', '.join(missing)}." if missing else ".")
        )
        return RuntimeReadinessReport(
            level=level,
            required_capabilities=cls._REQUIREMENTS,
            available_capabilities=available,
            missing_capabilities=missing,
            diagnostics_timestamp=context.diagnostics_timestamp,
            summary=summary,
        )


@dataclass(slots=True, frozen=True)
class RuntimeCapabilitySummary:
    """Compact deterministic counts for one capability manifest."""

    readiness: RuntimeReadinessLevel
    supported_subsystem_count: int
    registered_service_count: int
    available_diagnostics_count: int
    enabled_feature_count: int
    disabled_feature_count: int
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.readiness, RuntimeReadinessLevel):
            raise TypeError("readiness must be a RuntimeReadinessLevel")
        for name in (
            "supported_subsystem_count",
            "registered_service_count",
            "available_diagnostics_count",
            "enabled_feature_count",
            "disabled_feature_count",
        ):
            _count(getattr(self, name), name)
        _text(self.message, "message", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeCapabilityManifest:
    """Immutable description of current NARVIS runtime capabilities."""

    runtime_version: str
    build_version: str
    supported_subsystems: tuple[str, ...]
    registered_runtime_services: tuple[str, ...]
    available_diagnostics: tuple[str, ...]
    lifecycle_support: bool
    conversation_support: bool
    ai_manager_available: bool
    runtime_service_registry_available: bool
    diagnostics_available: bool
    event_bus_available: bool
    compatibility_mode: RuntimeCompatibilityStatus
    execution_mode: RuntimeExecutionMode
    provider_mode: RuntimeProviderMode
    feature_flags: Mapping[str, bool]
    readiness: RuntimeReadinessReport
    capability_summary: RuntimeCapabilitySummary
    diagnostics_timestamp: datetime
    runtime_feature_registry_available: bool = False
    runtime_dependency_graph_available: bool = False
    runtime_state_engine_available: bool = False
    runtime_snapshot_engine_available: bool = False
    runtime_metadata_catalog_available: bool = False
    runtime_configuration_registry_available: bool = False

    def __post_init__(self) -> None:
        _text(self.runtime_version, "runtime_version", maximum=64)
        _text(self.build_version, "build_version", maximum=128)
        subsystems = _identifiers(self.supported_subsystems, "supported_subsystems")
        services = _identifiers(
            self.registered_runtime_services,
            "registered_runtime_services",
        )
        diagnostics = _identifiers(
            self.available_diagnostics,
            "available_diagnostics",
        )
        for name, values in (
            ("supported_subsystems", subsystems),
            ("registered_runtime_services", services),
            ("available_diagnostics", diagnostics),
        ):
            if tuple(sorted(values)) != values:
                raise ValueError(f"{name} must be sorted")
        for name in (
            "lifecycle_support",
            "conversation_support",
            "ai_manager_available",
            "runtime_service_registry_available",
            "diagnostics_available",
            "event_bus_available",
            "runtime_feature_registry_available",
            "runtime_dependency_graph_available",
            "runtime_state_engine_available",
            "runtime_snapshot_engine_available",
            "runtime_metadata_catalog_available",
            "runtime_configuration_registry_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if not isinstance(self.compatibility_mode, RuntimeCompatibilityStatus):
            raise TypeError(
                "compatibility_mode must be a RuntimeCompatibilityStatus"
            )
        if not isinstance(self.execution_mode, RuntimeExecutionMode):
            raise TypeError("execution_mode must be a RuntimeExecutionMode")
        if not isinstance(self.provider_mode, RuntimeProviderMode):
            raise TypeError("provider_mode must be a RuntimeProviderMode")
        if not isinstance(self.readiness, RuntimeReadinessReport):
            raise TypeError("readiness must be a RuntimeReadinessReport")
        if not isinstance(self.capability_summary, RuntimeCapabilitySummary):
            raise TypeError("capability_summary must be a RuntimeCapabilitySummary")
        if self.capability_summary.readiness is not self.readiness.level:
            raise ValueError("capability summary readiness must match report")
        captured = _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        if self.readiness.diagnostics_timestamp != captured:
            raise ValueError("manifest and readiness timestamps must match")
        flags = _feature_flags(self.feature_flags)
        if (
            self.capability_summary.supported_subsystem_count != len(subsystems)
            or self.capability_summary.registered_service_count != len(services)
            or self.capability_summary.available_diagnostics_count
            != len(diagnostics)
        ):
            raise ValueError("capability summary counts must match manifest metadata")
        if (
            self.capability_summary.enabled_feature_count
            != sum(flags.values())
            or self.capability_summary.disabled_feature_count
            != len(flags) - sum(flags.values())
        ):
            raise ValueError("capability summary feature counts must match flags")
        object.__setattr__(self, "supported_subsystems", subsystems)
        object.__setattr__(self, "registered_runtime_services", services)
        object.__setattr__(self, "available_diagnostics", diagnostics)
        object.__setattr__(self, "feature_flags", flags)


class RuntimeCapabilityManifestService:
    """Build manifests from one immutable diagnostics metadata source."""

    _SUBSYSTEM_ANCHORS = (
        ("ai", ("ai_manager",)),
        ("automation", ("automation_service",)),
        ("brain", ("brain_engine",)),
        ("computer", ("computer_services",)),
        ("conversation", ("conversation_manager", "ai_runtime_adapter")),
        ("core", ("coordinator", "event_bus", "lifecycle_manager")),
        ("dashboard", ("dashboard",)),
        ("diagnostics", ("runtime_diagnostics",)),
        ("evolution", ("evolution_service",)),
        ("internet", ("internet_service",)),
        ("memory", ("memory_service",)),
        ("runtime_configuration", ("runtime_configuration_registry",)),
        ("runtime_dependencies", ("runtime_dependency_graph",)),
        ("runtime_features", ("runtime_feature_registry",)),
        ("runtime_metadata", ("runtime_metadata_catalog",)),
        ("runtime_observability", ("runtime_snapshot_engine",)),
        ("runtime_services", ("runtime_service_registry",)),
        ("runtime_state", ("runtime_state_engine",)),
        ("skills", ("skill_registry",)),
        ("vision", ("vision_service",)),
        ("voice", ("voice_runtime_service",)),
    )

    def snapshot(self, source: RuntimeCapabilitySource) -> RuntimeCapabilityManifest:
        """Return a deterministic manifest without resolving runtime services."""

        if not isinstance(source, RuntimeCapabilitySource):
            raise TypeError("source must be a RuntimeCapabilitySource")
        registered = set(source.registered_runtime_services)
        lifecycle_support = {
            "coordinator",
            "lifecycle_manager",
        }.issubset(registered)
        conversation_support = {
            "conversation_manager",
            "ai_runtime_adapter",
        }.issubset(registered)
        ai_manager_available = "ai_manager" in registered
        registry_available = (
            "runtime_service_registry" in registered
            and source.service_registry_snapshot is not None
        )
        diagnostics_available = "runtime_diagnostics" in registered
        capability_manifest_available = "runtime_capability_manifest" in registered
        feature_registry_available = (
            source.feature_registry_available
            and "runtime_feature_registry" in registered
        )
        dependency_graph_available = (
            source.dependency_graph_available
            and "runtime_dependency_graph" in registered
        )
        state_engine_available = (
            source.state_engine_available and "runtime_state_engine" in registered
        )
        snapshot_engine_available = (
            source.snapshot_engine_available
            and "runtime_snapshot_engine" in registered
        )
        metadata_catalog_available = (
            source.metadata_catalog_available
            and "runtime_metadata_catalog" in registered
        )
        configuration_registry_available = (
            source.configuration_registry_available
            and "runtime_configuration_registry" in registered
        )
        execution_mode = (
            RuntimeExecutionMode.ARCHITECTURE_ONLY
            if ai_manager_available
            else RuntimeExecutionMode.DISABLED
        )
        provider_mode = (
            RuntimeProviderMode.DISABLED
            if {"ai_provider", "brain_provider"} & registered
            else RuntimeProviderMode.UNAVAILABLE
        )
        subsystems = tuple(
            name
            for name, anchors in self._SUBSYSTEM_ANCHORS
            if set(anchors).issubset(registered)
        )
        available_diagnostics = tuple(
            sorted(
                (
                    *(
                        ("compatibility", "lifecycle", "runtime_health")
                        if diagnostics_available
                        else ()
                    ),
                    *(
                        ("dependency_health", "service_registry")
                        if registry_available
                        else ()
                    ),
                    *(("feature_registry",) if feature_registry_available else ()),
                    *(
                        (
                            "dependency_graph",
                            "feature_compatibility",
                            "feature_relationships",
                            "feature_validation",
                        )
                        if dependency_graph_available
                        else ()
                    ),
                    *(
                        ("runtime_readiness", "runtime_state")
                        if state_engine_available
                        else ()
                    ),
                    *(
                        (
                            "runtime_observability",
                            "runtime_snapshot",
                            "snapshot_comparison",
                        )
                        if snapshot_engine_available
                        else ()
                    ),
                    *(
                        ("runtime_metadata", "runtime_version_catalog")
                        if metadata_catalog_available
                        else ()
                    ),
                    *(
                        (
                            "configuration_validation",
                            "runtime_configuration",
                        )
                        if configuration_registry_available
                        else ()
                    ),
                )
            )
        )
        feature_flags = {
            "active_probing": False,
            "ai_architecture": ai_manager_available,
            "ai_execution": False,
            "conversation_runtime": conversation_support,
            "diagnostics": diagnostics_available,
            "event_bus": source.event_bus_available,
            "lifecycle": lifecycle_support,
            "network_access": False,
            "provider_execution": False,
            "runtime_capability_manifest": capability_manifest_available,
            "runtime_configuration_registry": configuration_registry_available,
            "runtime_dependency_graph": dependency_graph_available,
            "runtime_feature_registry": feature_registry_available,
            "runtime_metadata_catalog": metadata_catalog_available,
            "runtime_service_registry": registry_available,
            "runtime_state_engine": state_engine_available,
            "runtime_snapshot_engine": snapshot_engine_available,
        }
        readiness = RuntimeReadinessCalculator.calculate(
            RuntimeReadinessContext(
                lifecycle_state=source.lifecycle_state,
                diagnostics_health=source.diagnostics_health,
                service_registry_health=source.service_registry_health,
                lifecycle_support=lifecycle_support,
                conversation_support=conversation_support,
                ai_manager_available=ai_manager_available,
                runtime_service_registry_available=registry_available,
                diagnostics_available=diagnostics_available,
                event_bus_available=source.event_bus_available,
                compatibility_mode=source.compatibility_mode,
                execution_mode=execution_mode,
                provider_mode=provider_mode,
                diagnostics_timestamp=source.diagnostics_timestamp,
            )
        )
        enabled_features = sum(feature_flags.values())
        summary = RuntimeCapabilitySummary(
            readiness=readiness.level,
            supported_subsystem_count=len(subsystems),
            registered_service_count=len(source.registered_runtime_services),
            available_diagnostics_count=len(available_diagnostics),
            enabled_feature_count=enabled_features,
            disabled_feature_count=len(feature_flags) - enabled_features,
            message=(
                f"Runtime capability metadata reports {readiness.level.value}: "
                f"{len(subsystems)} subsystems, "
                f"{len(source.registered_runtime_services)} services, "
                f"{len(available_diagnostics)} diagnostics, "
                f"{enabled_features} enabled feature flags."
            ),
        )
        return RuntimeCapabilityManifest(
            runtime_version=source.runtime_version,
            build_version=source.build_version,
            supported_subsystems=subsystems,
            registered_runtime_services=source.registered_runtime_services,
            available_diagnostics=available_diagnostics,
            lifecycle_support=lifecycle_support,
            conversation_support=conversation_support,
            ai_manager_available=ai_manager_available,
            runtime_service_registry_available=registry_available,
            diagnostics_available=diagnostics_available,
            event_bus_available=source.event_bus_available,
            compatibility_mode=source.compatibility_mode,
            execution_mode=execution_mode,
            provider_mode=provider_mode,
            feature_flags=feature_flags,
            readiness=readiness,
            capability_summary=summary,
            diagnostics_timestamp=source.diagnostics_timestamp,
            runtime_feature_registry_available=feature_registry_available,
            runtime_dependency_graph_available=dependency_graph_available,
            runtime_state_engine_available=state_engine_available,
            runtime_snapshot_engine_available=snapshot_engine_available,
            runtime_metadata_catalog_available=metadata_catalog_available,
            runtime_configuration_registry_available=(
                configuration_registry_available
            ),
        )


__all__ = [
    "RUNTIME_CAPABILITY_MANIFEST_VERSION",
    "RUNTIME_CONFIGURATION_VERSION",
    "RuntimeCapabilityManifest",
    "RuntimeCapabilityManifestService",
    "RuntimeCapabilitySource",
    "RuntimeCapabilitySummary",
    "RuntimeExecutionMode",
    "RuntimeProviderMode",
    "RuntimeReadinessCalculator",
    "RuntimeReadinessContext",
    "RuntimeReadinessLevel",
    "RuntimeReadinessReport",
]
