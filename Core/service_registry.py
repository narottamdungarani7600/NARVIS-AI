"""Passive runtime service registry and dependency-health reporting.

The registry reads immutable dependency-injection and lifecycle metadata only.
It never resolves services, invokes factories, probes health, or executes
component callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from .runtime_metadata import RUNTIME_SERVICE_REGISTRY_VERSION
from .system import ComponentState, ServiceRegistrationMetadata


class RuntimeHealthStatus(str, Enum):
    """Deterministic runtime and dependency health classifications."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INITIALIZING = "initializing"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RuntimeLifecycleState(str, Enum):
    """Lifecycle metadata states observed by passive runtime services."""

    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RuntimeCompatibilityStatus(str, Enum):
    """Compatibility classifications derived from registration metadata."""

    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    INCOMPATIBLE = "incompatible"
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


def _names(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of service names")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of service names") from error
    for value in result:
        _text(value, name, maximum=128)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


@dataclass(slots=True, frozen=True)
class RuntimeServiceDependency:
    """One immutable declared dependency edge."""

    service_name: str
    dependency_name: str
    registered: bool

    def __post_init__(self) -> None:
        _text(self.service_name, "service_name", maximum=128)
        _text(self.dependency_name, "dependency_name", maximum=128)
        if not isinstance(self.registered, bool):
            raise TypeError("registered must be a bool")


@dataclass(slots=True, frozen=True)
class RuntimeDependencyGraphSummary:
    """Immutable aggregate of declared registration dependency edges."""

    service_count: int
    dependency_count: int
    satisfied_dependency_count: int
    missing_dependency_count: int
    dependencies: tuple[RuntimeServiceDependency, ...]
    cyclic_services: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "service_count",
            "dependency_count",
            "satisfied_dependency_count",
            "missing_dependency_count",
        ):
            _count(getattr(self, name), name)
        dependencies = tuple(self.dependencies)
        if not all(
            isinstance(dependency, RuntimeServiceDependency)
            for dependency in dependencies
        ):
            raise TypeError("dependencies must contain RuntimeServiceDependency values")
        if self.dependency_count != len(dependencies):
            raise ValueError("dependency_count must match dependencies")
        if (
            self.satisfied_dependency_count + self.missing_dependency_count
            != self.dependency_count
        ):
            raise ValueError("dependency counts must account for every edge")
        if self.satisfied_dependency_count != sum(
            dependency.registered for dependency in dependencies
        ):
            raise ValueError("satisfied_dependency_count does not match edges")
        cyclic = _names(self.cyclic_services, "cyclic_services")
        if tuple(sorted(cyclic)) != cyclic:
            raise ValueError("cyclic_services must be sorted")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "cyclic_services", cyclic)


@dataclass(slots=True, frozen=True)
class RuntimeServiceRecord:
    """Immutable metadata and derived health for one DI registration."""

    service_name: str
    service_type: str
    registration_order: int
    lifecycle_state: RuntimeLifecycleState
    dependencies: tuple[str, ...]
    dependency_count: int
    registration_source: str
    health_state: RuntimeHealthStatus
    compatibility_status: RuntimeCompatibilityStatus
    runtime_available: bool
    initialization_timestamp: datetime | None

    def __post_init__(self) -> None:
        _text(self.service_name, "service_name", maximum=128)
        _text(self.service_type, "service_type")
        _text(self.registration_source, "registration_source", maximum=256)
        if (
            isinstance(self.registration_order, bool)
            or not isinstance(self.registration_order, int)
            or self.registration_order < 1
        ):
            raise ValueError("registration_order must be a positive integer")
        dependencies = _names(self.dependencies, "dependencies")
        if tuple(sorted(dependencies)) != dependencies:
            raise ValueError("dependencies must be sorted")
        _count(self.dependency_count, "dependency_count")
        if self.dependency_count != len(dependencies):
            raise ValueError("dependency_count must match dependencies")
        if not isinstance(self.lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        if not isinstance(self.health_state, RuntimeHealthStatus):
            raise TypeError("health_state must be a RuntimeHealthStatus")
        if not isinstance(self.compatibility_status, RuntimeCompatibilityStatus):
            raise TypeError(
                "compatibility_status must be a RuntimeCompatibilityStatus"
            )
        if not isinstance(self.runtime_available, bool):
            raise TypeError("runtime_available must be a bool")
        if self.initialization_timestamp is not None:
            _time(self.initialization_timestamp, "initialization_timestamp")
        object.__setattr__(self, "dependencies", dependencies)


@dataclass(slots=True, frozen=True)
class RuntimeCompatibilitySummary:
    """Immutable compatibility counts and combined runtime status."""

    status: RuntimeCompatibilityStatus
    runtime_status: RuntimeCompatibilityStatus
    compatible_services: int
    degraded_services: int
    incompatible_services: int
    unknown_services: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeCompatibilityStatus):
            raise TypeError("status must be a RuntimeCompatibilityStatus")
        if not isinstance(self.runtime_status, RuntimeCompatibilityStatus):
            raise TypeError("runtime_status must be a RuntimeCompatibilityStatus")
        for name in (
            "compatible_services",
            "degraded_services",
            "incompatible_services",
            "unknown_services",
        ):
            _count(getattr(self, name), name)


