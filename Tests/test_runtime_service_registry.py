"""Focused tests for Version 1.4 Milestone 3 Sprint 2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest import mock
from uuid import uuid4

from Core import (
    RUNTIME_DIAGNOSTICS_STARTED_EVENT,
    RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
    RuntimeBuildMetadata,
    RuntimeCompatibilityStatus,
    RuntimeDiagnostics,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeServiceRegistry,
    RuntimeServiceRegistrySnapshot,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator
from narvis import NARVISApplication, NARVISConfig


class _Clock:
    """Deterministic timestamp source for registration and diagnostics metadata."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class _Logger:
    def log(self, level: object, message: str, **context: object) -> None:
        return None


class RuntimeServiceRegistrationTests(unittest.TestCase):
    """Verify DI metadata retention without service instantiation."""

    def test_registration_order_type_source_and_timestamps_are_deterministic(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        factory_calls = 0

        def factory() -> object:
            nonlocal factory_calls
            factory_calls += 1
            return object()

        first = object()
        container.register_instance(
            "zeta",
            first,
            registration_source="test.composition",
        )
        clock.advance(1)
        container.register_factory(
            "alpha",
            factory,
            service_type="tests.AlphaService",
            dependencies=("zeta",),
            registration_source="test.factory",
        )
        registrations = container.service_registrations()

        self.assertEqual(
            tuple(registration.service_name for registration in registrations),
            ("zeta", "alpha"),
        )
        self.assertEqual(
            tuple(registration.registration_order for registration in registrations),
            (1, 2),
        )
        self.assertEqual(registrations[0].service_type, "builtins.object")
        self.assertEqual(registrations[0].registration_source, "test.composition")
        self.assertEqual(registrations[0].initialization_timestamp, clock.now - timedelta(seconds=1))
        self.assertEqual(registrations[1].service_type, "tests.AlphaService")
        self.assertEqual(registrations[1].dependencies, ("zeta",))
        self.assertIsNone(registrations[1].initialization_timestamp)
        self.assertEqual(factory_calls, 0)

        container.register_instance("zeta", object())
        self.assertEqual(container.service_registrations()[0].registration_order, 1)

    def test_registry_snapshot_never_resolves_or_invokes_factories(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        factory_calls = 0

        def forbidden_factory() -> object:
            nonlocal factory_calls
            factory_calls += 1
            raise AssertionError("registry must not instantiate services")

        container.register_instance("ready", object())
        container.register_factory(
            "lazy",
            forbidden_factory,
            dependencies=("ready",),
        )
        registry = RuntimeServiceRegistry(container, SystemCoordinator())

        snapshot = registry.snapshot(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            runtime_compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            diagnostics_timestamp=clock.now,
        )

        self.assertEqual(factory_calls, 0)
        self.assertEqual(snapshot.get("lazy").dependency_count, 1)  # type: ignore[union-attr]
        self.assertIs(
            snapshot.get("lazy").health_state,  # type: ignore[union-attr]
            RuntimeHealthStatus.INITIALIZING,
        )
        self.assertEqual(snapshot.health.total_services, 2)


class RuntimeServiceRegistryModelTests(unittest.TestCase):
    """Verify immutable records and deterministic aggregate calculations."""

    def _snapshot(
        self,
        container: DependencyContainer,
        *,
        lifecycle: RuntimeLifecycleState = RuntimeLifecycleState.RUNNING,
        compatibility: RuntimeCompatibilityStatus = RuntimeCompatibilityStatus.COMPATIBLE,
        coordinator: SystemCoordinator | None = None,
        at: datetime | None = None,
    ) -> RuntimeServiceRegistrySnapshot:
        return RuntimeServiceRegistry(
            container,
            coordinator or SystemCoordinator(),
        ).snapshot(
            lifecycle_state=lifecycle,
            runtime_compatibility_status=compatibility,
            diagnostics_timestamp=at or datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    def test_registry_models_are_immutable(self) -> None:
        container = DependencyContainer(clock=_Clock())
        container.register_instance("database", object())
        container.register_instance(
            "service",
            object(),
            dependencies=("database",),
        )
        snapshot = self._snapshot(container)
        record = snapshot.get("service")

        self.assertIsNotNone(record)
        with self.assertRaises(FrozenInstanceError):
            snapshot.services = ()  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            record.health_state = RuntimeHealthStatus.FAILED  # type: ignore[union-attr,misc]
        with self.assertRaises(TypeError):
            record.dependencies[0] = "changed"  # type: ignore[union-attr,index]

    def test_dependency_graph_and_summaries_are_deterministic(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        container.register_instance("database", object())
        container.register_instance(
            "worker",
            object(),
            dependencies=("database",),
        )
        container.register_instance(
            "api",
            object(),
            dependencies=("missing_cache",),
        )
        registry = RuntimeServiceRegistry(container, SystemCoordinator())

        first = registry.snapshot(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            runtime_compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            diagnostics_timestamp=clock.now,
        )
        second = registry.snapshot(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            runtime_compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            diagnostics_timestamp=clock.now,
        )
        graph = first.health.dependency_graph_summary

        self.assertEqual(first, second)
        self.assertEqual(graph.service_count, 3)
        self.assertEqual(graph.dependency_count, 2)
        self.assertEqual(graph.satisfied_dependency_count, 1)
        self.assertEqual(graph.missing_dependency_count, 1)
        self.assertEqual(
            tuple(
                (edge.service_name, edge.dependency_name, edge.registered)
                for edge in graph.dependencies
            ),
            (
                ("worker", "database", True),
                ("api", "missing_cache", False),
            ),
        )
        self.assertIs(first.get("api").health_state, RuntimeHealthStatus.DEGRADED)  # type: ignore[union-attr]
        self.assertIs(first.health.status, RuntimeHealthStatus.DEGRADED)
        self.assertEqual(
            first.health.summary,
            "Runtime service metadata reports degraded: 3 total, 3 active, "
            "0 inactive, 0 failed, 1 missing dependencies, compatibility compatible.",
        )

    def test_cycle_and_compatibility_summaries_use_registration_metadata_only(self) -> None:
        container = DependencyContainer(clock=_Clock())
        container.register_instance(
            "alpha",
            object(),
            dependencies=("beta",),
            compatibility_status="compatible",
        )
        container.register_instance(
            "beta",
            object(),
            dependencies=("alpha",),
            compatibility_status="degraded",
        )
        container.register_instance(
            "gamma",
            object(),
            compatibility_status="incompatible",
        )
        container.register_instance(
            "delta",
            object(),
            compatibility_status="unknown",
        )

        snapshot = self._snapshot(container)
        graph = snapshot.health.dependency_graph_summary
        compatibility = snapshot.health.compatibility_summary

        self.assertEqual(graph.cyclic_services, ("alpha", "beta"))
        self.assertEqual(compatibility.compatible_services, 1)
        self.assertEqual(compatibility.degraded_services, 1)
        self.assertEqual(compatibility.incompatible_services, 1)
        self.assertEqual(compatibility.unknown_services, 1)
        self.assertIs(
            compatibility.status,
            RuntimeCompatibilityStatus.INCOMPATIBLE,
        )
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.DEGRADED)

    def test_lifecycle_and_failure_states_are_derived_from_metadata(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        container.register_instance("service", object())
        coordinator = SystemCoordinator()
        component = SimpleNamespace(name="service", state=ComponentState.NEW)
        coordinator.register(component)

        initializing = self._snapshot(
            container,
            lifecycle=RuntimeLifecycleState.INITIALIZING,
            coordinator=coordinator,
        )
        running_uninitialized = self._snapshot(
            container,
            coordinator=coordinator,
        )
        component.state = ComponentState.INITIALIZED
        running = self._snapshot(container, coordinator=coordinator)
        stopped = self._snapshot(
            container,
            lifecycle=RuntimeLifecycleState.STOPPED,
            coordinator=coordinator,
        )
        failed = self._snapshot(
            container,
            lifecycle=RuntimeLifecycleState.FAILED,
            coordinator=coordinator,
        )
        unknown = self._snapshot(
            container,
            lifecycle=RuntimeLifecycleState.UNKNOWN,
            coordinator=coordinator,
        )

        self.assertIs(initializing.health.status, RuntimeHealthStatus.INITIALIZING)
        self.assertIs(
            running_uninitialized.get("service").health_state,  # type: ignore[union-attr]
            RuntimeHealthStatus.INITIALIZING,
        )
        self.assertIs(running.health.status, RuntimeHealthStatus.HEALTHY)
        self.assertIs(stopped.health.status, RuntimeHealthStatus.STOPPED)
        self.assertIs(failed.health.status, RuntimeHealthStatus.FAILED)
        self.assertIs(unknown.health.status, RuntimeHealthStatus.UNKNOWN)

        unavailable = DependencyContainer(clock=clock)
        unavailable.register_instance(
            "failed_service",
            object(),
            runtime_available=False,
        )
        unavailable_snapshot = self._snapshot(unavailable)
        self.assertIs(unavailable_snapshot.health.status, RuntimeHealthStatus.FAILED)
        self.assertEqual(unavailable_snapshot.health.active_services, 0)
        self.assertEqual(unavailable_snapshot.health.failed_services, 1)


class RuntimeServiceRegistryIntegrationTests(unittest.TestCase):
    """Verify diagnostics, lifecycle, EventBus, and application compatibility."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def _application(self) -> NARVISApplication:
        root = Path("data") / "test_runtime_tmp" / f"registry_{uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return NARVISApplication(
            config=NARVISConfig(data_dir=root / "data", log_dir=root / "logs")
        )

    def test_runtime_diagnostics_exposes_registry_snapshot_at_same_timestamp(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        for name in self.required_services:
            container.register_instance(name, object())
        coordinator = SystemCoordinator()
        coordinator.register(
            SimpleNamespace(name="ai_runtime", state=ComponentState.INITIALIZED)
        )
        registry = RuntimeServiceRegistry(container, coordinator)
        diagnostics = RuntimeDiagnostics(
            container,
            coordinator,
            SimpleNamespace(started=True, bootstrapped=True, shutting_down=False),
            RuntimeBuildMetadata("1.4", 3, 2, "v1.4-m3-s2", "test"),
            runtime_service_registry=registry,
            event_bus=EventBus(),
            logger=_Logger(),
            clock=clock,
        )
        diagnostics.start()

        snapshot = diagnostics.snapshot()
        registry_snapshot = snapshot.service_registry_snapshot

        self.assertIsNotNone(registry_snapshot)
        self.assertEqual(
            registry_snapshot.diagnostics_timestamp,  # type: ignore[union-attr]
            snapshot.captured_at,
        )
        self.assertEqual(registry_snapshot.health.total_services, 6)  # type: ignore[union-attr]
        self.assertIs(
            registry_snapshot.health.status,  # type: ignore[union-attr]
            RuntimeHealthStatus.HEALTHY,
        )

    def test_application_lifecycle_uses_existing_events_and_preserves_execution(self) -> None:
        application = self._application()
        events: list[object] = []
        for event_name in (
            RUNTIME_DIAGNOSTICS_STARTED_EVENT,
            "system.started",
            RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
            "system.stopped",
        ):
            application.event_bus.subscribe(
                event_name,
                events.append,
            )
        before = application.runtime_services()

        try:
            application.start()
            provider = application.container.resolve("ai_provider")
            brain_engine = application.container.resolve("brain_engine")
            with mock.patch.object(
                application.container,
                "resolve",
                side_effect=AssertionError("registry snapshots must not resolve services"),
            ):
                running = application.runtime_services()
                repeated = application.runtime_services()
            legacy_health = application.health()
        finally:
            application.shutdown()

        stopped = application.runtime_services()
        self.assertIs(before.health.status, RuntimeHealthStatus.INITIALIZING)
        self.assertIs(running.health.status, RuntimeHealthStatus.HEALTHY)
        self.assertEqual(
            tuple(service.service_name for service in running.services),
            tuple(service.service_name for service in repeated.services),
        )
        self.assertIs(stopped.health.status, RuntimeHealthStatus.STOPPED)
        self.assertIn("runtime_service_registry", application.container.registered_services())
        self.assertIn("brain_engine", legacy_health)
        self.assertIs(application.container.resolve("brain_engine"), brain_engine)
        self.assertEqual(getattr(provider, "request_count", 0), 0)
        self.assertEqual(
            [getattr(event, "name") for event in events],
            [
                RUNTIME_DIAGNOSTICS_STARTED_EVENT,
                "system.started",
                RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
                "system.stopped",
            ],
        )
        self.assertTrue(getattr(events[0], "payload")["service_registry_registered"])
        self.assertTrue(getattr(events[2], "payload")["service_registry_registered"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
