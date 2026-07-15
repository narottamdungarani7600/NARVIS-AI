"""Focused tests for Version 1.4 Milestone 3 Sprint 1 diagnostics."""

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
    RuntimeDiagnosticsLifecycleAdapter,
    RuntimeDiagnosticsSnapshot,
    RuntimeHealthCalculator,
    RuntimeHealthContext,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator
from narvis import NARVISApplication, NARVISConfig


class _Clock:
    """Injectable deterministic clock for uptime and lifecycle tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class _Logger:
    """Available logger double with retained entries."""

    def __init__(self) -> None:
        self.entries: list[tuple[object, str, dict[str, object]]] = []

    def log(self, level: object, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _MetadataOnlyRegistry:
    """Registry double that fails if a caller attempts service resolution."""

    def __init__(self, services: tuple[str, ...]) -> None:
        self.services = tuple(sorted(services))
        self.resolve_calls = 0

    def is_registered(self, name: str) -> bool:
        return name in self.services

    def registered_services(self) -> tuple[str, ...]:
        return self.services

    def resolve(self, name: str) -> object:
        self.resolve_calls += 1
        raise AssertionError(f"diagnostics must not resolve '{name}'")


class RuntimeDiagnosticsModelTests(unittest.TestCase):
    """Verify immutable typed models and deterministic health calculation."""

    def test_build_and_snapshot_metadata_are_deeply_immutable(self) -> None:
        build = RuntimeBuildMetadata(
            version="1.4",
            milestone=3,
            sprint=1,
            build_id="v1.4-m3-s1",
            environment="test",
            attributes={"nested": {"flags": ["metadata-only"]}},
        )
        services = DependencyContainer()
        diagnostics = RuntimeDiagnostics(
            services,
            SystemCoordinator(),
            SimpleNamespace(started=False, bootstrapped=False, shutting_down=False),
            build,
            event_bus=EventBus(),
            logger=_Logger(),
            clock=_Clock(),
        )

        snapshot = diagnostics.snapshot()

        self.assertIsInstance(snapshot, RuntimeDiagnosticsSnapshot)
        self.assertEqual(snapshot.runtime_version, "1.4")
        self.assertEqual(build.attributes["nested"]["flags"], ("metadata-only",))
        with self.assertRaises(FrozenInstanceError):
            snapshot.runtime_version = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            build.attributes["new"] = True  # type: ignore[index]
        with self.assertRaises(TypeError):
            build.attributes["nested"]["flags"] = ()  # type: ignore[index]

    def test_health_calculator_supports_every_declared_state(self) -> None:
        expected = {
            RuntimeLifecycleState.INITIALIZING: RuntimeHealthStatus.INITIALIZING,
            RuntimeLifecycleState.STOPPED: RuntimeHealthStatus.STOPPED,
            RuntimeLifecycleState.FAILED: RuntimeHealthStatus.FAILED,
            RuntimeLifecycleState.UNKNOWN: RuntimeHealthStatus.UNKNOWN,
        }
        for lifecycle, status in expected.items():
            with self.subTest(lifecycle=lifecycle):
                report = RuntimeHealthCalculator.calculate(
                    RuntimeHealthContext(
                        lifecycle_state=lifecycle,
                        ai_manager_registered=True,
                        conversation_runtime_state=RuntimeHealthStatus.HEALTHY,
                        event_bus_available=True,
                        logger_available=True,
                        compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
                    )
                )
                self.assertIs(report.status, status)
                self.assertTrue(report.calculated_from_metadata)
                self.assertFalse(report.active_probes)

        healthy = RuntimeHealthCalculator.calculate(
            RuntimeHealthContext(
                lifecycle_state=RuntimeLifecycleState.RUNNING,
                ai_manager_registered=True,
                conversation_runtime_state=RuntimeHealthStatus.HEALTHY,
                event_bus_available=True,
                logger_available=True,
                compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            )
        )
        degraded = RuntimeHealthCalculator.calculate(
            RuntimeHealthContext(
                lifecycle_state=RuntimeLifecycleState.RUNNING,
                ai_manager_registered=False,
                conversation_runtime_state=RuntimeHealthStatus.DEGRADED,
                event_bus_available=False,
                logger_available=False,
                compatibility_status=RuntimeCompatibilityStatus.INCOMPATIBLE,
            )
        )

        self.assertIs(healthy.status, RuntimeHealthStatus.HEALTHY)
        self.assertEqual(healthy.issues, ())
        self.assertIs(degraded.status, RuntimeHealthStatus.DEGRADED)
        self.assertEqual(
            degraded.issues,
            (
                "ai_manager_unregistered",
                "conversation_runtime_unavailable",
                "event_bus_unavailable",
                "logger_unavailable",
                "compatibility_incompatible",
            ),
        )

    def test_pre_start_snapshot_reports_initializing_without_startup_time(self) -> None:
        clock = _Clock()
        diagnostics = RuntimeDiagnostics(
            DependencyContainer(),
            SystemCoordinator(),
            SimpleNamespace(started=False, bootstrapped=False, shutting_down=False),
            RuntimeBuildMetadata("1.4", 3, 1, "build", "test"),
            event_bus=EventBus(),
            logger=_Logger(),
            clock=clock,
        )

        snapshot = diagnostics.snapshot()

        self.assertIsNone(snapshot.startup_timestamp)
        self.assertEqual(snapshot.uptime, timedelta(0))
        self.assertIs(snapshot.lifecycle.state, RuntimeLifecycleState.INITIALIZING)
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.INITIALIZING)
        self.assertIs(
            snapshot.compatibility.status,
            RuntimeCompatibilityStatus.UNKNOWN,
        )
        self.assertEqual(
            snapshot.diagnostics_summary.message,
            "Runtime metadata reports initializing: runtime_initializing.",
        )

    def test_dependency_container_reports_names_without_resolving_factories(self) -> None:
        container = DependencyContainer()
        factory_calls = 0

        def factory() -> object:
            nonlocal factory_calls
            factory_calls += 1
            return object()

        container.register_instance("zeta", object())
        container.register_factory("alpha", factory)

        self.assertEqual(container.registered_services(), ("alpha", "zeta"))
        self.assertTrue(container.is_registered("alpha"))
        self.assertFalse(container.is_registered("missing"))
        self.assertEqual(factory_calls, 0)


class RuntimeDiagnosticsServiceTests(unittest.TestCase):
    """Verify passive snapshots, lifecycle events, uptime, and DI boundaries."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def _service(
        self,
        *,
        registered: tuple[str, ...] | None = None,
        started: bool = True,
    ) -> tuple[RuntimeDiagnostics, _Clock, EventBus, _MetadataOnlyRegistry]:
        clock = _Clock()
        bus = EventBus()
        registry = _MetadataOnlyRegistry(registered or self.required_services)
        coordinator = SystemCoordinator()
        coordinator.register(
            SimpleNamespace(
                name="ai_runtime",
                state=ComponentState.INITIALIZED,
            )
        )
        diagnostics = RuntimeDiagnostics(
            registry,
            coordinator,
            SimpleNamespace(
                started=started,
                bootstrapped=started,
                shutting_down=False,
            ),
            RuntimeBuildMetadata(
                version="1.4",
                milestone=3,
                sprint=1,
                build_id="v1.4-m3-s1",
                environment="test",
            ),
            event_bus=bus,
            logger=_Logger(),
            clock=clock,
        )
        return diagnostics, clock, bus, registry

    def test_running_snapshot_is_healthy_and_never_resolves_services(self) -> None:
        diagnostics, clock, _, registry = self._service()
        diagnostics.start()
        clock.advance(15)

        snapshot = diagnostics.snapshot()

        self.assertEqual(snapshot.startup_timestamp, clock.now - timedelta(seconds=15))
        self.assertEqual(snapshot.uptime, timedelta(seconds=15))
        self.assertEqual(snapshot.registered_runtime_services, self.required_services)
        self.assertTrue(snapshot.ai_manager_registered)
        self.assertIs(
            snapshot.conversation_runtime_state,
            RuntimeHealthStatus.HEALTHY,
        )
        self.assertTrue(snapshot.event_bus_available)
        self.assertTrue(snapshot.logger_available)
        self.assertIs(snapshot.lifecycle.state, RuntimeLifecycleState.RUNNING)
        self.assertIs(
            snapshot.compatibility.status,
            RuntimeCompatibilityStatus.COMPATIBLE,
        )
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.HEALTHY)
        self.assertEqual(snapshot.diagnostics_summary.passed_checks, 5)
        self.assertEqual(registry.resolve_calls, 0)

    def test_missing_registration_calculates_degraded_summary_deterministically(self) -> None:
        registered = tuple(
            service
            for service in self.required_services
            if service not in {"ai_runtime_adapter"}
        )
        diagnostics, _, _, _ = self._service(registered=registered)
        diagnostics.start()

        first = diagnostics.snapshot()
        second = diagnostics.snapshot(at=first.captured_at)

        self.assertIs(first.health.status, RuntimeHealthStatus.DEGRADED)
        self.assertIs(
            first.compatibility.status,
            RuntimeCompatibilityStatus.DEGRADED,
        )
        self.assertEqual(
            first.compatibility.missing_services,
            ("ai_runtime_adapter",),
        )
        self.assertEqual(first.diagnostics_summary, second.diagnostics_summary)
        self.assertEqual(
            first.health.issues,
            (
                "conversation_runtime_unavailable",
                "compatibility_degraded",
            ),
        )

    def test_lifecycle_events_are_emitted_once_and_uptime_freezes_on_stop(self) -> None:
        diagnostics, clock, bus, _ = self._service()
        events: list[object] = []
        bus.subscribe(RUNTIME_DIAGNOSTICS_STARTED_EVENT, events.append)
        bus.subscribe(RUNTIME_DIAGNOSTICS_STOPPED_EVENT, events.append)

        diagnostics.start()
        diagnostics.start()
        clock.advance(7)
        diagnostics.stop()
        diagnostics.stop()
        clock.advance(100)
        snapshot = diagnostics.snapshot()

        self.assertEqual(
            [getattr(event, "name") for event in events],
            [
                RUNTIME_DIAGNOSTICS_STARTED_EVENT,
                RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
            ],
        )
        self.assertEqual(snapshot.uptime, timedelta(seconds=7))
        self.assertIs(snapshot.lifecycle.state, RuntimeLifecycleState.STOPPED)
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.STOPPED)
        self.assertNotIn("registered_runtime_services", repr(events))
        self.assertNotIn("build_metadata", repr(events))

    def test_lifecycle_adapter_uses_existing_component_contract(self) -> None:
        diagnostics, _, _, _ = self._service()
        lifecycle = RuntimeDiagnosticsLifecycleAdapter(diagnostics)

        lifecycle.initialize(SimpleNamespace())
        running = diagnostics.snapshot()
        lifecycle.shutdown()
        stopped = diagnostics.snapshot()

        self.assertIs(running.health.status, RuntimeHealthStatus.HEALTHY)
        self.assertIs(stopped.health.status, RuntimeHealthStatus.STOPPED)
        self.assertIs(lifecycle.state, ComponentState.STOPPED)

    def test_unavailable_event_bus_and_logger_are_metadata_only_degradations(self) -> None:
        registry = _MetadataOnlyRegistry(self.required_services)
        coordinator = SystemCoordinator()
        coordinator.register(
            SimpleNamespace(name="ai_runtime", state=ComponentState.INITIALIZED)
        )
        diagnostics = RuntimeDiagnostics(
            registry,
            coordinator,
            SimpleNamespace(started=True, bootstrapped=True, shutting_down=False),
            RuntimeBuildMetadata("1.4", 3, 1, "build", "test"),
            event_bus=None,
            logger=None,
            clock=_Clock(),
        )
        diagnostics.start()

        snapshot = diagnostics.snapshot()

        self.assertFalse(snapshot.event_bus_available)
        self.assertFalse(snapshot.logger_available)
        self.assertEqual(
            snapshot.health.issues,
            ("event_bus_unavailable", "logger_unavailable"),
        )
        self.assertEqual(registry.resolve_calls, 0)

    def test_invalid_dependencies_are_rejected_without_side_effects(self) -> None:
        build = RuntimeBuildMetadata("1.4", 3, 1, "build", "test")
        state = SimpleNamespace(started=False, bootstrapped=False, shutting_down=False)
        with self.assertRaises(TypeError):
            RuntimeDiagnostics(object(), SystemCoordinator(), state, build)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            RuntimeDiagnostics(DependencyContainer(), object(), state, build)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            RuntimeDiagnostics(
                DependencyContainer(),
                SystemCoordinator(),
                object(),
                build,
            )  # type: ignore[arg-type]


