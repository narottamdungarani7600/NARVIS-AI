"""Focused tests for Version 1.4 Milestone 3 Sprint 3."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
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
    RuntimeCapabilityManifest,
    RuntimeCapabilityManifestService,
    RuntimeCapabilitySource,
    RuntimeCompatibilityStatus,
    RuntimeDiagnostics,
    RuntimeExecutionMode,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeProviderMode,
    RuntimeReadinessCalculator,
    RuntimeReadinessContext,
    RuntimeReadinessLevel,
    RuntimeServiceRegistry,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator
from narvis import NARVISApplication, NARVISConfig


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Logger:
    def log(self, level: object, message: str, **context: object) -> None:
        return None


class RuntimeReadinessTests(unittest.TestCase):
    """Verify every readiness level and deterministic calculation rules."""

    def _context(self) -> RuntimeReadinessContext:
        return RuntimeReadinessContext(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            diagnostics_health=RuntimeHealthStatus.HEALTHY,
            service_registry_health=RuntimeHealthStatus.HEALTHY,
            lifecycle_support=True,
            conversation_support=True,
            ai_manager_available=True,
            runtime_service_registry_available=True,
            diagnostics_available=True,
            event_bus_available=True,
            compatibility_mode=RuntimeCompatibilityStatus.COMPATIBLE,
            execution_mode=RuntimeExecutionMode.ARCHITECTURE_ONLY,
            provider_mode=RuntimeProviderMode.DISABLED,
            diagnostics_timestamp=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    def test_readiness_calculator_supports_all_declared_levels(self) -> None:
        ready = RuntimeReadinessCalculator.calculate(self._context())
        partial = RuntimeReadinessCalculator.calculate(
            replace(self._context(), conversation_support=False)
        )
        unknown = RuntimeReadinessCalculator.calculate(
            replace(
                self._context(),
                lifecycle_state=RuntimeLifecycleState.UNKNOWN,
            )
        )

        self.assertIs(ready.level, RuntimeReadinessLevel.READY)
        self.assertEqual(ready.missing_capabilities, ())
        self.assertIs(partial.level, RuntimeReadinessLevel.PARTIAL)
        self.assertEqual(partial.missing_capabilities, ("conversation_runtime",))
        self.assertIs(unknown.level, RuntimeReadinessLevel.READINESS_UNKNOWN)
        self.assertTrue(ready.calculated_from_metadata)
        self.assertFalse(ready.active_probes)

        for lifecycle in (
            RuntimeLifecycleState.INITIALIZING,
            RuntimeLifecycleState.STOPPED,
            RuntimeLifecycleState.FAILED,
        ):
            with self.subTest(lifecycle=lifecycle):
                report = RuntimeReadinessCalculator.calculate(
                    replace(self._context(), lifecycle_state=lifecycle)
                )
                self.assertIs(report.level, RuntimeReadinessLevel.NOT_READY)

    def test_readiness_summary_is_deterministic(self) -> None:
        context = replace(
            self._context(),
            ai_manager_available=False,
            execution_mode=RuntimeExecutionMode.DISABLED,
            provider_mode=RuntimeProviderMode.UNAVAILABLE,
        )

        first = RuntimeReadinessCalculator.calculate(context)
        second = RuntimeReadinessCalculator.calculate(context)

        self.assertEqual(first, second)
        self.assertEqual(
            first.missing_capabilities,
            (
                "ai_manager",
                "architecture_only_execution",
                "provider_execution_disabled",
            ),
        )
        self.assertEqual(
            first.summary,
            "Runtime readiness metadata reports partial: 8 of 11 requirements "
            "available; missing ai_manager, architecture_only_execution, "
            "provider_execution_disabled.",
        )


class RuntimeCapabilityManifestTests(unittest.TestCase):
    """Verify immutable deterministic manifests from registry metadata."""

    service_names = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
        "coordinator",
        "event_bus",
        "lifecycle_manager",
        "runtime_capability_manifest",
        "runtime_diagnostics",
        "runtime_service_registry",
    )

    def _source(
        self,
        *,
        names: tuple[str, ...] | None = None,
        lifecycle: RuntimeLifecycleState = RuntimeLifecycleState.RUNNING,
    ) -> RuntimeCapabilitySource:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        for name in names or self.service_names:
            container.register_instance(name, object())
        registry_snapshot = RuntimeServiceRegistry(
            container,
            SystemCoordinator(),
        ).snapshot(
            lifecycle_state=lifecycle,
            runtime_compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            diagnostics_timestamp=clock.now,
        )
        return RuntimeCapabilitySource(
            runtime_version="1.4",
            build_version="v1.4-m3-s3",
            registered_runtime_services=container.registered_services(),
            lifecycle_state=lifecycle,
            diagnostics_health=(
                RuntimeHealthStatus.HEALTHY
                if lifecycle is RuntimeLifecycleState.RUNNING
                else RuntimeHealthStatus.INITIALIZING
            ),
            service_registry_health=registry_snapshot.health.status,
            event_bus_available=True,
            compatibility_mode=RuntimeCompatibilityStatus.COMPATIBLE,
            service_registry_snapshot=registry_snapshot,
            diagnostics_timestamp=clock.now,
        )

    def test_manifest_is_deeply_immutable_and_complete(self) -> None:
        manifest = RuntimeCapabilityManifestService().snapshot(self._source())

        self.assertIsInstance(manifest, RuntimeCapabilityManifest)
        self.assertEqual(manifest.runtime_version, "1.4")
        self.assertEqual(manifest.build_version, "v1.4-m3-s3")
        self.assertEqual(
            manifest.supported_subsystems,
            ("ai", "brain", "conversation", "core", "diagnostics", "runtime_services"),
        )
        self.assertEqual(
            manifest.available_diagnostics,
            (
                "compatibility",
                "dependency_health",
                "lifecycle",
                "runtime_health",
                "service_registry",
            ),
        )
        self.assertTrue(manifest.lifecycle_support)
        self.assertTrue(manifest.conversation_support)
        self.assertTrue(manifest.ai_manager_available)
        self.assertTrue(manifest.runtime_service_registry_available)
        self.assertTrue(manifest.diagnostics_available)
        self.assertTrue(manifest.event_bus_available)
        self.assertIs(
            manifest.compatibility_mode,
            RuntimeCompatibilityStatus.COMPATIBLE,
        )
        self.assertIs(
            manifest.execution_mode,
            RuntimeExecutionMode.ARCHITECTURE_ONLY,
        )
        self.assertIs(manifest.provider_mode, RuntimeProviderMode.DISABLED)
        self.assertIs(manifest.readiness.level, RuntimeReadinessLevel.READY)
        self.assertFalse(manifest.feature_flags["ai_execution"])
        self.assertFalse(manifest.feature_flags["provider_execution"])
        self.assertFalse(manifest.feature_flags["network_access"])
        self.assertFalse(manifest.feature_flags["active_probing"])

        with self.assertRaises(FrozenInstanceError):
            manifest.runtime_version = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            manifest.feature_flags["ai_execution"] = True  # type: ignore[index]
        with self.assertRaises(TypeError):
            manifest.supported_subsystems[0] = "changed"  # type: ignore[index]

    def test_manifest_metadata_and_modes_are_deterministic(self) -> None:
        service = RuntimeCapabilityManifestService()
        source = self._source()

        first = service.snapshot(source)
        second = service.snapshot(source)
        unavailable = service.snapshot(
            self._source(
                names=tuple(
                    name
                    for name in self.service_names
                    if name not in {"ai_manager", "ai_provider", "brain_provider"}
                )
            )
        )

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(first.feature_flags),
            tuple(sorted(first.feature_flags)),
        )
        self.assertIs(
            unavailable.execution_mode,
            RuntimeExecutionMode.DISABLED,
        )
        self.assertIs(
            unavailable.provider_mode,
            RuntimeProviderMode.UNAVAILABLE,
        )
        self.assertIs(
            unavailable.readiness.level,
            RuntimeReadinessLevel.PARTIAL,
        )


class RuntimeCapabilityIntegrationTests(unittest.TestCase):
    """Verify diagnostics, DI, registry, lifecycle, and EventBus integration."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def _application(self) -> NARVISApplication:
        root = Path("data") / "test_runtime_tmp" / f"capability_{uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return NARVISApplication(
            config=NARVISConfig(data_dir=root / "data", log_dir=root / "logs")
        )

    def test_diagnostics_embeds_manifest_without_resolving_services(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        bus = EventBus()
        coordinator = SystemCoordinator()
        coordinator.register(
            SimpleNamespace(name="ai_runtime", state=ComponentState.INITIALIZED)
        )
        runtime_state = SimpleNamespace(
            started=True,
            bootstrapped=True,
            shutting_down=False,
        )
        registry = RuntimeServiceRegistry(container, coordinator)
        manifest_service = RuntimeCapabilityManifestService()
        diagnostics = RuntimeDiagnostics(
            container,
            coordinator,
            runtime_state,
            RuntimeBuildMetadata("1.4", 3, 3, "v1.4-m3-s3", "test"),
            runtime_service_registry=registry,
            capability_manifest_service=manifest_service,
            event_bus=bus,
            logger=_Logger(),
            clock=clock,
        )
        services = {
            "coordinator": coordinator,
            "event_bus": bus,
            "lifecycle_manager": object(),
            "runtime_status": runtime_state,
            "runtime_diagnostics": diagnostics,
            "runtime_service_registry": registry,
            "runtime_capability_manifest": manifest_service,
            **{name: object() for name in self.required_services},
        }
        for name, instance in services.items():
            container.register_instance(name, instance)
        diagnostics.start()

        with mock.patch.object(
            container,
            "resolve",
            side_effect=AssertionError("capability snapshots must not resolve services"),
        ):
            snapshot = diagnostics.snapshot()

        manifest = snapshot.capability_manifest
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.diagnostics_timestamp, snapshot.captured_at)  # type: ignore[union-attr]
        self.assertIs(manifest.readiness.level, RuntimeReadinessLevel.READY)  # type: ignore[union-attr]
        self.assertEqual(manifest.registered_runtime_services, snapshot.registered_runtime_services)  # type: ignore[union-attr]
        self.assertEqual(
            manifest.capability_summary.registered_service_count,  # type: ignore[union-attr]
            snapshot.service_registry_snapshot.health.total_services,  # type: ignore[union-attr]
        )

    def test_diagnostics_without_manifest_service_remains_backward_compatible(self) -> None:
        clock = _Clock()
        diagnostics = RuntimeDiagnostics(
            DependencyContainer(clock=clock),
            SystemCoordinator(),
            SimpleNamespace(started=False, bootstrapped=False, shutting_down=False),
            RuntimeBuildMetadata("1.4", 3, 3, "build", "test"),
            clock=clock,
        )

        self.assertIsNone(diagnostics.snapshot().capability_manifest)

    def test_application_manifest_tracks_lifecycle_without_new_events_or_execution(self) -> None:
        application = self._application()
        events: list[object] = []
        for event_name in (
            RUNTIME_DIAGNOSTICS_STARTED_EVENT,
            "system.started",
            RUNTIME_DIAGNOSTICS_STOPPED_EVENT,
            "system.stopped",
        ):
            application.event_bus.subscribe(event_name, events.append)
        before = application.capabilities()

        try:
            application.start()
            provider = application.container.resolve("ai_provider")
            brain_engine = application.container.resolve("brain_engine")
            with mock.patch.object(
                application.container,
                "resolve",
                side_effect=AssertionError("manifest must not resolve services"),
            ), mock.patch.object(
                provider,
                "complete_chat",
                side_effect=AssertionError("manifest must not call providers"),
            ):
                running = application.capabilities()
                diagnostics_manifest = application.diagnostics().capability_manifest
            legacy_health = application.health()
        finally:
            application.shutdown()

        stopped = application.capabilities()
        self.assertIs(before.readiness.level, RuntimeReadinessLevel.NOT_READY)
        self.assertIs(running.readiness.level, RuntimeReadinessLevel.READY)
        self.assertEqual(
            running.registered_runtime_services,
            diagnostics_manifest.registered_runtime_services,
        )
        self.assertIs(
            diagnostics_manifest.readiness.level,
            RuntimeReadinessLevel.READY,
        )
        self.assertEqual(running.runtime_version, "1.4")
        self.assertEqual(running.build_version, "v1.4-m3-s3")
        self.assertIs(stopped.readiness.level, RuntimeReadinessLevel.NOT_READY)
        self.assertIn(
            "runtime_capability_manifest",
            application.container.registered_services(),
        )
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
        self.assertTrue(getattr(events[0], "payload")["capability_manifest_registered"])
        self.assertTrue(getattr(events[2], "payload")["capability_manifest_registered"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