@dataclass(slots=True, frozen=True)
class RuntimeDependencyHealthReport:
    """Deterministic aggregate service and dependency health report."""

    status: RuntimeHealthStatus
    total_services: int
    active_services: int
    inactive_services: int
    failed_services: int
    dependency_graph_summary: RuntimeDependencyGraphSummary
    compatibility_summary: RuntimeCompatibilitySummary
    diagnostics_timestamp: datetime
    summary: str
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeHealthStatus):
            raise TypeError("status must be a RuntimeHealthStatus")
        for name in (
            "total_services",
            "active_services",
            "inactive_services",
            "failed_services",
        ):
            _count(getattr(self, name), name)
        if self.active_services + self.inactive_services != self.total_services:
            raise ValueError("active and inactive counts must equal total services")
        if self.failed_services > self.total_services:
            raise ValueError("failed_services cannot exceed total_services")
        if not isinstance(
            self.dependency_graph_summary,
            RuntimeDependencyGraphSummary,
        ):
            raise TypeError(
                "dependency_graph_summary must be a RuntimeDependencyGraphSummary"
            )
        if not isinstance(self.compatibility_summary, RuntimeCompatibilitySummary):
            raise TypeError(
                "compatibility_summary must be a RuntimeCompatibilitySummary"
            )
        if self.dependency_graph_summary.service_count != self.total_services:
            raise ValueError("dependency graph service count must match total services")
        compatibility_total = sum(
            (
                self.compatibility_summary.compatible_services,
                self.compatibility_summary.degraded_services,
                self.compatibility_summary.incompatible_services,
                self.compatibility_summary.unknown_services,
            )
        )
        if compatibility_total != self.total_services:
            raise ValueError("compatibility counts must match total services")
        _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        _text(self.summary, "summary", maximum=2000)
        if self.calculated_from_metadata is not True:
            raise ValueError("dependency health must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("dependency health cannot use active probes")


@dataclass(slots=True, frozen=True)
class RuntimeServiceRegistrySnapshot:
    """Complete immutable snapshot of registered runtime service metadata."""

    services: tuple[RuntimeServiceRecord, ...]
    health: RuntimeDependencyHealthReport
    diagnostics_timestamp: datetime

    def __post_init__(self) -> None:
        services = tuple(self.services)
        if not all(isinstance(service, RuntimeServiceRecord) for service in services):
            raise TypeError("services must contain RuntimeServiceRecord values")
        orders = tuple(service.registration_order for service in services)
        if tuple(sorted(orders)) != orders or len(set(orders)) != len(orders):
            raise ValueError("services must have unique deterministic registration order")
        names = tuple(service.service_name for service in services)
        if len(set(names)) != len(names):
            raise ValueError("services cannot contain duplicate names")
        if not isinstance(self.health, RuntimeDependencyHealthReport):
            raise TypeError("health must be a RuntimeDependencyHealthReport")
        captured = _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        if self.health.diagnostics_timestamp != captured:
            raise ValueError("health and snapshot timestamps must match")
        if self.health.total_services != len(services):
            raise ValueError("health total must match services")
        object.__setattr__(self, "services", services)

    def get(self, service_name: str) -> RuntimeServiceRecord | None:
        """Return one retained service record without resolving the service."""

        _text(service_name, "service_name", maximum=128)
        return next(
            (
                service
                for service in self.services
                if service.service_name == service_name
            ),
            None,
        )


class ServiceRegistrationReader(Protocol):
    """Read-only dependency container metadata contract."""

    def service_registrations(self) -> tuple[ServiceRegistrationMetadata, ...]:
        """Return registrations without service resolution."""


class ComponentMetadataReader(Protocol):
    """Read-only lifecycle coordinator metadata contract."""

    def get_component(self, name: str) -> object | None:
        """Return a lifecycle component by name."""


class RuntimeServiceRegistry:
    """Build passive service records and dependency-health snapshots."""

    def __init__(
        self,
        registrations: ServiceRegistrationReader,
        components: ComponentMetadataReader,
    ) -> None:
        if not callable(getattr(registrations, "service_registrations", None)):
            raise TypeError("registrations must provide service_registrations")
        if not callable(getattr(components, "get_component", None)):
            raise TypeError("components must provide get_component")
        self._registrations = registrations
        self._components = components

    def snapshot(
        self,
        *,
        lifecycle_state: RuntimeLifecycleState,
        runtime_compatibility_status: RuntimeCompatibilityStatus,
        diagnostics_timestamp: datetime,
    ) -> RuntimeServiceRegistrySnapshot:
        """Return a deterministic snapshot from retained metadata only."""

        if not isinstance(lifecycle_state, RuntimeLifecycleState):
            raise TypeError("lifecycle_state must be a RuntimeLifecycleState")
        if not isinstance(
            runtime_compatibility_status,
            RuntimeCompatibilityStatus,
        ):
            raise TypeError(
                "runtime_compatibility_status must be a RuntimeCompatibilityStatus"
            )
        captured_at = _time(diagnostics_timestamp, "diagnostics_timestamp")
        registrations = tuple(self._registrations.service_registrations())
        self._validate_registrations(registrations)
        graph = self._dependency_graph(registrations)
        registered_names = {registration.service_name for registration in registrations}
        unavailable_names = {
            registration.service_name
            for registration in registrations
            if not registration.runtime_available
        }
        cyclic_names = set(graph.cyclic_services)
        records = tuple(
            self._record(
                registration,
                lifecycle_state=lifecycle_state,
                registered_names=registered_names,
                unavailable_names=unavailable_names,
                cyclic_names=cyclic_names,
            )
            for registration in registrations
        )
        compatibility = self._compatibility_summary(
            records,
            runtime_compatibility_status,
        )
        health = self._health_report(
            records,
            graph,
            compatibility,
            lifecycle_state=lifecycle_state,
            diagnostics_timestamp=captured_at,
        )
        return RuntimeServiceRegistrySnapshot(
            services=records,
            health=health,
            diagnostics_timestamp=captured_at,
        )

    def _record(
        self,
        registration: ServiceRegistrationMetadata,
        *,
        lifecycle_state: RuntimeLifecycleState,
        registered_names: set[str],
        unavailable_names: set[str],
        cyclic_names: set[str],
    ) -> RuntimeServiceRecord:
        service_lifecycle = self._service_lifecycle(registration, lifecycle_state)
        compatibility = RuntimeCompatibilityStatus(
            registration.compatibility_status
        )
        missing_dependency = any(
            dependency not in registered_names
            for dependency in registration.dependencies
        )
        unavailable_dependency = any(
            dependency in unavailable_names
            for dependency in registration.dependencies
        )
        health = self._service_health(
            lifecycle_state=service_lifecycle,
            runtime_available=registration.runtime_available,
            compatible=compatibility is RuntimeCompatibilityStatus.COMPATIBLE,
            dependency_degraded=(
                missing_dependency
                or unavailable_dependency
                or registration.service_name in cyclic_names
            ),
        )
        return RuntimeServiceRecord(
            service_name=registration.service_name,
            service_type=registration.service_type,
            registration_order=registration.registration_order,
            lifecycle_state=service_lifecycle,
            dependencies=registration.dependencies,
            dependency_count=len(registration.dependencies),
            registration_source=registration.registration_source,
            health_state=health,
            compatibility_status=compatibility,
            runtime_available=registration.runtime_available,
            initialization_timestamp=registration.initialization_timestamp,
        )

    def _service_lifecycle(
        self,
        registration: ServiceRegistrationMetadata,
        runtime_state: RuntimeLifecycleState,
    ) -> RuntimeLifecycleState:
        if runtime_state is not RuntimeLifecycleState.RUNNING:
            return runtime_state
        component = self._components.get_component(
            registration.lifecycle_component
        )
        if component is None:
            return (
                RuntimeLifecycleState.RUNNING
                if registration.initialization_timestamp is not None
                else RuntimeLifecycleState.INITIALIZING
            )
        component_state = getattr(component, "state", None)
        states = {
            ComponentState.NEW: RuntimeLifecycleState.INITIALIZING,
            ComponentState.INITIALIZED: RuntimeLifecycleState.RUNNING,
            ComponentState.RUNNING: RuntimeLifecycleState.RUNNING,
            ComponentState.STOPPED: RuntimeLifecycleState.STOPPED,
        }
        return states.get(component_state, RuntimeLifecycleState.UNKNOWN)

    @staticmethod
    def _service_health(
        *,
        lifecycle_state: RuntimeLifecycleState,
        runtime_available: bool,
        compatible: bool,
        dependency_degraded: bool,
    ) -> RuntimeHealthStatus:
        terminal = {
            RuntimeLifecycleState.INITIALIZING: RuntimeHealthStatus.INITIALIZING,
            RuntimeLifecycleState.STOPPED: RuntimeHealthStatus.STOPPED,
            RuntimeLifecycleState.FAILED: RuntimeHealthStatus.FAILED,
            RuntimeLifecycleState.UNKNOWN: RuntimeHealthStatus.UNKNOWN,
        }
        if lifecycle_state in terminal:
            return terminal[lifecycle_state]
        if not runtime_available:
            return RuntimeHealthStatus.FAILED
        if not compatible or dependency_degraded:
            return RuntimeHealthStatus.DEGRADED
        return RuntimeHealthStatus.HEALTHY

    @staticmethod
    def _dependency_graph(
        registrations: tuple[ServiceRegistrationMetadata, ...],
    ) -> RuntimeDependencyGraphSummary:
        registered_names = {registration.service_name for registration in registrations}
        edges = tuple(
            RuntimeServiceDependency(
                service_name=registration.service_name,
                dependency_name=dependency,
                registered=dependency in registered_names,
            )
            for registration in registrations
            for dependency in registration.dependencies
        )
        cyclic = RuntimeServiceRegistry._cyclic_services(registrations)
        satisfied = sum(edge.registered for edge in edges)
        return RuntimeDependencyGraphSummary(
            service_count=len(registrations),
            dependency_count=len(edges),
            satisfied_dependency_count=satisfied,
            missing_dependency_count=len(edges) - satisfied,
            dependencies=edges,
            cyclic_services=cyclic,
        )

    @staticmethod
    def _cyclic_services(
        registrations: tuple[ServiceRegistrationMetadata, ...],
    ) -> tuple[str, ...]:
        names = {registration.service_name for registration in registrations}
        graph = {
            registration.service_name: tuple(
                dependency
                for dependency in registration.dependencies
                if dependency in names
            )
            for registration in registrations
        }
        visited: set[str] = set()
        visiting: set[str] = set()
        cyclic: set[str] = set()

        def visit(service_name: str, path: tuple[str, ...]) -> None:
            if service_name in visiting:
                cycle_start = path.index(service_name)
                cyclic.update(path[cycle_start:])
                return
            if service_name in visited:
                return
            visiting.add(service_name)
            current_path = (*path, service_name)
            for dependency in graph[service_name]:
                visit(dependency, current_path)
            visiting.remove(service_name)
            visited.add(service_name)

        for service_name in graph:
            visit(service_name, ())
        return tuple(sorted(cyclic))

    @staticmethod
    def _compatibility_summary(
        records: tuple[RuntimeServiceRecord, ...],
        runtime_status: RuntimeCompatibilityStatus,
    ) -> RuntimeCompatibilitySummary:
        counts = {
            status: sum(
                record.compatibility_status is status
                for record in records
            )
            for status in RuntimeCompatibilityStatus
        }
        if counts[RuntimeCompatibilityStatus.INCOMPATIBLE]:
            registration_status = RuntimeCompatibilityStatus.INCOMPATIBLE
        elif counts[RuntimeCompatibilityStatus.DEGRADED]:
            registration_status = RuntimeCompatibilityStatus.DEGRADED
        elif counts[RuntimeCompatibilityStatus.UNKNOWN]:
            registration_status = RuntimeCompatibilityStatus.UNKNOWN
        else:
            registration_status = RuntimeCompatibilityStatus.COMPATIBLE
        status = RuntimeServiceRegistry._combine_compatibility(
            runtime_status,
            registration_status,
        )
        return RuntimeCompatibilitySummary(
            status=status,
            runtime_status=runtime_status,
            compatible_services=counts[RuntimeCompatibilityStatus.COMPATIBLE],
            degraded_services=counts[RuntimeCompatibilityStatus.DEGRADED],
            incompatible_services=counts[RuntimeCompatibilityStatus.INCOMPATIBLE],
            unknown_services=counts[RuntimeCompatibilityStatus.UNKNOWN],
        )

    @staticmethod
    def _combine_compatibility(
        first: RuntimeCompatibilityStatus,
        second: RuntimeCompatibilityStatus,
    ) -> RuntimeCompatibilityStatus:
        if RuntimeCompatibilityStatus.INCOMPATIBLE in (first, second):
            return RuntimeCompatibilityStatus.INCOMPATIBLE
        if RuntimeCompatibilityStatus.DEGRADED in (first, second):
            return RuntimeCompatibilityStatus.DEGRADED
        if RuntimeCompatibilityStatus.UNKNOWN in (first, second):
            return RuntimeCompatibilityStatus.UNKNOWN
        return RuntimeCompatibilityStatus.COMPATIBLE

    @staticmethod
    def _health_report(
        records: tuple[RuntimeServiceRecord, ...],
        graph: RuntimeDependencyGraphSummary,
        compatibility: RuntimeCompatibilitySummary,
        *,
        lifecycle_state: RuntimeLifecycleState,
        diagnostics_timestamp: datetime,
    ) -> RuntimeDependencyHealthReport:
        total = len(records)
        active = sum(
            record.lifecycle_state is RuntimeLifecycleState.RUNNING
            and record.runtime_available
            for record in records
        )
        failed = sum(
            record.health_state is RuntimeHealthStatus.FAILED
            for record in records
        )
        terminal = {
            RuntimeLifecycleState.INITIALIZING: RuntimeHealthStatus.INITIALIZING,
            RuntimeLifecycleState.STOPPED: RuntimeHealthStatus.STOPPED,
            RuntimeLifecycleState.FAILED: RuntimeHealthStatus.FAILED,
            RuntimeLifecycleState.UNKNOWN: RuntimeHealthStatus.UNKNOWN,
        }
        if lifecycle_state in terminal:
            status = terminal[lifecycle_state]
        elif not records:
            status = RuntimeHealthStatus.UNKNOWN
        elif failed:
            status = RuntimeHealthStatus.FAILED
        elif (
            all(
                record.health_state is RuntimeHealthStatus.HEALTHY
                for record in records
            )
            and graph.missing_dependency_count == 0
            and not graph.cyclic_services
            and compatibility.status is RuntimeCompatibilityStatus.COMPATIBLE
        ):
            status = RuntimeHealthStatus.HEALTHY
        else:
            status = RuntimeHealthStatus.DEGRADED
        inactive = total - active
        summary = (
            f"Runtime service metadata reports {status.value}: "
            f"{total} total, {active} active, {inactive} inactive, "
            f"{failed} failed, {graph.missing_dependency_count} missing "
            f"dependencies, compatibility {compatibility.status.value}."
        )
        return RuntimeDependencyHealthReport(
            status=status,
            total_services=total,
            active_services=active,
            inactive_services=inactive,
            failed_services=failed,
            dependency_graph_summary=graph,
            compatibility_summary=compatibility,
            diagnostics_timestamp=diagnostics_timestamp,
            summary=summary,
        )

    @staticmethod
    def _validate_registrations(
        registrations: tuple[ServiceRegistrationMetadata, ...],
    ) -> None:
        if not all(
            isinstance(registration, ServiceRegistrationMetadata)
            for registration in registrations
        ):
            raise TypeError(
                "service_registrations must contain ServiceRegistrationMetadata"
            )
        names = tuple(registration.service_name for registration in registrations)
        orders = tuple(
            registration.registration_order for registration in registrations
        )
        if len(set(names)) != len(names):
            raise ValueError("service registrations cannot contain duplicate names")
        if len(set(orders)) != len(orders) or tuple(sorted(orders)) != orders:
            raise ValueError("service registrations must be in deterministic order")


__all__ = [
    "RUNTIME_SERVICE_REGISTRY_VERSION",
    "RuntimeCompatibilityStatus",
    "RuntimeCompatibilitySummary",
    "RuntimeDependencyGraphSummary",
    "RuntimeDependencyHealthReport",
    "RuntimeHealthStatus",
    "RuntimeLifecycleState",
    "RuntimeServiceDependency",
    "RuntimeServiceRecord",
    "RuntimeServiceRegistry",
    "RuntimeServiceRegistrySnapshot",
]
