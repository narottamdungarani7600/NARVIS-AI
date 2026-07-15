"""Immutable deterministic runtime state and readiness reporting.

The state engine is a passive metadata reducer.  It consumes snapshots from
the existing runtime registries and diagnostics pipeline; it never resolves a
service, invokes a provider, probes the host, performs I/O, or executes a
feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from .capabilities import RuntimeCapabilityManifest, RuntimeReadinessLevel
from .dependency_graph import (
    RuntimeDependencyGraphSnapshot,
    RuntimeFeatureCompatibilityStatus,
    RuntimeFeatureValidationStatus,
)
from .features import (
    RuntimeFeatureAvailability,
    RuntimeFeatureRegistrySnapshot,
)
from .service_registry import (
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeServiceRegistrySnapshot,
)


class RuntimeStateReadiness(str, Enum):
    """Readiness states produced by the runtime state engine."""

    READY = "ready"
    PARTIAL = "partial"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"


# A descriptive compatibility alias for consumers that name the enum by role.
RuntimeReadinessState = RuntimeStateReadiness


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
    if result != tuple(sorted(result)):
        raise ValueError(f"{name} must use deterministic ordering")
    return result


def _pairs(values: object, name: str) -> tuple[tuple[str, str], ...]:
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifier pairs") from error
    for value in result:
        if not isinstance(value, tuple) or len(value) != 2:
            raise TypeError(f"{name} must contain identifier pairs")
        _text(value[0], name, maximum=128)
        _text(value[1], name, maximum=128)
    if result != tuple(sorted(set(result))):
        raise ValueError(f"{name} must use unique deterministic ordering")
    return result


def _freeze_identifier_map(
    values: Mapping[str, tuple[str, ...]],
    name: str,
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    frozen: dict[str, tuple[str, ...]] = {}
    for feature_id in sorted(values):
        _text(feature_id, f"{name} key", maximum=128)
        frozen[feature_id] = _identifiers(values[feature_id], f"{name} values")
    return MappingProxyType(frozen)


@dataclass(slots=True, frozen=True)
class RuntimeStateSource:
    """One immutable, same-timestamp input set for state calculation."""

    lifecycle_state: RuntimeLifecycleState
    diagnostics_health: RuntimeHealthStatus
    diagnostics_issues: tuple[str, ...]
    diagnostics_timestamp: datetime
    service_registry_snapshot: RuntimeServiceRegistrySnapshot | None = None
    capability_manifest: RuntimeCapabilityManifest | None = None
    feature_registry_snapshot: RuntimeFeatureRegistrySnapshot | None = None
    dependency_graph_snapshot: RuntimeDependencyGraphSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        if not isinstance(self.diagnostics_health, RuntimeHealthStatus):
            raise TypeError("diagnostics_health must be a RuntimeHealthStatus")
        issues = tuple(self.diagnostics_issues)
        for issue in issues:
            _text(issue, "diagnostics issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("diagnostics_issues must use unique deterministic ordering")
        captured = _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        expected_types = (
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
        )
        for name, value, expected_type in expected_types:
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
            timestamp = getattr(value, "diagnostics_timestamp", None)
            if value is not None and timestamp is not None and timestamp != captured:
                raise ValueError(f"{name} must use the diagnostics timestamp")
        if (
            self.dependency_graph_snapshot is not None
            and self.feature_registry_snapshot is not None
            and self.dependency_graph_snapshot.feature_registry_snapshot
            != self.feature_registry_snapshot
        ):
            raise ValueError("dependency graph and feature registry snapshots must match")
        if (
            self.capability_manifest is not None
            and self.service_registry_snapshot is not None
            and self.capability_manifest.diagnostics_timestamp
            != self.service_registry_snapshot.diagnostics_timestamp
        ):
            raise ValueError("capability and service registry timestamps must match")
        object.__setattr__(self, "diagnostics_issues", issues)


@dataclass(slots=True, frozen=True)
class RuntimeFeatureReadiness:
    """One immutable dependency-aware feature readiness result."""

    feature_id: str
    readiness: RuntimeStateReadiness
    declared_availability: RuntimeFeatureAvailability
    required_dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    blocking_dependencies: tuple[str, ...]
    compatibility_conflicts: tuple[str, ...]
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id", maximum=128)
        if not isinstance(self.readiness, RuntimeStateReadiness):
            raise TypeError("readiness must be a RuntimeStateReadiness")
        if not isinstance(self.declared_availability, RuntimeFeatureAvailability):
            raise TypeError(
                "declared_availability must be a RuntimeFeatureAvailability"
            )
        for name in (
            "required_dependencies",
            "optional_dependencies",
            "blocking_dependencies",
            "compatibility_conflicts",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "feature readiness issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "issues", issues)

    @property
    def state(self) -> RuntimeStateReadiness:
        """Return the feature readiness using state-oriented terminology."""

        return self.readiness

    @property
    def status(self) -> RuntimeStateReadiness:
        """Return the feature readiness using report-oriented terminology."""

        return self.readiness

    @property
    def availability(self) -> RuntimeFeatureAvailability:
        """Return the effective feature-registry availability input."""

        return self.declared_availability


RuntimeFeatureReadinessState = RuntimeFeatureReadiness


@dataclass(slots=True, frozen=True)
class RuntimeReadinessSummary:
    """Deterministic aggregate and per-state feature counts."""

    state: RuntimeStateReadiness
    total_feature_count: int
    ready_feature_count: int
    partial_feature_count: int
    not_ready_feature_count: int
    unknown_feature_count: int
    ready_feature_ids: tuple[str, ...]
    partial_feature_ids: tuple[str, ...]
    not_ready_feature_ids: tuple[str, ...]
    unknown_feature_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeStateReadiness):
            raise TypeError("state must be a RuntimeStateReadiness")
        for name in (
            "total_feature_count",
            "ready_feature_count",
            "partial_feature_count",
            "not_ready_feature_count",
            "unknown_feature_count",
        ):
            _count(getattr(self, name), name)
        groups = (
            ("ready_feature_ids", "ready_feature_count"),
            ("partial_feature_ids", "partial_feature_count"),
            ("not_ready_feature_ids", "not_ready_feature_count"),
            ("unknown_feature_ids", "unknown_feature_count"),
        )
        all_ids: list[str] = []
        for ids_name, count_name in groups:
            values = _identifiers(getattr(self, ids_name), ids_name)
            if len(values) != getattr(self, count_name):
                raise ValueError(f"{count_name} must match {ids_name}")
            all_ids.extend(values)
            object.__setattr__(self, ids_name, values)
        if len(all_ids) != self.total_feature_count or len(set(all_ids)) != len(all_ids):
            raise ValueError("feature readiness groups must partition all features")
        _text(self.summary, "summary", maximum=2000)

    @property
    def readiness(self) -> RuntimeStateReadiness:
        """Return the aggregate readiness state."""

        return self.state

    @property
    def status(self) -> RuntimeStateReadiness:
        """Return the aggregate readiness state."""

        return self.state


@dataclass(slots=True, frozen=True)
class RuntimeDependencyImpactSummary:
    """Immutable report of dependency and relationship readiness impacts."""

    impacted_feature_ids: tuple[str, ...]
    blocking_dependencies: Mapping[str, tuple[str, ...]]
    optional_dependency_impacts: Mapping[str, tuple[str, ...]]
    conflicting_features: Mapping[str, tuple[str, ...]]
    missing_required_dependencies: tuple[tuple[str, str], ...]
    missing_optional_dependencies: tuple[tuple[str, str], ...]
    circular_feature_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "impacted_feature_ids",
            _identifiers(self.impacted_feature_ids, "impacted_feature_ids"),
        )
        for name in (
            "blocking_dependencies",
            "optional_dependency_impacts",
            "conflicting_features",
        ):
            object.__setattr__(
                self,
                name,
                _freeze_identifier_map(getattr(self, name), name),
            )
        for name in (
            "missing_required_dependencies",
            "missing_optional_dependencies",
        ):
            object.__setattr__(self, name, _pairs(getattr(self, name), name))
        object.__setattr__(
            self,
            "circular_feature_ids",
            _identifiers(self.circular_feature_ids, "circular_feature_ids"),
        )
        _text(self.summary, "summary", maximum=2000)

    @property
    def impacted_feature_count(self) -> int:
        """Return the number of features affected by dependency metadata."""

        return len(self.impacted_feature_ids)


@dataclass(slots=True, frozen=True)
class RuntimeStateCompatibilitySummary:
    """Readiness-oriented summary of feature compatibility metadata."""

    state: RuntimeStateReadiness
    source_status: RuntimeFeatureCompatibilityStatus | None
    compatible_pair_count: int
    conflicting_pair_count: int
    active_conflict_count: int
    missing_reference_count: int
    asymmetric_compatibility_count: int
    affected_feature_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeStateReadiness):
            raise TypeError("state must be a RuntimeStateReadiness")
        if self.source_status is not None and not isinstance(
            self.source_status,
            RuntimeFeatureCompatibilityStatus,
        ):
            raise TypeError(
                "source_status must be a RuntimeFeatureCompatibilityStatus"
            )
        for name in (
            "compatible_pair_count",
            "conflicting_pair_count",
            "active_conflict_count",
            "missing_reference_count",
            "asymmetric_compatibility_count",
        ):
            _count(getattr(self, name), name)
        object.__setattr__(
            self,
            "affected_feature_ids",
            _identifiers(self.affected_feature_ids, "affected_feature_ids"),
        )
        _text(self.summary, "summary", maximum=2000)

    @property
    def status(self) -> RuntimeStateReadiness:
        """Return the compatibility readiness state."""

        return self.state


@dataclass(slots=True, frozen=True)
class RuntimeStateHealthSummary:
    """Combined passive diagnostics and service-registry health summary."""

    state: RuntimeStateReadiness
    diagnostics_health: RuntimeHealthStatus
    service_registry_health: RuntimeHealthStatus
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeStateReadiness):
            raise TypeError("state must be a RuntimeStateReadiness")
        for name in ("diagnostics_health", "service_registry_health"):
            if not isinstance(getattr(self, name), RuntimeHealthStatus):
                raise TypeError(f"{name} must be a RuntimeHealthStatus")
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "health issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "issues", issues)

    @property
    def status(self) -> RuntimeStateReadiness:
        """Return the combined health readiness state."""

        return self.state


@dataclass(slots=True, frozen=True)
class RuntimeStateSnapshot:
    """Complete immutable runtime state derived from one metadata instant."""

    state: RuntimeStateReadiness
    lifecycle_state: RuntimeLifecycleState
    feature_readiness: tuple[RuntimeFeatureReadiness, ...]
    readiness_summary: RuntimeReadinessSummary
    dependency_impact_summary: RuntimeDependencyImpactSummary
    compatibility_summary: RuntimeStateCompatibilitySummary
    health_summary: RuntimeStateHealthSummary
    service_registry_snapshot: RuntimeServiceRegistrySnapshot | None
    capability_manifest: RuntimeCapabilityManifest | None
    feature_registry_snapshot: RuntimeFeatureRegistrySnapshot | None
    dependency_graph_snapshot: RuntimeDependencyGraphSnapshot | None
    diagnostics_timestamp: datetime
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeStateReadiness):
            raise TypeError("state must be a RuntimeStateReadiness")
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        features = tuple(self.feature_readiness)
        if not all(isinstance(item, RuntimeFeatureReadiness) for item in features):
            raise TypeError(
                "feature_readiness must contain RuntimeFeatureReadiness values"
            )
        if tuple(item.feature_id for item in features) != tuple(
            sorted(item.feature_id for item in features)
        ):
            raise ValueError("feature_readiness must use feature-id ordering")
        report_types = (
            ("readiness_summary", self.readiness_summary, RuntimeReadinessSummary),
            (
                "dependency_impact_summary",
                self.dependency_impact_summary,
                RuntimeDependencyImpactSummary,
            ),
            (
                "compatibility_summary",
                self.compatibility_summary,
                RuntimeStateCompatibilitySummary,
            ),
            ("health_summary", self.health_summary, RuntimeStateHealthSummary),
        )
        for name, value, expected_type in report_types:
            if not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
        if self.readiness_summary.state is not self.state:
            raise ValueError("snapshot and readiness summary states must match")
        if self.readiness_summary.total_feature_count != len(features):
            raise ValueError("readiness summary must account for every feature")
        captured = _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        for value in (
            self.service_registry_snapshot,
            self.capability_manifest,
            self.feature_registry_snapshot,
            self.dependency_graph_snapshot,
        ):
            timestamp = getattr(value, "diagnostics_timestamp", None)
            if value is not None and timestamp is not None and timestamp != captured:
                raise ValueError("runtime state source timestamps must match")
        if self.calculated_from_metadata is not True:
            raise ValueError("runtime state must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("runtime state cannot use active probes")
        object.__setattr__(self, "feature_readiness", features)

    @property
    def readiness(self) -> RuntimeStateReadiness:
        """Return the aggregate runtime readiness state."""

        return self.state

    @property
    def status(self) -> RuntimeStateReadiness:
        """Return the aggregate runtime readiness state."""

        return self.state

    def get(self, feature_id: str) -> RuntimeFeatureReadiness | None:
        """Return one feature readiness result."""

        _text(feature_id, "feature_id", maximum=128)
        return next(
            (item for item in self.feature_readiness if item.feature_id == feature_id),
            None,
        )


class RuntimeStateEngine:
    """Reduce immutable runtime metadata into deterministic readiness state."""

    def snapshot(self, source: RuntimeStateSource) -> RuntimeStateSnapshot:
        """Calculate one immutable runtime state snapshot without execution."""

        if not isinstance(source, RuntimeStateSource):
            raise TypeError("source must be a RuntimeStateSource")
        feature_readiness = self._feature_readiness(source)
        dependency_impact = self._dependency_impact(source, feature_readiness)
        compatibility = self._compatibility(source)
        health = self._health(source)
        state = self._aggregate(source, feature_readiness, compatibility, health)
        readiness = self._readiness_summary(state, feature_readiness)
        return RuntimeStateSnapshot(
            state=state,
            lifecycle_state=source.lifecycle_state,
            feature_readiness=feature_readiness,
            readiness_summary=readiness,
            dependency_impact_summary=dependency_impact,
            compatibility_summary=compatibility,
            health_summary=health,
            service_registry_snapshot=source.service_registry_snapshot,
            capability_manifest=source.capability_manifest,
            feature_registry_snapshot=source.feature_registry_snapshot,
            dependency_graph_snapshot=source.dependency_graph_snapshot,
            diagnostics_timestamp=source.diagnostics_timestamp,
        )

    def evaluate(self, source: RuntimeStateSource) -> RuntimeStateSnapshot:
        """Compatibility spelling for :meth:`snapshot`."""

        return self.snapshot(source)

    @staticmethod
    def _availability_state(
        availability: RuntimeFeatureAvailability,
    ) -> RuntimeStateReadiness:
        return {
            RuntimeFeatureAvailability.AVAILABLE: RuntimeStateReadiness.READY,
            RuntimeFeatureAvailability.CONDITIONAL: RuntimeStateReadiness.PARTIAL,
            RuntimeFeatureAvailability.UNAVAILABLE: RuntimeStateReadiness.NOT_READY,
        }[availability]

    def _feature_readiness(
        self,
        source: RuntimeStateSource,
    ) -> tuple[RuntimeFeatureReadiness, ...]:
        feature_snapshot = source.feature_registry_snapshot
        graph_snapshot = source.dependency_graph_snapshot
        if feature_snapshot is None:
            return ()
        graph_nodes = (
            {item.feature_id: item for item in graph_snapshot.nodes}
            if graph_snapshot is not None
            else {}
        )
        validation = (
            {
                item.feature_id: item
                for item in graph_snapshot.validation_report.feature_results
            }
            if graph_snapshot is not None
            else {}
        )
        results: list[RuntimeFeatureReadiness] = []
        for descriptor in feature_snapshot.features:
            node = graph_nodes.get(descriptor.id)
            result = validation.get(descriptor.id)
            declared = descriptor.availability
            if node is not None:
                readiness = self._availability_state(node.readiness)
                required = node.required_dependencies
                optional = node.optional_dependencies
            elif descriptor.depends_on or descriptor.parent_feature_id is not None:
                readiness = RuntimeStateReadiness.UNKNOWN
                required = descriptor.depends_on
                optional = descriptor.optional_dependencies
            else:
                readiness = self._availability_state(declared)
                required = descriptor.depends_on
                optional = descriptor.optional_dependencies
            blocking: tuple[str, ...] = ()
            conflicts: tuple[str, ...] = ()
            issues: set[str] = set()
            if result is not None:
                blocking = tuple(
                    sorted(
                        set(result.missing_required_dependencies)
                        | set(result.unavailable_required_dependencies)
                    )
                )
                conflicts = result.conflicting_features
                issues.update(
                    f"missing required dependency: {item}"
                    for item in result.missing_required_dependencies
                )
                issues.update(
                    f"missing optional dependency: {item}"
                    for item in result.missing_optional_dependencies
                )
                issues.update(
                    f"unavailable required dependency: {item}"
                    for item in result.unavailable_required_dependencies
                )
                issues.update(
                    f"compatibility conflict: {item}"
                    for item in result.conflicting_features
                )
                if result.circular_dependency:
                    issues.add("circular dependency")
                if result.parent_missing:
                    issues.add("missing parent feature")
            elif graph_snapshot is None and (required or optional):
                issues.add("dependency graph metadata unavailable")
            summary = (
                f"Feature {descriptor.id} is {readiness.value} from immutable runtime "
                f"metadata with {len(blocking)} blocking dependencies."
            )
            results.append(
                RuntimeFeatureReadiness(
                    feature_id=descriptor.id,
                    readiness=readiness,
                    declared_availability=declared,
                    required_dependencies=required,
                    optional_dependencies=optional,
                    blocking_dependencies=blocking,
                    compatibility_conflicts=conflicts,
                    issues=tuple(sorted(issues)),
                    summary=summary,
                )
            )
        return tuple(results)

    @staticmethod
    def _dependency_impact(
        source: RuntimeStateSource,
        features: tuple[RuntimeFeatureReadiness, ...],
    ) -> RuntimeDependencyImpactSummary:
        graph = source.dependency_graph_snapshot
        blocking = {
            item.feature_id: item.blocking_dependencies
            for item in features
            if item.blocking_dependencies
        }
        conflicts = {
            item.feature_id: item.compatibility_conflicts
            for item in features
            if item.compatibility_conflicts
        }
        optional_impacts: dict[str, tuple[str, ...]] = {}
        missing_required: tuple[tuple[str, str], ...] = ()
        missing_optional: tuple[tuple[str, str], ...] = ()
        circular_ids: tuple[str, ...] = ()
        if graph is not None:
            optional_impacts = {
                item.feature_id: item.missing_optional_dependencies
                for item in graph.validation_report.feature_results
                if item.missing_optional_dependencies
            }
            missing_required = tuple(
                sorted(
                    (edge.feature_id, edge.dependency_id)
                    for edge in graph.validation_report.missing_required_dependencies
                )
            )
            missing_optional = tuple(
                sorted(
                    (edge.feature_id, edge.dependency_id)
                    for edge in graph.validation_report.missing_optional_dependencies
                )
            )
            circular_ids = tuple(
                sorted(
                    {
                        feature_id
                        for cycle in graph.validation_report.circular_dependencies
                        for feature_id in cycle.feature_ids
                    }
                )
            )
        impacted = {
            item.feature_id
            for item in features
            if item.readiness is not RuntimeStateReadiness.READY
        }
        impacted.update(blocking)
        impacted.update(optional_impacts)
        impacted.update(conflicts)
        impacted.update(circular_ids)
        summary = (
            f"Dependency metadata impacts {len(impacted)} features; "
            f"{len(missing_required)} required and {len(missing_optional)} optional "
            "dependencies are missing."
        )
        return RuntimeDependencyImpactSummary(
            impacted_feature_ids=tuple(sorted(impacted)),
            blocking_dependencies=blocking,
            optional_dependency_impacts=optional_impacts,
            conflicting_features=conflicts,
            missing_required_dependencies=missing_required,
            missing_optional_dependencies=missing_optional,
            circular_feature_ids=circular_ids,
            summary=summary,
        )

    @staticmethod
    def _compatibility(
        source: RuntimeStateSource,
    ) -> RuntimeStateCompatibilitySummary:
        graph = source.dependency_graph_snapshot
        if graph is None:
            return RuntimeStateCompatibilitySummary(
                state=RuntimeStateReadiness.UNKNOWN,
                source_status=None,
                compatible_pair_count=0,
                conflicting_pair_count=0,
                active_conflict_count=0,
                missing_reference_count=0,
                asymmetric_compatibility_count=0,
                affected_feature_ids=(),
                summary="Feature compatibility is unknown because graph metadata is unavailable.",
            )
        report = graph.compatibility_report
        state = {
            RuntimeFeatureCompatibilityStatus.COMPATIBLE: RuntimeStateReadiness.READY,
            RuntimeFeatureCompatibilityStatus.DEGRADED: RuntimeStateReadiness.PARTIAL,
            RuntimeFeatureCompatibilityStatus.INCOMPATIBLE: RuntimeStateReadiness.NOT_READY,
        }[report.status]
        affected = {
            feature_id for pair in report.active_conflicts for feature_id in pair
        }
        affected.update(
            feature_id for item in report.missing_references for feature_id in item[:2]
        )
        affected.update(
            feature_id
            for pair in report.asymmetric_compatibilities
            for feature_id in pair
        )
        summary = (
            f"Feature compatibility is {state.value}: "
            f"{len(report.active_conflicts)} active conflicts and "
            f"{len(report.missing_references)} missing references."
        )
        return RuntimeStateCompatibilitySummary(
            state=state,
            source_status=report.status,
            compatible_pair_count=len(report.compatible_pairs),
            conflicting_pair_count=len(report.conflicting_pairs),
            active_conflict_count=len(report.active_conflicts),
            missing_reference_count=len(report.missing_references),
            asymmetric_compatibility_count=len(report.asymmetric_compatibilities),
            affected_feature_ids=tuple(sorted(affected)),
            summary=summary,
        )

    @staticmethod
    def _health(source: RuntimeStateSource) -> RuntimeStateHealthSummary:
        service_health = (
            source.service_registry_snapshot.health.status
            if source.service_registry_snapshot is not None
            else RuntimeHealthStatus.UNKNOWN
        )
        health_values = (source.diagnostics_health, service_health)
        if any(
            item in (RuntimeHealthStatus.FAILED, RuntimeHealthStatus.STOPPED)
            for item in health_values
        ):
            state = RuntimeStateReadiness.NOT_READY
        elif any(item is RuntimeHealthStatus.UNKNOWN for item in health_values):
            state = RuntimeStateReadiness.UNKNOWN
        elif all(item is RuntimeHealthStatus.HEALTHY for item in health_values):
            state = RuntimeStateReadiness.READY
        else:
            state = RuntimeStateReadiness.PARTIAL
        summary = (
            f"Runtime health is {state.value}: diagnostics "
            f"{source.diagnostics_health.value}, service registry {service_health.value}."
        )
        return RuntimeStateHealthSummary(
            state=state,
            diagnostics_health=source.diagnostics_health,
            service_registry_health=service_health,
            issues=source.diagnostics_issues,
            summary=summary,
        )

    @staticmethod
    def _aggregate(
        source: RuntimeStateSource,
        features: tuple[RuntimeFeatureReadiness, ...],
        compatibility: RuntimeStateCompatibilitySummary,
        health: RuntimeStateHealthSummary,
    ) -> RuntimeStateReadiness:
        if source.lifecycle_state is RuntimeLifecycleState.UNKNOWN:
            return RuntimeStateReadiness.UNKNOWN
        if source.lifecycle_state is not RuntimeLifecycleState.RUNNING:
            return RuntimeStateReadiness.NOT_READY
        if any(
            item is None
            for item in (
                source.service_registry_snapshot,
                source.capability_manifest,
                source.feature_registry_snapshot,
                source.dependency_graph_snapshot,
            )
        ):
            return RuntimeStateReadiness.UNKNOWN
        manifest = source.capability_manifest
        graph = source.dependency_graph_snapshot
        assert manifest is not None
        assert graph is not None
        if manifest.readiness.level is RuntimeReadinessLevel.READINESS_UNKNOWN:
            return RuntimeStateReadiness.UNKNOWN
        if (
            manifest.readiness.level is RuntimeReadinessLevel.NOT_READY
            or health.state is RuntimeStateReadiness.NOT_READY
            or compatibility.state is RuntimeStateReadiness.NOT_READY
        ):
            return RuntimeStateReadiness.NOT_READY
        if health.state is RuntimeStateReadiness.UNKNOWN:
            return RuntimeStateReadiness.UNKNOWN
        if not features:
            return RuntimeStateReadiness.UNKNOWN
        usable = sum(
            item.readiness
            in (RuntimeStateReadiness.READY, RuntimeStateReadiness.PARTIAL)
            for item in features
        )
        if usable == 0:
            return RuntimeStateReadiness.NOT_READY
        all_ready = all(
            item.readiness is RuntimeStateReadiness.READY for item in features
        )
        if (
            all_ready
            and manifest.readiness.level is RuntimeReadinessLevel.READY
            and health.state is RuntimeStateReadiness.READY
            and compatibility.state is RuntimeStateReadiness.READY
            and graph.validation_report.status is RuntimeFeatureValidationStatus.VALID
        ):
            return RuntimeStateReadiness.READY
        return RuntimeStateReadiness.PARTIAL

    @staticmethod
    def _readiness_summary(
        state: RuntimeStateReadiness,
        features: tuple[RuntimeFeatureReadiness, ...],
    ) -> RuntimeReadinessSummary:
        groups = {
            readiness: tuple(
                item.feature_id
                for item in features
                if item.readiness is readiness
            )
            for readiness in RuntimeStateReadiness
        }
        summary = (
            f"Runtime state is {state.value}: {len(groups[RuntimeStateReadiness.READY])} "
            f"ready, {len(groups[RuntimeStateReadiness.PARTIAL])} partial, "
            f"{len(groups[RuntimeStateReadiness.NOT_READY])} not ready, and "
            f"{len(groups[RuntimeStateReadiness.UNKNOWN])} unknown features."
        )
        return RuntimeReadinessSummary(
            state=state,
            total_feature_count=len(features),
            ready_feature_count=len(groups[RuntimeStateReadiness.READY]),
            partial_feature_count=len(groups[RuntimeStateReadiness.PARTIAL]),
            not_ready_feature_count=len(groups[RuntimeStateReadiness.NOT_READY]),
            unknown_feature_count=len(groups[RuntimeStateReadiness.UNKNOWN]),
            ready_feature_ids=groups[RuntimeStateReadiness.READY],
            partial_feature_ids=groups[RuntimeStateReadiness.PARTIAL],
            not_ready_feature_ids=groups[RuntimeStateReadiness.NOT_READY],
            unknown_feature_ids=groups[RuntimeStateReadiness.UNKNOWN],
            summary=summary,
        )


def build_runtime_state_engine() -> RuntimeStateEngine:
    """Return the passive Runtime State Engine for DI composition."""

    return RuntimeStateEngine()


__all__ = [
    "RuntimeDependencyImpactSummary",
    "RuntimeFeatureReadiness",
    "RuntimeFeatureReadinessState",
    "RuntimeReadinessState",
    "RuntimeReadinessSummary",
    "RuntimeStateCompatibilitySummary",
    "RuntimeStateEngine",
    "RuntimeStateHealthSummary",
    "RuntimeStateReadiness",
    "RuntimeStateSnapshot",
    "RuntimeStateSource",
    "build_runtime_state_engine",
]
