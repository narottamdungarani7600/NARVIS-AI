"""Immutable runtime observability snapshots and deterministic comparisons.

The snapshot engine consumes retained runtime metadata only.  It never resolves
services, invokes providers or AI models, probes the host, uses networking, or
enters Trusted Execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any

from .capabilities import RuntimeCapabilityManifest, RuntimeReadinessLevel
from .dependency_graph import (
    RuntimeDependencyGraphSnapshot,
    RuntimeFeatureCompatibilityStatus,
    RuntimeFeatureDependencyType,
    RuntimeFeatureValidationStatus,
)
from .features import (
    RuntimeFeatureAvailability,
    RuntimeFeatureCommercialVisibility,
    RuntimeFeatureRegistrySnapshot,
)
from .runtime_state import (
    RuntimeReadinessSummary,
    RuntimeStateHealthSummary,
    RuntimeStateReadiness,
    RuntimeStateSnapshot,
)
from .runtime_metadata import (
    RUNTIME_OBSERVABILITY_VERSION,
    RuntimeMetadataSnapshot,
)
from .runtime_config import RuntimeConfigurationSnapshot
from .service_registry import (
    RuntimeCompatibilityStatus,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeServiceRegistrySnapshot,
)


RUNTIME_SNAPSHOT_SCHEMA_VERSION = "1.0"
_SNAPSHOT_ID_PREFIX = "runtime-snapshot-"
_OMITTED_CONTENT_FIELDS = {
    "captured_at",
    "diagnostics_timestamp",
    "startup_timestamp",
    "uptime_seconds",
}


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


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of identifiers")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    for value in result:
        _text(value, name, maximum=128)
    if result != tuple(sorted(set(result))):
        raise ValueError(f"{name} must use unique deterministic ordering")
    return result


def _freeze_text_mapping(
    values: Mapping[str, str],
    name: str,
) -> Mapping[str, str]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    frozen: dict[str, str] = {}
    for key in sorted(values):
        _text(key, f"{name} key", maximum=128)
        frozen[key] = _text(values[key], f"{name} value", maximum=512)
    return MappingProxyType(frozen)


def _canonical(value: Any, *, omit_time: bool = False) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical(getattr(value, item.name), omit_time=omit_time)
            for item in fields(value)
            if not (
                omit_time
                and (
                    item.name in _OMITTED_CONTENT_FIELDS
                    or item.name.endswith("_timestamp")
                )
            )
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(value[key], omit_time=omit_time)
            for key in sorted(value, key=str)
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item, omit_time=omit_time) for item in value]
    raise TypeError(f"unsupported snapshot export value: {type(value).__name__}")


def _immutable_export(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if is_dataclass(value) and not isinstance(value, type):
        return MappingProxyType(
            {
                item.name: _immutable_export(getattr(value, item.name))
                for item in fields(value)
            }
        )
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _immutable_export(value[key])
                for key in sorted(value, key=str)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_immutable_export(item) for item in value)
    raise TypeError(f"unsupported snapshot export value: {type(value).__name__}")


def _digest(value: Any, *, omit_time: bool = False) -> str:
    payload = json.dumps(
        _canonical(value, omit_time=omit_time),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(slots=True, frozen=True)
class RuntimeSnapshotSource:
    """One immutable, same-timestamp source for observability capture."""

    runtime_version: str
    build_version: str
    lifecycle_state: RuntimeLifecycleState
    diagnostics_health: RuntimeHealthStatus
    diagnostics_issues: tuple[str, ...]
    registered_runtime_services: tuple[str, ...]
    compatibility_status: RuntimeCompatibilityStatus
    ai_manager_registered: bool
    conversation_runtime_state: RuntimeHealthStatus
    event_bus_available: bool
    logger_available: bool
    passed_diagnostics_checks: int
    total_diagnostics_checks: int
    diagnostics_summary: str
    startup_timestamp: datetime | None
    uptime_seconds: float
    captured_at: datetime
    service_registry_snapshot: RuntimeServiceRegistrySnapshot | None = None
    capability_manifest: RuntimeCapabilityManifest | None = None
    feature_registry_snapshot: RuntimeFeatureRegistrySnapshot | None = None
    dependency_graph_snapshot: RuntimeDependencyGraphSnapshot | None = None
    runtime_state_snapshot: RuntimeStateSnapshot | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    runtime_metadata_snapshot: RuntimeMetadataSnapshot | None = None
    runtime_configuration_snapshot: RuntimeConfigurationSnapshot | None = None

    def __post_init__(self) -> None:
        _text(self.runtime_version, "runtime_version", maximum=64)
        _text(self.build_version, "build_version", maximum=128)
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        for name in (
            "diagnostics_health",
            "conversation_runtime_state",
        ):
            if not isinstance(getattr(self, name), RuntimeHealthStatus):
                raise TypeError(f"{name} must be a RuntimeHealthStatus")
        if not isinstance(self.compatibility_status, RuntimeCompatibilityStatus):
            raise TypeError(
                "compatibility_status must be a RuntimeCompatibilityStatus"
            )
        issues = tuple(self.diagnostics_issues)
        for issue in issues:
            _text(issue, "diagnostics issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("diagnostics_issues must use deterministic ordering")
        services = _identifiers(
            self.registered_runtime_services,
            "registered_runtime_services",
        )
        for name in (
            "ai_manager_registered",
            "event_bus_available",
            "logger_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        for name in ("passed_diagnostics_checks", "total_diagnostics_checks"):
            _count(getattr(self, name), name)
        if self.passed_diagnostics_checks > self.total_diagnostics_checks:
            raise ValueError("passed diagnostics checks cannot exceed total checks")
        _text(self.diagnostics_summary, "diagnostics_summary", maximum=2000)
        if self.startup_timestamp is not None:
            _time(self.startup_timestamp, "startup_timestamp")
        _number(self.uptime_seconds, "uptime_seconds")
        captured = _time(self.captured_at, "captured_at")
        if self.startup_timestamp is not None and captured < self.startup_timestamp:
            raise ValueError("captured_at cannot precede startup_timestamp")
        snapshot_types = (
            (
                "service_registry_snapshot",
                self.service_registry_snapshot,
                RuntimeServiceRegistrySnapshot,
            ),
            ("capability_manifest", self.capability_manifest, RuntimeCapabilityManifest),
            (
                "feature_registry_snapshot",
                self.feature_registry_snapshot,
                RuntimeFeatureRegistrySnapshot,
            ),
            (
                "dependency_graph_snapshot",
                self.dependency_graph_snapshot,
                RuntimeDependencyGraphSnapshot,
            ),
            (
                "runtime_state_snapshot",
                self.runtime_state_snapshot,
                RuntimeStateSnapshot,
            ),
            (
                "runtime_metadata_snapshot",
                self.runtime_metadata_snapshot,
                RuntimeMetadataSnapshot,
            ),
            (
                "runtime_configuration_snapshot",
                self.runtime_configuration_snapshot,
                RuntimeConfigurationSnapshot,
            ),
        )
        for name, value, expected_type in snapshot_types:
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
            timestamp = getattr(value, "diagnostics_timestamp", None)
            if value is not None and timestamp is not None and timestamp != captured:
                raise ValueError(f"{name} must use captured_at")
        if (
            self.runtime_metadata_snapshot is not None
            and self.runtime_metadata_snapshot.captured_at is not None
            and self.runtime_metadata_snapshot.captured_at != captured
        ):
            raise ValueError("runtime_metadata_snapshot must use captured_at")
        if (
            self.runtime_configuration_snapshot is not None
            and self.runtime_configuration_snapshot.captured_at is not None
            and self.runtime_configuration_snapshot.captured_at != captured
        ):
            raise ValueError("runtime_configuration_snapshot must use captured_at")
        if self.service_registry_snapshot is not None:
            snapshot_services = tuple(
                item.service_name for item in self.service_registry_snapshot.services
            )
            if set(snapshot_services) != set(services):
                raise ValueError(
                    "service snapshot must contain registered_runtime_services"
                )
        if (
            self.dependency_graph_snapshot is not None
            and self.feature_registry_snapshot is not None
            and self.dependency_graph_snapshot.feature_registry_snapshot
            != self.feature_registry_snapshot
        ):
            raise ValueError("feature and dependency snapshots must match")
        if self.capability_manifest is not None and (
            self.capability_manifest.runtime_version != self.runtime_version
            or self.capability_manifest.build_version != self.build_version
        ):
            raise ValueError("capability manifest must match runtime build metadata")
        if self.runtime_state_snapshot is not None and (
            self.runtime_state_snapshot.service_registry_snapshot,
            self.runtime_state_snapshot.capability_manifest,
            self.runtime_state_snapshot.feature_registry_snapshot,
            self.runtime_state_snapshot.dependency_graph_snapshot,
            self.runtime_state_snapshot.runtime_metadata_snapshot,
            self.runtime_state_snapshot.runtime_configuration_snapshot,
        ) != (
            self.service_registry_snapshot,
            self.capability_manifest,
            self.feature_registry_snapshot,
            self.dependency_graph_snapshot,
            self.runtime_metadata_snapshot,
            self.runtime_configuration_snapshot,
        ):
            raise ValueError("runtime state inputs must match snapshot source inputs")
        object.__setattr__(self, "diagnostics_issues", issues)
        object.__setattr__(self, "registered_runtime_services", services)
        object.__setattr__(self, "uptime_seconds", float(self.uptime_seconds))
        object.__setattr__(
            self,
            "metadata",
            _freeze_text_mapping(self.metadata, "metadata"),
        )


@dataclass(slots=True, frozen=True)
class RuntimeDiagnosticsExport:
    """Cycle-free immutable diagnostics facts embedded in a runtime snapshot."""

    lifecycle_state: RuntimeLifecycleState
    health_status: RuntimeHealthStatus
    compatibility_status: RuntimeCompatibilityStatus
    registered_runtime_services: tuple[str, ...]
    ai_manager_registered: bool
    conversation_runtime_state: RuntimeHealthStatus
    event_bus_available: bool
    logger_available: bool
    passed_checks: int
    total_checks: int
    issues: tuple[str, ...]
    startup_timestamp: datetime | None
    uptime_seconds: float
    captured_at: datetime
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        for name in ("health_status", "conversation_runtime_state"):
            if not isinstance(getattr(self, name), RuntimeHealthStatus):
                raise TypeError(f"{name} must be a RuntimeHealthStatus")
        if not isinstance(self.compatibility_status, RuntimeCompatibilityStatus):
            raise TypeError(
                "compatibility_status must be a RuntimeCompatibilityStatus"
            )
        object.__setattr__(
            self,
            "registered_runtime_services",
            _identifiers(
                self.registered_runtime_services,
                "registered_runtime_services",
            ),
        )
        for name in (
            "ai_manager_registered",
            "event_bus_available",
            "logger_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        for name in ("passed_checks", "total_checks"):
            _count(getattr(self, name), name)
        if self.passed_checks > self.total_checks:
            raise ValueError("passed_checks cannot exceed total_checks")
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "diagnostics issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        if self.startup_timestamp is not None:
            _time(self.startup_timestamp, "startup_timestamp")
        _number(self.uptime_seconds, "uptime_seconds")
        captured = _time(self.captured_at, "captured_at")
        if self.startup_timestamp is not None and captured < self.startup_timestamp:
            raise ValueError("captured_at cannot precede startup_timestamp")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "uptime_seconds", float(self.uptime_seconds))


@dataclass(slots=True, frozen=True)
class RuntimeSnapshotMetadata:
    """Versioned identity and provenance for one runtime snapshot."""

    snapshot_id: str
    content_hash: str
    schema_version: str
    runtime_version: str
    build_version: str
    captured_at: datetime
    source_names: tuple[str, ...]
    attributes: Mapping[str, str]
    deterministic: bool = True
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        _text(self.snapshot_id, "snapshot_id", maximum=128)
        if not self.snapshot_id.startswith(_SNAPSHOT_ID_PREFIX):
            raise ValueError("snapshot_id must use the runtime snapshot prefix")
        identifier_hash = self.snapshot_id.removeprefix(_SNAPSHOT_ID_PREFIX)
        if len(identifier_hash) != 64 or any(
            character not in "0123456789abcdef" for character in identifier_hash
        ):
            raise ValueError("snapshot_id must contain a SHA-256 digest")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a SHA-256 digest")
        _text(self.schema_version, "schema_version", maximum=32)
        _text(self.runtime_version, "runtime_version", maximum=64)
        _text(self.build_version, "build_version", maximum=128)
        _time(self.captured_at, "captured_at")
        object.__setattr__(
            self,
            "source_names",
            _identifiers(self.source_names, "source_names"),
        )
        object.__setattr__(
            self,
            "attributes",
            _freeze_text_mapping(self.attributes, "attributes"),
        )
        if self.deterministic is not True:
            raise ValueError("runtime snapshots must be deterministic")
        if self.calculated_from_metadata is not True:
            raise ValueError("runtime snapshots must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("runtime snapshots cannot use active probes")


@dataclass(slots=True, frozen=True)
class RuntimeOverview:
    """Compact immutable overview of the observed runtime."""

    runtime_version: str
    build_version: str
    lifecycle_state: RuntimeLifecycleState
    readiness: RuntimeStateReadiness
    health: RuntimeHealthStatus
    registered_service_count: int
    registered_feature_count: int
    supported_subsystem_count: int
    dependency_edge_count: int
    captured_at: datetime
    summary: str

    def __post_init__(self) -> None:
        _text(self.runtime_version, "runtime_version", maximum=64)
        _text(self.build_version, "build_version", maximum=128)
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        if not isinstance(self.readiness, RuntimeStateReadiness):
            raise TypeError("readiness must be a RuntimeStateReadiness")
        if not isinstance(self.health, RuntimeHealthStatus):
            raise TypeError("health must be a RuntimeHealthStatus")
        for name in (
            "registered_service_count",
            "registered_feature_count",
            "supported_subsystem_count",
            "dependency_edge_count",
        ):
            _count(getattr(self, name), name)
        _time(self.captured_at, "captured_at")
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeRegisteredServicesSummary:
    """Deterministic summary of passive DI service registration metadata."""

    service_names: tuple[str, ...]
    total_services: int
    active_services: int
    inactive_services: int
    failed_services: int
    missing_dependency_count: int
    cyclic_services: tuple[str, ...]
    health: RuntimeHealthStatus
    summary: str

    def __post_init__(self) -> None:
        names = _identifiers(self.service_names, "service_names")
        cyclic = _identifiers(self.cyclic_services, "cyclic_services")
        for name in (
            "total_services",
            "active_services",
            "inactive_services",
            "failed_services",
            "missing_dependency_count",
        ):
            _count(getattr(self, name), name)
        if self.total_services != len(names):
            raise ValueError("total_services must match service_names")
        if self.active_services + self.inactive_services != self.total_services:
            raise ValueError("active and inactive services must match total_services")
        if not set(cyclic).issubset(names):
            raise ValueError("cyclic_services must identify registered services")
        if not isinstance(self.health, RuntimeHealthStatus):
            raise TypeError("health must be a RuntimeHealthStatus")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "service_names", names)
        object.__setattr__(self, "cyclic_services", cyclic)


@dataclass(slots=True, frozen=True)
class RuntimeRegisteredFeaturesSummary:
    """Deterministic summary of registered feature and readiness metadata."""

    feature_ids: tuple[str, ...]
    categories: tuple[str, ...]
    total_features: int
    public_features: int
    experimental_features: int
    available_features: int
    conditional_features: int
    unavailable_features: int
    ready_features: int
    partial_features: int
    not_ready_features: int
    unknown_features: int
    summary: str

    def __post_init__(self) -> None:
        feature_ids = _identifiers(self.feature_ids, "feature_ids")
        categories = _identifiers(self.categories, "categories")
        for name in (
            "total_features",
            "public_features",
            "experimental_features",
            "available_features",
            "conditional_features",
            "unavailable_features",
            "ready_features",
            "partial_features",
            "not_ready_features",
            "unknown_features",
        ):
            _count(getattr(self, name), name)
        if self.total_features != len(feature_ids):
            raise ValueError("total_features must match feature_ids")
        if (
            self.available_features
            + self.conditional_features
            + self.unavailable_features
            != self.total_features
        ):
            raise ValueError("availability counts must match total_features")
        if (
            self.ready_features
            + self.partial_features
            + self.not_ready_features
            + self.unknown_features
            != self.total_features
        ):
            raise ValueError("readiness counts must match total_features")
        if self.public_features > self.total_features:
            raise ValueError("public_features cannot exceed total_features")
        if self.experimental_features > self.total_features:
            raise ValueError("experimental_features cannot exceed total_features")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "feature_ids", feature_ids)
        object.__setattr__(self, "categories", categories)


@dataclass(slots=True, frozen=True)
class RuntimeObservedCapabilitySummary:
    """Immutable observability view of the Capability Manifest."""

    readiness: RuntimeStateReadiness
    supported_subsystems: tuple[str, ...]
    available_diagnostics: tuple[str, ...]
    enabled_feature_flags: tuple[str, ...]
    disabled_feature_flags: tuple[str, ...]
    registered_service_count: int
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.readiness, RuntimeStateReadiness):
            raise TypeError("readiness must be a RuntimeStateReadiness")
        for name in (
            "supported_subsystems",
            "available_diagnostics",
            "enabled_feature_flags",
            "disabled_feature_flags",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        if set(self.enabled_feature_flags) & set(self.disabled_feature_flags):
            raise ValueError("enabled and disabled feature flags cannot overlap")
        _count(self.registered_service_count, "registered_service_count")
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeObservedDependencySummary:
    """Immutable observability view of feature dependency metadata."""

    readiness: RuntimeStateReadiness
    validation_status: RuntimeFeatureValidationStatus | None
    compatibility_status: RuntimeFeatureCompatibilityStatus | None
    node_count: int
    edge_count: int
    required_edge_count: int
    optional_edge_count: int
    missing_required_count: int
    missing_optional_count: int
    circular_component_count: int
    impacted_feature_count: int
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.readiness, RuntimeStateReadiness):
            raise TypeError("readiness must be a RuntimeStateReadiness")
        if self.validation_status is not None and not isinstance(
            self.validation_status,
            RuntimeFeatureValidationStatus,
        ):
            raise TypeError(
                "validation_status must be a RuntimeFeatureValidationStatus"
            )
        if self.compatibility_status is not None and not isinstance(
            self.compatibility_status,
            RuntimeFeatureCompatibilityStatus,
        ):
            raise TypeError(
                "compatibility_status must be a RuntimeFeatureCompatibilityStatus"
            )
        for name in (
            "node_count",
            "edge_count",
            "required_edge_count",
            "optional_edge_count",
            "missing_required_count",
            "missing_optional_count",
            "circular_component_count",
            "impacted_feature_count",
        ):
            _count(getattr(self, name), name)
        if self.required_edge_count + self.optional_edge_count != self.edge_count:
            raise ValueError("dependency edge counts must match edge_count")
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeObservabilityReport:
    """Aggregate immutable report over all runtime observability summaries."""

    state: RuntimeStateReadiness
    overview: RuntimeOverview
    registered_services: RuntimeRegisteredServicesSummary
    registered_features: RuntimeRegisteredFeaturesSummary
    capabilities: RuntimeObservedCapabilitySummary
    dependencies: RuntimeObservedDependencySummary
    readiness: RuntimeReadinessSummary
    health: RuntimeStateHealthSummary
    summary: str
    runtime_metadata: RuntimeMetadataSnapshot | None = None
    runtime_configuration: RuntimeConfigurationSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeStateReadiness):
            raise TypeError("state must be a RuntimeStateReadiness")
        expected_types = (
            ("overview", self.overview, RuntimeOverview),
            (
                "registered_services",
                self.registered_services,
                RuntimeRegisteredServicesSummary,
            ),
            (
                "registered_features",
                self.registered_features,
                RuntimeRegisteredFeaturesSummary,
            ),
            ("capabilities", self.capabilities, RuntimeObservedCapabilitySummary),
            ("dependencies", self.dependencies, RuntimeObservedDependencySummary),
            ("readiness", self.readiness, RuntimeReadinessSummary),
            ("health", self.health, RuntimeStateHealthSummary),
        )
        for name, value, expected_type in expected_types:
            if not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
        if self.overview.readiness is not self.state:
            raise ValueError("overview and observability states must match")
        if self.readiness.state is not self.state:
            raise ValueError("readiness and observability states must match")
        if self.runtime_metadata is not None and not isinstance(
            self.runtime_metadata,
            RuntimeMetadataSnapshot,
        ):
            raise TypeError("runtime_metadata must be a RuntimeMetadataSnapshot")
        if self.runtime_configuration is not None and not isinstance(
            self.runtime_configuration,
            RuntimeConfigurationSnapshot,
        ):
            raise TypeError(
                "runtime_configuration must be a RuntimeConfigurationSnapshot"
            )
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeSnapshotComparison:
    """Deterministic difference report between two runtime snapshots."""

    left_snapshot_id: str
    right_snapshot_id: str
    same_snapshot: bool
    same_content: bool
    schema_compatible: bool
    timestamp_changed: bool
    timestamp_delta: timedelta
    changed_sections: tuple[str, ...]
    services_added: tuple[str, ...]
    services_removed: tuple[str, ...]
    features_added: tuple[str, ...]
    features_removed: tuple[str, ...]
    readiness_changed: bool
    health_changed: bool
    summary: str

    def __post_init__(self) -> None:
        for name in ("left_snapshot_id", "right_snapshot_id"):
            _text(getattr(self, name), name, maximum=128)
        for name in (
            "same_snapshot",
            "same_content",
            "schema_compatible",
            "timestamp_changed",
            "readiness_changed",
            "health_changed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if not isinstance(self.timestamp_delta, timedelta):
            raise TypeError("timestamp_delta must be a timedelta")
        for name in (
            "changed_sections",
            "services_added",
            "services_removed",
            "features_added",
            "features_removed",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeSnapshot:
    """Complete versioned immutable runtime observability snapshot."""

    metadata: RuntimeSnapshotMetadata
    overview: RuntimeOverview
    registered_services_summary: RuntimeRegisteredServicesSummary
    registered_features_summary: RuntimeRegisteredFeaturesSummary
    capability_summary: RuntimeObservedCapabilitySummary
    dependency_summary: RuntimeObservedDependencySummary
    readiness_summary: RuntimeReadinessSummary
    health_summary: RuntimeStateHealthSummary
    diagnostics_snapshot: RuntimeDiagnosticsExport
    service_snapshot: RuntimeServiceRegistrySnapshot | None
    feature_snapshot: RuntimeFeatureRegistrySnapshot | None
    capability_snapshot: RuntimeCapabilityManifest | None
    dependency_snapshot: RuntimeDependencyGraphSnapshot | None
    state_snapshot: RuntimeStateSnapshot | None
    observability_report: RuntimeObservabilityReport
    runtime_metadata_snapshot: RuntimeMetadataSnapshot | None = None
    runtime_configuration_snapshot: RuntimeConfigurationSnapshot | None = None

    def __post_init__(self) -> None:
        expected_types = (
            ("metadata", self.metadata, RuntimeSnapshotMetadata),
            ("overview", self.overview, RuntimeOverview),
            (
                "registered_services_summary",
                self.registered_services_summary,
                RuntimeRegisteredServicesSummary,
            ),
            (
                "registered_features_summary",
                self.registered_features_summary,
                RuntimeRegisteredFeaturesSummary,
            ),
            (
                "capability_summary",
                self.capability_summary,
                RuntimeObservedCapabilitySummary,
            ),
            (
                "dependency_summary",
                self.dependency_summary,
                RuntimeObservedDependencySummary,
            ),
            ("readiness_summary", self.readiness_summary, RuntimeReadinessSummary),
            ("health_summary", self.health_summary, RuntimeStateHealthSummary),
            (
                "diagnostics_snapshot",
                self.diagnostics_snapshot,
                RuntimeDiagnosticsExport,
            ),
            (
                "observability_report",
                self.observability_report,
                RuntimeObservabilityReport,
            ),
        )
        for name, value, expected_type in expected_types:
            if not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
        optional_types = (
            ("service_snapshot", self.service_snapshot, RuntimeServiceRegistrySnapshot),
            ("feature_snapshot", self.feature_snapshot, RuntimeFeatureRegistrySnapshot),
            ("capability_snapshot", self.capability_snapshot, RuntimeCapabilityManifest),
            (
                "dependency_snapshot",
                self.dependency_snapshot,
                RuntimeDependencyGraphSnapshot,
            ),
            ("state_snapshot", self.state_snapshot, RuntimeStateSnapshot),
            (
                "runtime_metadata_snapshot",
                self.runtime_metadata_snapshot,
                RuntimeMetadataSnapshot,
            ),
            (
                "runtime_configuration_snapshot",
                self.runtime_configuration_snapshot,
                RuntimeConfigurationSnapshot,
            ),
        )
        for name, value, expected_type in optional_types:
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
            timestamp = getattr(value, "diagnostics_timestamp", None)
            if (
                value is not None
                and timestamp is not None
                and timestamp != self.metadata.captured_at
            ):
                raise ValueError(f"{name} must use the snapshot timestamp")
        if (
            self.runtime_metadata_snapshot is not None
            and self.runtime_metadata_snapshot.captured_at is not None
            and self.runtime_metadata_snapshot.captured_at
            != self.metadata.captured_at
        ):
            raise ValueError(
                "runtime_metadata_snapshot must use the snapshot timestamp"
            )
        if (
            self.runtime_configuration_snapshot is not None
            and self.runtime_configuration_snapshot.captured_at is not None
            and self.runtime_configuration_snapshot.captured_at
            != self.metadata.captured_at
        ):
            raise ValueError(
                "runtime_configuration_snapshot must use the snapshot timestamp"
            )
        if self.diagnostics_snapshot.captured_at != self.metadata.captured_at:
            raise ValueError("diagnostics and snapshot timestamps must match")
        if self.overview.captured_at != self.metadata.captured_at:
            raise ValueError("overview and snapshot timestamps must match")
        expected_report = (
            self.overview,
            self.registered_services_summary,
            self.registered_features_summary,
            self.capability_summary,
            self.dependency_summary,
            self.readiness_summary,
            self.health_summary,
            self.runtime_metadata_snapshot,
            self.runtime_configuration_snapshot,
        )
        if (
            self.observability_report.overview,
            self.observability_report.registered_services,
            self.observability_report.registered_features,
            self.observability_report.capabilities,
            self.observability_report.dependencies,
            self.observability_report.readiness,
            self.observability_report.health,
            self.observability_report.runtime_metadata,
            self.observability_report.runtime_configuration,
        ) != expected_report:
            raise ValueError("observability report must reuse snapshot summaries")

    @property
    def snapshot_id(self) -> str:
        """Return the deterministic snapshot identifier."""

        return self.metadata.snapshot_id

    @property
    def schema_version(self) -> str:
        """Return the immutable snapshot schema version."""

        return self.metadata.schema_version

    @property
    def captured_at(self) -> datetime:
        """Return the snapshot capture timestamp."""

        return self.metadata.captured_at

    def export(self) -> Mapping[str, object]:
        """Return a deeply immutable deterministic mapping export."""

        values = dict(_immutable_export(self))
        return MappingProxyType(
            {
                "snapshot_id": self.snapshot_id,
                "schema_version": self.schema_version,
                "captured_at": self.captured_at.isoformat(),
                **values,
            }
        )

    def compare(self, other: RuntimeSnapshot) -> RuntimeSnapshotComparison:
        """Compare this snapshot with another snapshot deterministically."""

        return RuntimeSnapshotEngine.compare(self, other)


RuntimeObservabilitySnapshot = RuntimeSnapshot
RuntimeSnapshotExport = RuntimeSnapshot
RuntimeSnapshotComparisonReport = RuntimeSnapshotComparison


class RuntimeSnapshotEngine:
    """Build and compare passive runtime observability snapshots."""

    def snapshot(self, source: RuntimeSnapshotSource) -> RuntimeSnapshot:
        """Capture one deterministic immutable runtime snapshot."""

        if not isinstance(source, RuntimeSnapshotSource):
            raise TypeError("source must be a RuntimeSnapshotSource")
        diagnostics = self._diagnostics(source)
        services = self._services(source)
        readiness = self._readiness(source)
        health = self._health(source)
        features = self._features(source, readiness)
        capabilities = self._capabilities(source)
        dependencies = self._dependencies(source)
        state = readiness.state
        overview = RuntimeOverview(
            runtime_version=source.runtime_version,
            build_version=source.build_version,
            lifecycle_state=source.lifecycle_state,
            readiness=state,
            health=source.diagnostics_health,
            registered_service_count=services.total_services,
            registered_feature_count=features.total_features,
            supported_subsystem_count=len(capabilities.supported_subsystems),
            dependency_edge_count=dependencies.edge_count,
            captured_at=source.captured_at,
            summary=(
                f"NARVIS {source.runtime_version} build {source.build_version} is "
                f"{state.value} with {services.total_services} services and "
                f"{features.total_features} features."
            ),
        )
        report = RuntimeObservabilityReport(
            state=state,
            overview=overview,
            registered_services=services,
            registered_features=features,
            capabilities=capabilities,
            dependencies=dependencies,
            readiness=readiness,
            health=health,
            summary=(
                f"Runtime observability is {state.value}: "
                f"{readiness.ready_feature_count} ready features, "
                f"{services.missing_dependency_count} missing service dependencies, "
                f"and {dependencies.impacted_feature_count} dependency-impacted features."
            ),
            runtime_metadata=source.runtime_metadata_snapshot,
            runtime_configuration=source.runtime_configuration_snapshot,
        )
        source_payload = {
            "diagnostics": diagnostics,
            "service_snapshot": source.service_registry_snapshot,
            "feature_snapshot": source.feature_registry_snapshot,
            "capability_snapshot": source.capability_manifest,
            "dependency_snapshot": source.dependency_graph_snapshot,
            "state_snapshot": source.runtime_state_snapshot,
            "runtime_metadata_snapshot": source.runtime_metadata_snapshot,
            "runtime_configuration_snapshot": (
                source.runtime_configuration_snapshot
            ),
            "observability_report": report,
            "attributes": source.metadata,
        }
        content_hash = _digest(source_payload, omit_time=True)
        snapshot_hash = _digest(
            {
                "schema_version": RUNTIME_SNAPSHOT_SCHEMA_VERSION,
                "captured_at": source.captured_at,
                "payload": source_payload,
            }
        )
        source_names = tuple(
            sorted(
                name
                for name, value in (
                    ("capability_manifest", source.capability_manifest),
                    ("dependency_graph", source.dependency_graph_snapshot),
                    ("diagnostics", diagnostics),
                    ("feature_registry", source.feature_registry_snapshot),
                    ("runtime_state", source.runtime_state_snapshot),
                    ("runtime_metadata", source.runtime_metadata_snapshot),
                    (
                        "runtime_configuration",
                        source.runtime_configuration_snapshot,
                    ),
                    ("service_registry", source.service_registry_snapshot),
                )
                if value is not None
            )
        )
        metadata = RuntimeSnapshotMetadata(
            snapshot_id=f"{_SNAPSHOT_ID_PREFIX}{snapshot_hash}",
            content_hash=content_hash,
            schema_version=RUNTIME_SNAPSHOT_SCHEMA_VERSION,
            runtime_version=source.runtime_version,
            build_version=source.build_version,
            captured_at=source.captured_at,
            source_names=source_names,
            attributes=source.metadata,
        )
        return RuntimeSnapshot(
            metadata=metadata,
            overview=overview,
            registered_services_summary=services,
            registered_features_summary=features,
            capability_summary=capabilities,
            dependency_summary=dependencies,
            readiness_summary=readiness,
            health_summary=health,
            diagnostics_snapshot=diagnostics,
            service_snapshot=source.service_registry_snapshot,
            feature_snapshot=source.feature_registry_snapshot,
            capability_snapshot=source.capability_manifest,
            dependency_snapshot=source.dependency_graph_snapshot,
            state_snapshot=source.runtime_state_snapshot,
            observability_report=report,
            runtime_metadata_snapshot=source.runtime_metadata_snapshot,
            runtime_configuration_snapshot=(
                source.runtime_configuration_snapshot
            ),
        )

    def capture(self, source: RuntimeSnapshotSource) -> RuntimeSnapshot:
        """Compatibility spelling for :meth:`snapshot`."""

        return self.snapshot(source)

    def export(self, source: RuntimeSnapshotSource) -> Mapping[str, object]:
        """Capture and deeply freeze one deterministic mapping export."""

        return self.snapshot(source).export()

    @staticmethod
    def compare(
        left: RuntimeSnapshot,
        right: RuntimeSnapshot,
    ) -> RuntimeSnapshotComparison:
        """Return a deterministic comparison of two immutable snapshots."""

        if not isinstance(left, RuntimeSnapshot) or not isinstance(
            right,
            RuntimeSnapshot,
        ):
            raise TypeError("left and right must be RuntimeSnapshot values")
        changed: set[str] = set()
        if (
            left.metadata.schema_version,
            left.metadata.runtime_version,
            left.metadata.build_version,
            left.metadata.attributes,
        ) != (
            right.metadata.schema_version,
            right.metadata.runtime_version,
            right.metadata.build_version,
            right.metadata.attributes,
        ):
            changed.add("metadata")
        timestamp_changed = left.captured_at != right.captured_at
        if timestamp_changed:
            changed.add("timestamp")
        if _digest(left.overview, omit_time=True) != _digest(
            right.overview,
            omit_time=True,
        ):
            changed.add("overview")
        section_values = (
            (
                "services",
                (left.registered_services_summary, left.service_snapshot),
                (right.registered_services_summary, right.service_snapshot),
            ),
            (
                "features",
                (left.registered_features_summary, left.feature_snapshot),
                (right.registered_features_summary, right.feature_snapshot),
            ),
            (
                "capabilities",
                (left.capability_summary, left.capability_snapshot),
                (right.capability_summary, right.capability_snapshot),
            ),
            (
                "dependencies",
                (left.dependency_summary, left.dependency_snapshot),
                (right.dependency_summary, right.dependency_snapshot),
            ),
            (
                "runtime_metadata",
                left.runtime_metadata_snapshot,
                right.runtime_metadata_snapshot,
            ),
            (
                "runtime_configuration",
                left.runtime_configuration_snapshot,
                right.runtime_configuration_snapshot,
            ),
        )
        for name, left_value, right_value in section_values:
            if _digest(left_value, omit_time=True) != _digest(
                right_value,
                omit_time=True,
            ):
                changed.add(name)
        left_readiness = (
            left.readiness_summary,
            (
                left.state_snapshot.state,
                left.state_snapshot.feature_readiness,
                left.state_snapshot.dependency_impact_summary,
                left.state_snapshot.compatibility_summary,
            )
            if left.state_snapshot is not None
            else None,
        )
        right_readiness = (
            right.readiness_summary,
            (
                right.state_snapshot.state,
                right.state_snapshot.feature_readiness,
                right.state_snapshot.dependency_impact_summary,
                right.state_snapshot.compatibility_summary,
            )
            if right.state_snapshot is not None
            else None,
        )
        readiness_changed = left_readiness != right_readiness
        if readiness_changed:
            changed.add("readiness")
        health_changed = left.health_summary != right.health_summary
        if health_changed:
            changed.add("health")
        if _digest(left.diagnostics_snapshot, omit_time=True) != _digest(
            right.diagnostics_snapshot,
            omit_time=True,
        ):
            changed.add("diagnostics")
        left_services = set(left.registered_services_summary.service_names)
        right_services = set(right.registered_services_summary.service_names)
        left_features = set(left.registered_features_summary.feature_ids)
        right_features = set(right.registered_features_summary.feature_ids)
        same_snapshot = left.snapshot_id == right.snapshot_id
        same_content = left.metadata.content_hash == right.metadata.content_hash
        summary = (
            f"Runtime snapshots are {'identical' if same_snapshot else 'different'}; "
            f"{len(changed)} sections changed"
            + (f": {', '.join(sorted(changed))}." if changed else ".")
        )
        return RuntimeSnapshotComparison(
            left_snapshot_id=left.snapshot_id,
            right_snapshot_id=right.snapshot_id,
            same_snapshot=same_snapshot,
            same_content=same_content,
            schema_compatible=(left.schema_version == right.schema_version),
            timestamp_changed=timestamp_changed,
            timestamp_delta=right.captured_at - left.captured_at,
            changed_sections=tuple(sorted(changed)),
            services_added=tuple(sorted(right_services - left_services)),
            services_removed=tuple(sorted(left_services - right_services)),
            features_added=tuple(sorted(right_features - left_features)),
            features_removed=tuple(sorted(left_features - right_features)),
            readiness_changed=readiness_changed,
            health_changed=health_changed,
            summary=summary,
        )

    @staticmethod
    def _diagnostics(source: RuntimeSnapshotSource) -> RuntimeDiagnosticsExport:
        return RuntimeDiagnosticsExport(
            lifecycle_state=source.lifecycle_state,
            health_status=source.diagnostics_health,
            compatibility_status=source.compatibility_status,
            registered_runtime_services=source.registered_runtime_services,
            ai_manager_registered=source.ai_manager_registered,
            conversation_runtime_state=source.conversation_runtime_state,
            event_bus_available=source.event_bus_available,
            logger_available=source.logger_available,
            passed_checks=source.passed_diagnostics_checks,
            total_checks=source.total_diagnostics_checks,
            issues=source.diagnostics_issues,
            startup_timestamp=source.startup_timestamp,
            uptime_seconds=source.uptime_seconds,
            captured_at=source.captured_at,
            summary=source.diagnostics_summary,
        )

    @staticmethod
    def _services(source: RuntimeSnapshotSource) -> RuntimeRegisteredServicesSummary:
        snapshot = source.service_registry_snapshot
        if snapshot is None:
            names = source.registered_runtime_services
            health = RuntimeHealthStatus.UNKNOWN
            active = 0
            inactive = len(names)
            failed = 0
            missing = 0
            cyclic: tuple[str, ...] = ()
        else:
            names = tuple(sorted(item.service_name for item in snapshot.services))
            health = snapshot.health.status
            active = snapshot.health.active_services
            inactive = snapshot.health.inactive_services
            failed = snapshot.health.failed_services
            missing = (
                snapshot.health.dependency_graph_summary.missing_dependency_count
            )
            cyclic = snapshot.health.dependency_graph_summary.cyclic_services
        return RuntimeRegisteredServicesSummary(
            service_names=names,
            total_services=len(names),
            active_services=active,
            inactive_services=inactive,
            failed_services=failed,
            missing_dependency_count=missing,
            cyclic_services=cyclic,
            health=health,
            summary=(
                f"{len(names)} runtime services are registered: {active} active, "
                f"{inactive} inactive, and {missing} missing dependency edges."
            ),
        )

    @staticmethod
    def _readiness(source: RuntimeSnapshotSource) -> RuntimeReadinessSummary:
        if source.runtime_state_snapshot is not None:
            return source.runtime_state_snapshot.readiness_summary
        state = (
            RuntimeStateReadiness.NOT_READY
            if source.lifecycle_state
            in (
                RuntimeLifecycleState.INITIALIZING,
                RuntimeLifecycleState.STOPPED,
                RuntimeLifecycleState.FAILED,
            )
            else RuntimeStateReadiness.UNKNOWN
        )
        return RuntimeReadinessSummary(
            state=state,
            total_feature_count=0,
            ready_feature_count=0,
            partial_feature_count=0,
            not_ready_feature_count=0,
            unknown_feature_count=0,
            ready_feature_ids=(),
            partial_feature_ids=(),
            not_ready_feature_ids=(),
            unknown_feature_ids=(),
            summary=f"Runtime readiness is {state.value}; state metadata is unavailable.",
        )

    @staticmethod
    def _health(source: RuntimeSnapshotSource) -> RuntimeStateHealthSummary:
        if source.runtime_state_snapshot is not None:
            return source.runtime_state_snapshot.health_summary
        service_health = (
            source.service_registry_snapshot.health.status
            if source.service_registry_snapshot is not None
            else RuntimeHealthStatus.UNKNOWN
        )
        if source.diagnostics_health in (
            RuntimeHealthStatus.FAILED,
            RuntimeHealthStatus.STOPPED,
        ) or service_health in (
            RuntimeHealthStatus.FAILED,
            RuntimeHealthStatus.STOPPED,
        ):
            state = RuntimeStateReadiness.NOT_READY
        elif RuntimeHealthStatus.UNKNOWN in (
            source.diagnostics_health,
            service_health,
        ):
            state = RuntimeStateReadiness.UNKNOWN
        elif source.diagnostics_health is service_health is RuntimeHealthStatus.HEALTHY:
            state = RuntimeStateReadiness.READY
        else:
            state = RuntimeStateReadiness.PARTIAL
        return RuntimeStateHealthSummary(
            state=state,
            diagnostics_health=source.diagnostics_health,
            service_registry_health=service_health,
            issues=source.diagnostics_issues,
            summary=(
                f"Runtime health is {state.value}: diagnostics "
                f"{source.diagnostics_health.value}, service registry "
                f"{service_health.value}."
            ),
        )

    @staticmethod
    def _features(
        source: RuntimeSnapshotSource,
        readiness: RuntimeReadinessSummary,
    ) -> RuntimeRegisteredFeaturesSummary:
        snapshot = source.feature_registry_snapshot
        if snapshot is None:
            feature_ids: tuple[str, ...] = ()
            categories: tuple[str, ...] = ()
            public = experimental = available = conditional = unavailable = 0
        else:
            feature_ids = tuple(item.id for item in snapshot.features)
            categories = tuple(sorted(snapshot.features_by_category))
            public = sum(
                item.commercial_visibility
                is RuntimeFeatureCommercialVisibility.PUBLIC
                for item in snapshot.features
            )
            experimental = sum(item.experimental for item in snapshot.features)
            available = sum(
                item.availability is RuntimeFeatureAvailability.AVAILABLE
                for item in snapshot.features
            )
            conditional = sum(
                item.availability is RuntimeFeatureAvailability.CONDITIONAL
                for item in snapshot.features
            )
            unavailable = sum(
                item.availability is RuntimeFeatureAvailability.UNAVAILABLE
                for item in snapshot.features
            )
        total = len(feature_ids)
        if readiness.total_feature_count == total:
            ready = readiness.ready_feature_count
            partial = readiness.partial_feature_count
            not_ready = readiness.not_ready_feature_count
            unknown = readiness.unknown_feature_count
        else:
            ready = partial = not_ready = 0
            unknown = total
        return RuntimeRegisteredFeaturesSummary(
            feature_ids=feature_ids,
            categories=categories,
            total_features=total,
            public_features=public,
            experimental_features=experimental,
            available_features=available,
            conditional_features=conditional,
            unavailable_features=unavailable,
            ready_features=ready,
            partial_features=partial,
            not_ready_features=not_ready,
            unknown_features=unknown,
            summary=(
                f"{total} runtime features are registered across "
                f"{len(categories)} categories; {ready} are ready."
            ),
        )

    @staticmethod
    def _capabilities(
        source: RuntimeSnapshotSource,
    ) -> RuntimeObservedCapabilitySummary:
        manifest = source.capability_manifest
        if manifest is None:
            return RuntimeObservedCapabilitySummary(
                readiness=RuntimeStateReadiness.UNKNOWN,
                supported_subsystems=(),
                available_diagnostics=(),
                enabled_feature_flags=(),
                disabled_feature_flags=(),
                registered_service_count=len(source.registered_runtime_services),
                summary="Runtime capability metadata is unavailable.",
            )
        readiness = {
            RuntimeReadinessLevel.READY: RuntimeStateReadiness.READY,
            RuntimeReadinessLevel.PARTIAL: RuntimeStateReadiness.PARTIAL,
            RuntimeReadinessLevel.NOT_READY: RuntimeStateReadiness.NOT_READY,
            RuntimeReadinessLevel.READINESS_UNKNOWN: RuntimeStateReadiness.UNKNOWN,
        }[manifest.readiness.level]
        enabled = tuple(
            sorted(name for name, value in manifest.feature_flags.items() if value)
        )
        disabled = tuple(
            sorted(name for name, value in manifest.feature_flags.items() if not value)
        )
        return RuntimeObservedCapabilitySummary(
            readiness=readiness,
            supported_subsystems=manifest.supported_subsystems,
            available_diagnostics=manifest.available_diagnostics,
            enabled_feature_flags=enabled,
            disabled_feature_flags=disabled,
            registered_service_count=len(manifest.registered_runtime_services),
            summary=(
                f"Capability metadata is {readiness.value}: "
                f"{len(manifest.supported_subsystems)} subsystems and "
                f"{len(enabled)} enabled feature flags."
            ),
        )

    @staticmethod
    def _dependencies(
        source: RuntimeSnapshotSource,
    ) -> RuntimeObservedDependencySummary:
        graph = source.dependency_graph_snapshot
        if graph is None:
            return RuntimeObservedDependencySummary(
                readiness=RuntimeStateReadiness.UNKNOWN,
                validation_status=None,
                compatibility_status=None,
                node_count=0,
                edge_count=0,
                required_edge_count=0,
                optional_edge_count=0,
                missing_required_count=0,
                missing_optional_count=0,
                circular_component_count=0,
                impacted_feature_count=0,
                summary="Runtime dependency metadata is unavailable.",
            )
        report = graph.validation_report
        compatibility = graph.compatibility_report
        readiness = {
            RuntimeFeatureValidationStatus.VALID: RuntimeStateReadiness.READY,
            RuntimeFeatureValidationStatus.DEGRADED: RuntimeStateReadiness.PARTIAL,
            RuntimeFeatureValidationStatus.INVALID: RuntimeStateReadiness.NOT_READY,
        }[report.status]
        required_edges = sum(
            edge.dependency_type is RuntimeFeatureDependencyType.REQUIRED
            for edge in graph.edges
        )
        optional_edges = len(graph.edges) - required_edges
        impacted = (
            source.runtime_state_snapshot.dependency_impact_summary.impacted_feature_count
            if source.runtime_state_snapshot is not None
            else len(
                set(report.conditional_feature_ids)
                | set(report.unavailable_feature_ids)
            )
        )
        return RuntimeObservedDependencySummary(
            readiness=readiness,
            validation_status=report.status,
            compatibility_status=compatibility.status,
            node_count=len(graph.nodes),
            edge_count=len(graph.edges),
            required_edge_count=required_edges,
            optional_edge_count=optional_edges,
            missing_required_count=len(report.missing_required_dependencies),
            missing_optional_count=len(report.missing_optional_dependencies),
            circular_component_count=len(report.circular_dependencies),
            impacted_feature_count=impacted,
            summary=(
                f"Dependency metadata is {readiness.value}: {len(graph.nodes)} nodes, "
                f"{len(graph.edges)} edges, and {impacted} impacted features."
            ),
        )


def build_runtime_snapshot_engine() -> RuntimeSnapshotEngine:
    """Return the passive Runtime Snapshot Engine for DI composition."""

    return RuntimeSnapshotEngine()


RuntimeObservabilityEngine = RuntimeSnapshotEngine


def build_runtime_observability_engine() -> RuntimeObservabilityEngine:
    """Return the Runtime Snapshot Engine using observability terminology."""

    return build_runtime_snapshot_engine()


__all__ = [
    "RUNTIME_OBSERVABILITY_VERSION",
    "RUNTIME_SNAPSHOT_SCHEMA_VERSION",
    "RuntimeDiagnosticsExport",
    "RuntimeObservabilityReport",
    "RuntimeObservabilityEngine",
    "RuntimeObservabilitySnapshot",
    "RuntimeObservedCapabilitySummary",
    "RuntimeObservedDependencySummary",
    "RuntimeOverview",
    "RuntimeRegisteredFeaturesSummary",
    "RuntimeRegisteredServicesSummary",
    "RuntimeSnapshot",
    "RuntimeSnapshotComparison",
    "RuntimeSnapshotComparisonReport",
    "RuntimeSnapshotEngine",
    "RuntimeSnapshotExport",
    "RuntimeSnapshotMetadata",
    "RuntimeSnapshotSource",
    "build_runtime_snapshot_engine",
    "build_runtime_observability_engine",
]
