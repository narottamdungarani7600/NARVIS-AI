"""Immutable runtime feature dependencies, relationships, and validation.

The dependency graph consumes Runtime Feature Registry snapshots only. It
performs deterministic metadata validation and readiness propagation without
resolving services, invoking providers, probing the host, using the network,
or executing any described feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from .features import (
    RuntimeFeatureAvailability,
    RuntimeFeatureDescriptor,
    RuntimeFeatureRegistry,
    RuntimeFeatureRegistrySnapshot,
)
from .runtime_metadata import RUNTIME_DEPENDENCY_GRAPH_VERSION
from .runtime_config import RUNTIME_CONFIGURATION_VERSION
from .runtime_profiles import RUNTIME_PROFILE_REGISTRY_VERSION


class RuntimeFeatureDependencyType(str, Enum):
    """Supported dependency-edge classifications."""

    REQUIRED = "required"
    OPTIONAL = "optional"


class RuntimeFeatureValidationStatus(str, Enum):
    """Aggregate and per-feature metadata validation classifications."""

    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"


class RuntimeFeatureCompatibilityStatus(str, Enum):
    """Feature relationship compatibility classifications."""

    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    INCOMPATIBLE = "incompatible"


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
    return tuple(sorted(result))


def _ordered_identifiers(values: object, name: str) -> tuple[str, ...]:
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


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=128)


def _freeze_groups(
    values: Mapping[str, tuple[str, ...]],
    name: str,
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    frozen: dict[str, tuple[str, ...]] = {}
    for key in sorted(values):
        _text(key, f"{name} key", maximum=128)
        frozen[key] = _identifiers(values[key], f"{name} values")
    return MappingProxyType(frozen)


def _pair(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))  # type: ignore[return-value]


@dataclass(slots=True, frozen=True)
class RuntimeFeatureDependencyEdge:
    """One immutable required or optional feature dependency edge."""

    feature_id: str
    dependency_id: str
    dependency_type: RuntimeFeatureDependencyType

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id", maximum=128)
        _text(self.dependency_id, "dependency_id", maximum=128)
        if not isinstance(self.dependency_type, RuntimeFeatureDependencyType):
            try:
                object.__setattr__(
                    self,
                    "dependency_type",
                    RuntimeFeatureDependencyType(self.dependency_type),
                )
            except (TypeError, ValueError) as error:
                raise TypeError(
                    "dependency_type must be a RuntimeFeatureDependencyType"
                ) from error


RuntimeFeatureDependency = RuntimeFeatureDependencyEdge


@dataclass(slots=True, frozen=True)
class RuntimeFeatureDependencyCycle:
    """One deterministic strongly connected feature component."""

    feature_ids: tuple[str, ...]
    required_only: bool

    def __post_init__(self) -> None:
        feature_ids = _identifiers(self.feature_ids, "feature_ids")
        if not feature_ids:
            raise ValueError("feature_ids cannot be empty")
        if not isinstance(self.required_only, bool):
            raise TypeError("required_only must be a bool")
        object.__setattr__(self, "feature_ids", feature_ids)


@dataclass(slots=True, frozen=True)
class RuntimeFeatureRelationship:
    """Derived immutable relationship metadata for one feature."""

    feature_id: str
    depends_on: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    required_by: tuple[str, ...]
    optionally_required_by: tuple[str, ...]
    compatible_with: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    parent_feature_id: str | None
    child_feature_ids: tuple[str, ...]
    category: str
    category_parent: str | None
    groups: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id", maximum=128)
        _text(self.category, "category", maximum=128)
        for name in (
            "depends_on",
            "optional_dependencies",
            "required_by",
            "optionally_required_by",
            "compatible_with",
            "conflicts_with",
            "child_feature_ids",
            "groups",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        object.__setattr__(
            self,
            "parent_feature_id",
            _optional_text(self.parent_feature_id, "parent_feature_id"),
        )
        object.__setattr__(
            self,
            "category_parent",
            _optional_text(self.category_parent, "category_parent"),
        )


@dataclass(slots=True, frozen=True)
class RuntimeFeatureRelationshipSummary:
    """Immutable feature, category, and group relationship export."""

    relationships: tuple[RuntimeFeatureRelationship, ...]
    category_hierarchy: Mapping[str, tuple[str, ...]]
    feature_groups: Mapping[str, tuple[str, ...]]
    diagnostics_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        relationships = tuple(self.relationships)
        if not all(
            isinstance(item, RuntimeFeatureRelationship) for item in relationships
        ):
            raise TypeError(
                "relationships must contain RuntimeFeatureRelationship values"
            )
        ids = tuple(item.feature_id for item in relationships)
        if ids != tuple(sorted(ids)) or len(set(ids)) != len(ids):
            raise ValueError("relationships must use unique feature-id ordering")
        if self.diagnostics_timestamp is not None:
            _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        object.__setattr__(self, "relationships", relationships)
        object.__setattr__(
            self,
            "category_hierarchy",
            _freeze_groups(self.category_hierarchy, "category_hierarchy"),
        )
        object.__setattr__(
            self,
            "feature_groups",
            _freeze_groups(self.feature_groups, "feature_groups"),
        )

    def get(self, feature_id: str) -> RuntimeFeatureRelationship | None:
        """Return relationship metadata for one feature id."""

        _text(feature_id, "feature_id", maximum=128)
        return next(
            (item for item in self.relationships if item.feature_id == feature_id),
            None,
        )


@dataclass(slots=True, frozen=True)
class RuntimeFeatureCompatibilityReport:
    """Deterministic compatibility and conflict validation report."""

    status: RuntimeFeatureCompatibilityStatus
    compatible_pairs: tuple[tuple[str, str], ...]
    conflicting_pairs: tuple[tuple[str, str], ...]
    active_conflicts: tuple[tuple[str, str], ...]
    missing_references: tuple[tuple[str, str, str], ...]
    asymmetric_compatibilities: tuple[tuple[str, str], ...]
    contradictory_relationships: tuple[tuple[str, str], ...]
    diagnostics_timestamp: datetime | None = None
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeFeatureCompatibilityStatus):
            raise TypeError("status must be a RuntimeFeatureCompatibilityStatus")
        for name in (
            "compatible_pairs",
            "conflicting_pairs",
            "active_conflicts",
            "asymmetric_compatibilities",
            "contradictory_relationships",
        ):
            values = tuple(getattr(self, name))
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must use unique deterministic ordering")
            object.__setattr__(self, name, values)
        missing = tuple(self.missing_references)
        if missing != tuple(sorted(set(missing))):
            raise ValueError(
                "missing_references must use unique deterministic ordering"
            )
        if self.diagnostics_timestamp is not None:
            _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        if self.calculated_from_metadata is not True:
            raise ValueError("compatibility must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("compatibility cannot use active probes")
        object.__setattr__(self, "missing_references", missing)


@dataclass(slots=True, frozen=True)
class RuntimeFeatureValidationResult:
    """Deterministic validation and propagated readiness for one feature."""

    feature_id: str
    status: RuntimeFeatureValidationStatus
    readiness: RuntimeFeatureAvailability
    missing_required_dependencies: tuple[str, ...]
    missing_optional_dependencies: tuple[str, ...]
    unavailable_required_dependencies: tuple[str, ...]
    conflicting_features: tuple[str, ...]
    circular_dependency: bool
    parent_missing: bool
    summary: str

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id", maximum=128)
        if not isinstance(self.status, RuntimeFeatureValidationStatus):
            raise TypeError("status must be a RuntimeFeatureValidationStatus")
        if not isinstance(self.readiness, RuntimeFeatureAvailability):
            raise TypeError("readiness must be a RuntimeFeatureAvailability")
        for name in (
            "missing_required_dependencies",
            "missing_optional_dependencies",
            "unavailable_required_dependencies",
            "conflicting_features",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        for name in ("circular_dependency", "parent_missing"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeDependencyValidationReport:
    """Complete immutable dependency, hierarchy, and readiness validation."""

    status: RuntimeFeatureValidationStatus
    feature_results: tuple[RuntimeFeatureValidationResult, ...]
    missing_required_dependencies: tuple[RuntimeFeatureDependencyEdge, ...]
    missing_optional_dependencies: tuple[RuntimeFeatureDependencyEdge, ...]
    missing_parents: tuple[tuple[str, str], ...]
    circular_dependencies: tuple[RuntimeFeatureDependencyCycle, ...]
    parent_cycles: tuple[tuple[str, ...], ...]
    category_cycles: tuple[tuple[str, ...], ...]
    category_parent_conflicts: tuple[tuple[str, ...], ...]
    ready_feature_ids: tuple[str, ...]
    conditional_feature_ids: tuple[str, ...]
    unavailable_feature_ids: tuple[str, ...]
    diagnostics_timestamp: datetime | None = None
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeFeatureValidationStatus):
            raise TypeError("status must be a RuntimeFeatureValidationStatus")
        results = tuple(self.feature_results)
        if not all(isinstance(item, RuntimeFeatureValidationResult) for item in results):
            raise TypeError(
                "feature_results must contain RuntimeFeatureValidationResult values"
            )
        if tuple(item.feature_id for item in results) != tuple(
            sorted(item.feature_id for item in results)
        ):
            raise ValueError("feature_results must use feature-id ordering")
        for name, dependency_type in (
            ("missing_required_dependencies", RuntimeFeatureDependencyType.REQUIRED),
            ("missing_optional_dependencies", RuntimeFeatureDependencyType.OPTIONAL),
        ):
            edges = tuple(getattr(self, name))
            if not all(
                isinstance(edge, RuntimeFeatureDependencyEdge)
                and edge.dependency_type is dependency_type
                for edge in edges
            ):
                raise TypeError(f"{name} contains invalid dependency edges")
            object.__setattr__(self, name, edges)
        cycles = tuple(self.circular_dependencies)
        if not all(isinstance(item, RuntimeFeatureDependencyCycle) for item in cycles):
            raise TypeError(
                "circular_dependencies must contain RuntimeFeatureDependencyCycle values"
            )
        for name in (
            "missing_parents",
            "parent_cycles",
            "category_cycles",
            "category_parent_conflicts",
        ):
            values = tuple(getattr(self, name))
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must use unique deterministic ordering")
            object.__setattr__(self, name, values)
        for name in (
            "ready_feature_ids",
            "conditional_feature_ids",
            "unavailable_feature_ids",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        if self.diagnostics_timestamp is not None:
            _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        if self.calculated_from_metadata is not True:
            raise ValueError("validation must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("validation cannot use active probes")
        object.__setattr__(self, "feature_results", results)
        object.__setattr__(self, "circular_dependencies", cycles)

    def get(self, feature_id: str) -> RuntimeFeatureValidationResult | None:
        """Return one feature validation result."""

        _text(feature_id, "feature_id", maximum=128)
        return next(
            (item for item in self.feature_results if item.feature_id == feature_id),
            None,
        )


RuntimeDependencyGraphValidationReport = RuntimeDependencyValidationReport


@dataclass(slots=True, frozen=True)
class RuntimeFeatureGraphNode:
    """One immutable feature node with forward and reverse relationships."""

    feature_id: str
    parent_feature_id: str | None
    child_feature_ids: tuple[str, ...]
    required_dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    required_by: tuple[str, ...]
    optionally_required_by: tuple[str, ...]
    readiness: RuntimeFeatureAvailability

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id", maximum=128)
        object.__setattr__(
            self,
            "parent_feature_id",
            _optional_text(self.parent_feature_id, "parent_feature_id"),
        )
        for name in (
            "child_feature_ids",
            "required_dependencies",
            "optional_dependencies",
            "required_by",
            "optionally_required_by",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        if not isinstance(self.readiness, RuntimeFeatureAvailability):
            raise TypeError("readiness must be a RuntimeFeatureAvailability")


@dataclass(slots=True, frozen=True)
class RuntimeDependencyGraphSnapshot:
    """Complete immutable runtime feature graph and report export."""

    feature_registry_snapshot: RuntimeFeatureRegistrySnapshot
    nodes: tuple[RuntimeFeatureGraphNode, ...]
    edges: tuple[RuntimeFeatureDependencyEdge, ...]
    ordered_feature_ids: tuple[str, ...]
    root_feature_ids: tuple[str, ...]
    circular_dependencies: tuple[RuntimeFeatureDependencyCycle, ...]
    relationship_summary: RuntimeFeatureRelationshipSummary
    validation_report: RuntimeDependencyValidationReport
    compatibility_report: RuntimeFeatureCompatibilityReport
    diagnostics_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.feature_registry_snapshot,
            RuntimeFeatureRegistrySnapshot,
        ):
            raise TypeError(
                "feature_registry_snapshot must be a RuntimeFeatureRegistrySnapshot"
            )
        nodes = tuple(self.nodes)
        if not all(isinstance(item, RuntimeFeatureGraphNode) for item in nodes):
            raise TypeError("nodes must contain RuntimeFeatureGraphNode values")
        node_ids = tuple(item.feature_id for item in nodes)
        if node_ids != tuple(sorted(node_ids)) or len(set(node_ids)) != len(node_ids):
            raise ValueError("nodes must use unique feature-id ordering")
        edges = tuple(self.edges)
        if not all(isinstance(item, RuntimeFeatureDependencyEdge) for item in edges):
            raise TypeError("edges must contain RuntimeFeatureDependencyEdge values")
        ordered = _ordered_identifiers(
            self.ordered_feature_ids,
            "ordered_feature_ids",
        )
        if set(ordered) != set(node_ids):
            raise ValueError("ordered_feature_ids must contain every graph node")
        roots = _identifiers(self.root_feature_ids, "root_feature_ids")
        if not set(roots).issubset(node_ids):
            raise ValueError("root_feature_ids must identify graph nodes")
        cycles = tuple(self.circular_dependencies)
        if not all(isinstance(item, RuntimeFeatureDependencyCycle) for item in cycles):
            raise TypeError(
                "circular_dependencies must contain RuntimeFeatureDependencyCycle values"
            )
        if not isinstance(
            self.relationship_summary,
            RuntimeFeatureRelationshipSummary,
        ):
            raise TypeError(
                "relationship_summary must be a RuntimeFeatureRelationshipSummary"
            )
        if not isinstance(self.validation_report, RuntimeDependencyValidationReport):
            raise TypeError(
                "validation_report must be a RuntimeDependencyValidationReport"
            )
        if not isinstance(
            self.compatibility_report,
            RuntimeFeatureCompatibilityReport,
        ):
            raise TypeError(
                "compatibility_report must be a RuntimeFeatureCompatibilityReport"
            )
        if self.diagnostics_timestamp is not None:
            captured = _time(self.diagnostics_timestamp, "diagnostics_timestamp")
            timestamps = (
                self.feature_registry_snapshot.diagnostics_timestamp,
                self.relationship_summary.diagnostics_timestamp,
                self.validation_report.diagnostics_timestamp,
                self.compatibility_report.diagnostics_timestamp,
            )
            if any(value != captured for value in timestamps):
                raise ValueError("graph snapshot timestamps must match")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "ordered_feature_ids", ordered)
        object.__setattr__(self, "root_feature_ids", roots)
        object.__setattr__(self, "circular_dependencies", cycles)

    def get(self, feature_id: str) -> RuntimeFeatureGraphNode | None:
        """Return one feature graph node."""

        _text(feature_id, "feature_id", maximum=128)
        return next((item for item in self.nodes if item.feature_id == feature_id), None)


class RuntimeDependencyGraph:
    """Build deterministic feature graphs from immutable registry snapshots."""

    def __init__(self, feature_registry: RuntimeFeatureRegistry | None = None) -> None:
        if feature_registry is not None and not callable(
            getattr(feature_registry, "snapshot", None)
        ):
            raise TypeError("feature_registry must provide snapshot")
        self._feature_registry = feature_registry

    def snapshot(
        self,
        *,
        feature_registry_snapshot: RuntimeFeatureRegistrySnapshot | None = None,
        diagnostics_timestamp: datetime | None = None,
    ) -> RuntimeDependencyGraphSnapshot:
        """Return graph, relationship, validation, and compatibility metadata."""

        captured_at = diagnostics_timestamp
        if captured_at is not None:
            _time(captured_at, "diagnostics_timestamp")
        feature_snapshot = feature_registry_snapshot
        if feature_snapshot is None:
            if self._feature_registry is None:
                raise ValueError(
                    "feature_registry_snapshot is required without a feature registry"
                )
            feature_snapshot = self._feature_registry.snapshot(
                diagnostics_timestamp=captured_at
            )
        if not isinstance(feature_snapshot, RuntimeFeatureRegistrySnapshot):
            raise TypeError(
                "feature_registry_snapshot must be a RuntimeFeatureRegistrySnapshot"
            )
        if captured_at is None:
            captured_at = feature_snapshot.diagnostics_timestamp
        elif feature_snapshot.diagnostics_timestamp != captured_at:
            raise ValueError("feature registry and graph timestamps must match")

        descriptors = {item.id: item for item in feature_snapshot.features}
        edges = self._edges(descriptors)
        cycles = self._dependency_cycles(tuple(descriptors), edges)
        parent_cycles = self._parent_cycles(descriptors)
        category_hierarchy, category_conflicts = self._category_hierarchy(
            descriptors
        )
        category_cycles = self._category_cycles(descriptors)
        feature_groups = self._feature_groups(descriptors)
        relationships = self._relationships(descriptors)
        relationship_summary = RuntimeFeatureRelationshipSummary(
            relationships=relationships,
            category_hierarchy=category_hierarchy,
            feature_groups=feature_groups,
            diagnostics_timestamp=captured_at,
        )
        compatibility = self._compatibility_report(descriptors, captured_at)
        readiness = self._readiness(
            descriptors,
            cycles,
            parent_cycles,
            compatibility,
        )
        validation = self._validation_report(
            descriptors,
            edges,
            cycles,
            parent_cycles,
            category_cycles,
            category_conflicts,
            compatibility,
            readiness,
            captured_at,
        )
        nodes = self._nodes(descriptors, readiness)
        ordered = self._topological_order(descriptors, cycles, parent_cycles)
        roots = tuple(
            sorted(
                feature_id
                for feature_id, descriptor in descriptors.items()
                if descriptor.parent_feature_id is None
            )
        )
        return RuntimeDependencyGraphSnapshot(
            feature_registry_snapshot=feature_snapshot,
            nodes=nodes,
            edges=edges,
            ordered_feature_ids=ordered,
            root_feature_ids=roots,
            circular_dependencies=cycles,
            relationship_summary=relationship_summary,
            validation_report=validation,
            compatibility_report=compatibility,
            diagnostics_timestamp=captured_at,
        )

    def validate(
        self,
        *,
        feature_registry_snapshot: RuntimeFeatureRegistrySnapshot | None = None,
        diagnostics_timestamp: datetime | None = None,
    ) -> RuntimeDependencyValidationReport:
        """Return the immutable validation portion of a graph snapshot."""

        return self.snapshot(
            feature_registry_snapshot=feature_registry_snapshot,
            diagnostics_timestamp=diagnostics_timestamp,
        ).validation_report

    @staticmethod
    def _edges(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
    ) -> tuple[RuntimeFeatureDependencyEdge, ...]:
        edges = tuple(
            RuntimeFeatureDependencyEdge(feature_id, dependency_id, dependency_type)
            for feature_id, descriptor in descriptors.items()
            for dependency_type, dependencies in (
                (RuntimeFeatureDependencyType.REQUIRED, descriptor.depends_on),
                (
                    RuntimeFeatureDependencyType.OPTIONAL,
                    descriptor.optional_dependencies,
                ),
            )
            for dependency_id in dependencies
        )
        order = {
            RuntimeFeatureDependencyType.REQUIRED: 0,
            RuntimeFeatureDependencyType.OPTIONAL: 1,
        }
        return tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.feature_id,
                    order[edge.dependency_type],
                    edge.dependency_id,
                ),
            )
        )

    @classmethod
    def _dependency_cycles(
        cls,
        feature_ids: tuple[str, ...],
        edges: tuple[RuntimeFeatureDependencyEdge, ...],
    ) -> tuple[RuntimeFeatureDependencyCycle, ...]:
        known = set(feature_ids)
        adjacency = {
            feature_id: tuple(
                edge.dependency_id
                for edge in edges
                if edge.feature_id == feature_id and edge.dependency_id in known
            )
            for feature_id in feature_ids
        }
        required_adjacency = {
            feature_id: tuple(
                edge.dependency_id
                for edge in edges
                if edge.feature_id == feature_id
                and edge.dependency_id in known
                and edge.dependency_type is RuntimeFeatureDependencyType.REQUIRED
            )
            for feature_id in feature_ids
        }
        required_components = cls._cycles(
            tuple(sorted(feature_ids)),
            required_adjacency,
        )
        all_components = cls._cycles(tuple(sorted(feature_ids)), adjacency)
        result = [
            RuntimeFeatureDependencyCycle(
                feature_ids=component,
                required_only=True,
            )
            for component in required_components
        ]
        result.extend(
            RuntimeFeatureDependencyCycle(
                feature_ids=component,
                required_only=False,
            )
            for component in all_components
            if component not in required_components
        )
        return tuple(
            sorted(result, key=lambda item: (item.feature_ids, not item.required_only))
        )

    @classmethod
    def _parent_cycles(
        cls,
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
    ) -> tuple[tuple[str, ...], ...]:
        known = set(descriptors)
        adjacency = {
            feature_id: (
                (descriptor.parent_feature_id,)
                if descriptor.parent_feature_id in known
                else ()
            )
            for feature_id, descriptor in descriptors.items()
        }
        return cls._cycles(tuple(sorted(descriptors)), adjacency)

    @classmethod
    def _category_cycles(
        cls,
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
    ) -> tuple[tuple[str, ...], ...]:
        categories = {
            descriptor.category for descriptor in descriptors.values()
        } | {
            descriptor.category_parent
            for descriptor in descriptors.values()
            if descriptor.category_parent is not None
        }
        parent_by_category: dict[str, set[str]] = {
            category: set() for category in categories
        }
        for descriptor in descriptors.values():
            if descriptor.category_parent is not None:
                parent_by_category[descriptor.category].add(
                    descriptor.category_parent
                )
        adjacency = {
            category: tuple(sorted(parents))
            for category, parents in parent_by_category.items()
        }
        return cls._cycles(tuple(sorted(categories)), adjacency)

    @staticmethod
    def _cycles(
        node_ids: tuple[str, ...],
        adjacency: Mapping[str, tuple[str, ...]],
    ) -> tuple[tuple[str, ...], ...]:
        index = 0
        indexes: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[tuple[str, ...]] = []

        def visit(node_id: str) -> None:
            nonlocal index
            indexes[node_id] = index
            lowlinks[node_id] = index
            index += 1
            stack.append(node_id)
            on_stack.add(node_id)
            for target in sorted(adjacency.get(node_id, ())):
                if target not in indexes:
                    visit(target)
                    lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
                elif target in on_stack:
                    lowlinks[node_id] = min(lowlinks[node_id], indexes[target])
            if lowlinks[node_id] != indexes[node_id]:
                return
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node_id:
                    break
            normalized = tuple(sorted(component))
            if len(normalized) > 1 or node_id in adjacency.get(node_id, ()):
                components.append(normalized)

        for node_id in node_ids:
            if node_id not in indexes:
                visit(node_id)
        return tuple(sorted(components))

    @staticmethod
    def _category_hierarchy(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
    ) -> tuple[Mapping[str, tuple[str, ...]], tuple[tuple[str, ...], ...]]:
        children: dict[str, set[str]] = {}
        parents: dict[str, set[str]] = {}
        for descriptor in descriptors.values():
            if descriptor.category_parent is None:
                continue
            children.setdefault(descriptor.category_parent, set()).add(
                descriptor.category
            )
            parents.setdefault(descriptor.category, set()).add(
                descriptor.category_parent
            )
        hierarchy = {
            parent: tuple(sorted(values))
            for parent, values in sorted(children.items())
        }
        conflicts = tuple(
            sorted(
                (category, *sorted(values))
                for category, values in parents.items()
                if len(values) > 1
            )
        )
        return hierarchy, conflicts

    @staticmethod
    def _feature_groups(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
    ) -> Mapping[str, tuple[str, ...]]:
        groups: dict[str, list[str]] = {}
        for feature_id, descriptor in descriptors.items():
            for group in descriptor.groups:
                groups.setdefault(group, []).append(feature_id)
        return {
            group: tuple(sorted(feature_ids))
            for group, feature_ids in sorted(groups.items())
        }

    @staticmethod
    def _relationships(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
    ) -> tuple[RuntimeFeatureRelationship, ...]:
        return tuple(
            RuntimeFeatureRelationship(
                feature_id=feature_id,
                depends_on=descriptor.depends_on,
                optional_dependencies=descriptor.optional_dependencies,
                required_by=tuple(
                    sorted(
                        source_id
                        for source_id, source in descriptors.items()
                        if feature_id in source.depends_on
                    )
                ),
                optionally_required_by=tuple(
                    sorted(
                        source_id
                        for source_id, source in descriptors.items()
                        if feature_id in source.optional_dependencies
                    )
                ),
                compatible_with=descriptor.compatible_with,
                conflicts_with=descriptor.conflicts_with,
                parent_feature_id=descriptor.parent_feature_id,
                child_feature_ids=tuple(
                    sorted(
                        child_id
                        for child_id, child in descriptors.items()
                        if child.parent_feature_id == feature_id
                    )
                ),
                category=descriptor.category,
                category_parent=descriptor.category_parent,
                groups=descriptor.groups,
            )
            for feature_id, descriptor in sorted(descriptors.items())
        )

    @staticmethod
    def _compatibility_report(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
        diagnostics_timestamp: datetime | None,
    ) -> RuntimeFeatureCompatibilityReport:
        compatible: set[tuple[str, str]] = set()
        conflicting: set[tuple[str, str]] = set()
        missing: set[tuple[str, str, str]] = set()
        asymmetric: set[tuple[str, str]] = set()
        for feature_id, descriptor in descriptors.items():
            for target in descriptor.compatible_with:
                if target not in descriptors:
                    missing.add((feature_id, target, "compatible_with"))
                    continue
                compatible.add(_pair(feature_id, target))
                if feature_id not in descriptors[target].compatible_with:
                    asymmetric.add((feature_id, target))
            for target in descriptor.conflicts_with:
                if target not in descriptors:
                    missing.add((feature_id, target, "conflicts_with"))
                    continue
                conflicting.add(_pair(feature_id, target))
        contradictory = compatible & conflicting
        active_conflicts = {
            pair
            for pair in conflicting
            if all(
                descriptors[feature_id].availability
                is not RuntimeFeatureAvailability.UNAVAILABLE
                for feature_id in pair
            )
        }
        if active_conflicts or contradictory:
            status = RuntimeFeatureCompatibilityStatus.INCOMPATIBLE
        elif missing or asymmetric:
            status = RuntimeFeatureCompatibilityStatus.DEGRADED
        else:
            status = RuntimeFeatureCompatibilityStatus.COMPATIBLE
        return RuntimeFeatureCompatibilityReport(
            status=status,
            compatible_pairs=tuple(sorted(compatible)),
            conflicting_pairs=tuple(sorted(conflicting)),
            active_conflicts=tuple(sorted(active_conflicts)),
            missing_references=tuple(sorted(missing)),
            asymmetric_compatibilities=tuple(sorted(asymmetric)),
            contradictory_relationships=tuple(sorted(contradictory)),
            diagnostics_timestamp=diagnostics_timestamp,
        )

    @staticmethod
    def _readiness(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
        cycles: tuple[RuntimeFeatureDependencyCycle, ...],
        parent_cycles: tuple[tuple[str, ...], ...],
        compatibility: RuntimeFeatureCompatibilityReport,
    ) -> Mapping[str, RuntimeFeatureAvailability]:
        readiness = {
            feature_id: descriptor.availability
            for feature_id, descriptor in descriptors.items()
        }
        required_cycle_ids = {
            feature_id
            for cycle in cycles
            if cycle.required_only
            for feature_id in cycle.feature_ids
        }
        parent_cycle_ids = {
            feature_id for cycle in parent_cycles for feature_id in cycle
        }
        conflict_ids = {
            feature_id
            for pair in compatibility.active_conflicts
            for feature_id in pair
        }
        for feature_id, descriptor in descriptors.items():
            missing_required = set(descriptor.depends_on) - set(descriptors)
            parent_missing = (
                descriptor.parent_feature_id is not None
                and descriptor.parent_feature_id not in descriptors
            )
            if (
                missing_required
                or parent_missing
                or feature_id in required_cycle_ids
                or feature_id in parent_cycle_ids
                or feature_id in conflict_ids
            ):
                readiness[feature_id] = RuntimeFeatureAvailability.UNAVAILABLE

        changed = True
        while changed:
            changed = False
            for feature_id, descriptor in sorted(descriptors.items()):
                if readiness[feature_id] is RuntimeFeatureAvailability.UNAVAILABLE:
                    continue
                required = tuple(
                    dependency
                    for dependency in descriptor.depends_on
                    if dependency in readiness
                )
                if descriptor.parent_feature_id in readiness:
                    required = (*required, descriptor.parent_feature_id)  # type: ignore[arg-type]
                states = tuple(readiness[dependency] for dependency in required)
                next_state = readiness[feature_id]
                if RuntimeFeatureAvailability.UNAVAILABLE in states:
                    next_state = RuntimeFeatureAvailability.UNAVAILABLE
                elif (
                    RuntimeFeatureAvailability.CONDITIONAL in states
                    and next_state is RuntimeFeatureAvailability.AVAILABLE
                ):
                    next_state = RuntimeFeatureAvailability.CONDITIONAL
                if next_state is not readiness[feature_id]:
                    readiness[feature_id] = next_state
                    changed = True
        return MappingProxyType(readiness)

    @classmethod
    def _validation_report(
        cls,
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
        edges: tuple[RuntimeFeatureDependencyEdge, ...],
        cycles: tuple[RuntimeFeatureDependencyCycle, ...],
        parent_cycles: tuple[tuple[str, ...], ...],
        category_cycles: tuple[tuple[str, ...], ...],
        category_parent_conflicts: tuple[tuple[str, ...], ...],
        compatibility: RuntimeFeatureCompatibilityReport,
        readiness: Mapping[str, RuntimeFeatureAvailability],
        diagnostics_timestamp: datetime | None,
    ) -> RuntimeDependencyValidationReport:
        known = set(descriptors)
        missing_required = tuple(
            edge
            for edge in edges
            if edge.dependency_type is RuntimeFeatureDependencyType.REQUIRED
            and edge.dependency_id not in known
        )
        missing_optional = tuple(
            edge
            for edge in edges
            if edge.dependency_type is RuntimeFeatureDependencyType.OPTIONAL
            and edge.dependency_id not in known
        )
        missing_parents = tuple(
            sorted(
                (feature_id, descriptor.parent_feature_id)
                for feature_id, descriptor in descriptors.items()
                if descriptor.parent_feature_id is not None
                and descriptor.parent_feature_id not in known
            )
        )
        cycle_ids = {
            feature_id for cycle in cycles for feature_id in cycle.feature_ids
        } | {feature_id for cycle in parent_cycles for feature_id in cycle}
        blocking_cycle_ids = {
            feature_id
            for cycle in cycles
            if cycle.required_only
            for feature_id in cycle.feature_ids
        } | {feature_id for cycle in parent_cycles for feature_id in cycle}
        conflict_map: dict[str, set[str]] = {
            feature_id: set() for feature_id in descriptors
        }
        for first, second in compatibility.active_conflicts:
            conflict_map[first].add(second)
            conflict_map[second].add(first)
        results = []
        for feature_id, descriptor in sorted(descriptors.items()):
            missing_feature_required = tuple(
                dependency
                for dependency in descriptor.depends_on
                if dependency not in known
            )
            missing_feature_optional = tuple(
                dependency
                for dependency in descriptor.optional_dependencies
                if dependency not in known
            )
            unavailable_required = tuple(
                sorted(
                    (
                        *(
                            dependency
                            for dependency in descriptor.depends_on
                            if dependency in readiness
                            and readiness[dependency]
                            is RuntimeFeatureAvailability.UNAVAILABLE
                        ),
                        *(
                            (descriptor.parent_feature_id,)
                            if descriptor.parent_feature_id in readiness
                            and readiness[descriptor.parent_feature_id]
                            is RuntimeFeatureAvailability.UNAVAILABLE
                            else ()
                        ),
                    )
                )
            )
            parent_missing = (
                descriptor.parent_feature_id is not None
                and descriptor.parent_feature_id not in known
            )
            feature_readiness = readiness[feature_id]
            invalid = any(
                (
                    missing_feature_required,
                    unavailable_required,
                    conflict_map[feature_id],
                    feature_id in blocking_cycle_ids,
                    parent_missing,
                )
            )
            degraded = any(
                (
                    missing_feature_optional,
                    feature_readiness is RuntimeFeatureAvailability.CONDITIONAL,
                    feature_readiness is RuntimeFeatureAvailability.UNAVAILABLE,
                    feature_id in cycle_ids - blocking_cycle_ids,
                )
            )
            status = (
                RuntimeFeatureValidationStatus.INVALID
                if invalid
                else (
                    RuntimeFeatureValidationStatus.DEGRADED
                    if degraded
                    else RuntimeFeatureValidationStatus.VALID
                )
            )
            issues = sum(
                (
                    len(missing_feature_required),
                    len(missing_feature_optional),
                    len(unavailable_required),
                    len(conflict_map[feature_id]),
                    int(feature_id in cycle_ids),
                    int(parent_missing),
                )
            )
            results.append(
                RuntimeFeatureValidationResult(
                    feature_id=feature_id,
                    status=status,
                    readiness=feature_readiness,
                    missing_required_dependencies=missing_feature_required,
                    missing_optional_dependencies=missing_feature_optional,
                    unavailable_required_dependencies=unavailable_required,
                    conflicting_features=tuple(sorted(conflict_map[feature_id])),
                    circular_dependency=feature_id in cycle_ids,
                    parent_missing=parent_missing,
                    summary=(
                        f"Feature dependency metadata reports {status.value}: "
                        f"{issues} issue{'s' if issues != 1 else ''}."
                    ),
                )
            )
        if (
            missing_required
            or missing_parents
            or any(cycle.required_only for cycle in cycles)
            or parent_cycles
            or category_cycles
            or category_parent_conflicts
            or compatibility.status
            is RuntimeFeatureCompatibilityStatus.INCOMPATIBLE
        ):
            status = RuntimeFeatureValidationStatus.INVALID
        elif (
            missing_optional
            or compatibility.status is RuntimeFeatureCompatibilityStatus.DEGRADED
            or cycles
            or any(
                result.status is RuntimeFeatureValidationStatus.DEGRADED
                for result in results
            )
        ):
            status = RuntimeFeatureValidationStatus.DEGRADED
        else:
            status = RuntimeFeatureValidationStatus.VALID
        return RuntimeDependencyValidationReport(
            status=status,
            feature_results=tuple(results),
            missing_required_dependencies=missing_required,
            missing_optional_dependencies=missing_optional,
            missing_parents=missing_parents,
            circular_dependencies=cycles,
            parent_cycles=parent_cycles,
            category_cycles=category_cycles,
            category_parent_conflicts=category_parent_conflicts,
            ready_feature_ids=tuple(
                sorted(
                    feature_id
                    for feature_id, value in readiness.items()
                    if value is RuntimeFeatureAvailability.AVAILABLE
                )
            ),
            conditional_feature_ids=tuple(
                sorted(
                    feature_id
                    for feature_id, value in readiness.items()
                    if value is RuntimeFeatureAvailability.CONDITIONAL
                )
            ),
            unavailable_feature_ids=tuple(
                sorted(
                    feature_id
                    for feature_id, value in readiness.items()
                    if value is RuntimeFeatureAvailability.UNAVAILABLE
                )
            ),
            diagnostics_timestamp=diagnostics_timestamp,
        )

    @staticmethod
    def _nodes(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
        readiness: Mapping[str, RuntimeFeatureAvailability],
    ) -> tuple[RuntimeFeatureGraphNode, ...]:
        return tuple(
            RuntimeFeatureGraphNode(
                feature_id=feature_id,
                parent_feature_id=descriptor.parent_feature_id,
                child_feature_ids=tuple(
                    sorted(
                        child_id
                        for child_id, child in descriptors.items()
                        if child.parent_feature_id == feature_id
                    )
                ),
                required_dependencies=descriptor.depends_on,
                optional_dependencies=descriptor.optional_dependencies,
                required_by=tuple(
                    sorted(
                        source_id
                        for source_id, source in descriptors.items()
                        if feature_id in source.depends_on
                    )
                ),
                optionally_required_by=tuple(
                    sorted(
                        source_id
                        for source_id, source in descriptors.items()
                        if feature_id in source.optional_dependencies
                    )
                ),
                readiness=readiness[feature_id],
            )
            for feature_id, descriptor in sorted(descriptors.items())
        )

    @staticmethod
    def _topological_order(
        descriptors: Mapping[str, RuntimeFeatureDescriptor],
        cycles: tuple[RuntimeFeatureDependencyCycle, ...],
        parent_cycles: tuple[tuple[str, ...], ...],
    ) -> tuple[str, ...]:
        known = set(descriptors)
        dependencies = {
            feature_id: {
                dependency
                for dependency in descriptor.depends_on
                if dependency in known
            }
            for feature_id, descriptor in descriptors.items()
        }
        for feature_id, descriptor in descriptors.items():
            if descriptor.parent_feature_id in known:
                dependencies[feature_id].add(descriptor.parent_feature_id)  # type: ignore[arg-type]
        remaining = set(descriptors)
        ordered: list[str] = []
        while remaining:
            ready = sorted(
                feature_id
                for feature_id in remaining
                if not (dependencies[feature_id] & remaining)
            )
            if not ready:
                ordered.extend(sorted(remaining))
                break
            ordered.extend(ready)
            remaining.difference_update(ready)
        return tuple(ordered)


def build_runtime_dependency_graph(
    feature_registry: RuntimeFeatureRegistry,
) -> RuntimeDependencyGraph:
    """Build the passive dependency graph service for an existing registry."""

    return RuntimeDependencyGraph(feature_registry)


__all__ = [
    "RUNTIME_CONFIGURATION_VERSION",
    "RUNTIME_DEPENDENCY_GRAPH_VERSION",
    "RUNTIME_PROFILE_REGISTRY_VERSION",
    "RuntimeDependencyGraph",
    "RuntimeDependencyGraphSnapshot",
    "RuntimeDependencyGraphValidationReport",
    "RuntimeDependencyValidationReport",
    "RuntimeFeatureCompatibilityReport",
    "RuntimeFeatureCompatibilityStatus",
    "RuntimeFeatureDependency",
    "RuntimeFeatureDependencyCycle",
    "RuntimeFeatureDependencyEdge",
    "RuntimeFeatureDependencyType",
    "RuntimeFeatureGraphNode",
    "RuntimeFeatureRelationship",
    "RuntimeFeatureRelationshipSummary",
    "RuntimeFeatureValidationResult",
    "RuntimeFeatureValidationStatus",
    "build_runtime_dependency_graph",
]