class RuntimeDiagnosticsApplicationIntegrationTests(unittest.TestCase):
    """Verify diagnostics composition without changing established runtime behavior."""

    def _application(self) -> NARVISApplication:
        root = Path("data") / "test_runtime_tmp" / f"case_{uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return NARVISApplication(
            config=NARVISConfig(data_dir=root / "data", log_dir=root / "logs")
        )

    def test_application_registers_healthy_diagnostics_with_ordered_events(self) -> None:
        application = self._application()
        event_names: list[str] = []
        for name in (
            RUNTIME_DIAGNOSTICS_STARTED_EVENT,
            "system.started",
            RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
            "system.stopped",
        ):
            application.event_bus.subscribe(
                name,
                lambda event: event_names.append(event.name),
            )
        before_start = application.diagnostics()

        try:
            application.start()
            diagnostics = application.container.resolve("runtime_diagnostics")
            lifecycle = application.container.resolve(
                "runtime_diagnostics_lifecycle"
            )
            ai_manager = application.container.resolve("ai_manager")
            provider = application.container.resolve("ai_provider")
            with mock.patch.object(
                ai_manager,
                "route_request",
                side_effect=AssertionError("diagnostics must not route"),
            ), mock.patch.object(
                ai_manager,
                "plan_request",
                side_effect=AssertionError("diagnostics must not plan"),
            ), mock.patch.object(
                provider,
                "complete_chat",
                side_effect=AssertionError("diagnostics must not call providers"),
            ):
                snapshot = application.diagnostics()
                direct_snapshot = diagnostics.snapshot()
            legacy_health = application.health()
        finally:
            application.shutdown()

        stopped = application.diagnostics()
        self.assertIs(before_start.health.status, RuntimeHealthStatus.INITIALIZING)
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.HEALTHY)
        self.assertEqual(snapshot.runtime_version, "1.5")
        self.assertEqual(snapshot.build_metadata.milestone, 1)
        self.assertEqual(snapshot.build_metadata.sprint, 1)
        self.assertEqual(snapshot.build_metadata.build_id, "v1.5-s1")
        self.assertTrue(snapshot.ai_manager_registered)
        self.assertIs(
            snapshot.conversation_runtime_state,
            RuntimeHealthStatus.HEALTHY,
        )
        self.assertIn("runtime_diagnostics", snapshot.registered_runtime_services)
        self.assertIn("brain_engine", snapshot.registered_runtime_services)
        self.assertEqual(snapshot.health, direct_snapshot.health)
        self.assertIs(lifecycle.state, ComponentState.STOPPED)
        self.assertIs(stopped.health.status, RuntimeHealthStatus.STOPPED)
        self.assertIn("brain_engine", legacy_health)
        self.assertIn("dashboard", legacy_health)
        self.assertEqual(
            event_names,
            [
                RUNTIME_DIAGNOSTICS_STARTED_EVENT,
                "system.started",
                RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
                "system.stopped",
            ],
        )
        self.assertEqual(getattr(provider, "request_count", 0), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
