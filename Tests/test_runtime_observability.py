"""Focused tests for Version 1.5 Sprint 4 runtime observability snapshots."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest import mock

from Core import (
    RUNTIME_SNAPSHOT_SCHEMA_VERSION,
    RuntimeBuildMetadata,
    RuntimeCapabilityManifestService,
    RuntimeCapabilitySource,
    RuntimeCompatibilityStatus,
    RuntimeDependencyGraph,
    RuntimeDiagnostics,
    RuntimeFeatureAvailability,
    RuntimeFeatureCommercialVisibility,
    RuntimeFeatureDescriptor,
    RuntimeFeatureMaturity,
    RuntimeFeatureRegistry,
    RuntimeFeatureSafetyLevel,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeObservabilityReport,
    RuntimeServiceRegistry,
    RuntimeSnapshot,
    RuntimeSnapshotEngine,
    RuntimeSnapshotSource,
    RuntimeStateEngine,
    RuntimeStateReadiness,
    RuntimeStateSource,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator


class _Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Logger:
    def log(self, level: object, message: str, **context: object) -> None:
        return None


def _feature(
    feature_id: str,
    *,
    depends_on: tuple[str, ...] = (),
) -> RuntimeFeatureDescriptor:
    return RuntimeFeatureDescriptor(
        id=feature_id,
        display_name=feature_id.replace(".", " ").title(),
        description=f"Observability metadata for {feature_id}.",
        category="runtime",
        maturity=RuntimeFeatureMaturity.STABLE,
        availability=RuntimeFeatureAvailability.AVAILABLE,
        required_services=(),
        required_capabilities=(),
        safety_level=RuntimeFeatureSafetyLevel.METADATA_ONLY,
        commercial_visibility=RuntimeFeatureCommercialVisibility.PUBLIC,
        experimental=False,
        depends_on=depends_on,
    )


class RuntimeSnapshotEngineTests(unittest.TestCase):
    """Verify immutable identifiers, reports, exports, and comparisons."""

    required_services = (
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
        "runtime_dependency_graph",
        "runtime_diagnostics",
        "runtime_feature_registry",
        "runtime_service_registry",
        "runtime_snapshot_engine",
        "runtime_state_engine",
    )

    def _source(
        self,
        features: tuple[RuntimeFeatureDescriptor, ...],
        *,
        captured_at: datetime | None = None,
        extra_services: tuple[str, ...] = (),
    ) -> RuntimeSnapshotSource:
        captured = captured_at or datetime(
            2026,
            7,
            16,
            0,
            0,
            tzinfo=timezone.utc,
        )
        clock = _Clock(captured)
        container = DependencyContainer(clock=clock)
        for name in tuple(sorted((*self.required_services, *extra_services))):
            container.register_instance(name, object())
        service_snapshot = RuntimeServiceRegistry(
            container,
            SystemCoordinator(),
        ).snapshot(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            runtime_compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            diagnostics_timestamp=captured,
        )
        capability_manifest = RuntimeCapabilityManifestService().snapshot(
            RuntimeCapabilitySource(
                runtime_version="1.5",
                build_version="v1.5-s4",
                registered_runtime_services=container.registered_services(),
                lifecycle_state=RuntimeLifecycleState.RUNNING,
                diagnostics_health=RuntimeHealthStatus.HEALTHY,
                service_registry_health=service_snapshot.health.status,
                event_bus_available=True,
                compatibility_mode=RuntimeCompatibilityStatus.COMPATIBLE,
                service_registry_snapshot=service_snapshot,
                diagnostics_timestamp=captured,
                feature_registry_available=True,
                dependency_graph_available=True,
                state_engine_available=True,
                snapshot_engine_available=True,
            )
        )
        registry = RuntimeFeatureRegistry(features)
        feature_snapshot = registry.snapshot(
            service_registry_snapshot=service_snapshot,
            capability_manifest=capability_manifest,
            diagnostics_timestamp=captured,
        )
        graph_snapshot = RuntimeDependencyGraph(registry).snapshot(
            feature_registry_snapshot=feature_snapshot,
            diagnostics_timestamp=captured,
        )
        state_snapshot = RuntimeStateEngine().snapshot(
            RuntimeStateSource(
                lifecycle_state=RuntimeLifecycleState.RUNNING,
                diagnostics_health=RuntimeHealthStatus.HEALTHY,
                diagnostics_issues=(),
                diagnostics_timestamp=captured,
                service_registry_snapshot=service_snapshot,
                capability_manifest=capability_manifest,
                feature_registry_snapshot=feature_snapshot,
                dependency_graph_snapshot=graph_snapshot,
            )
        )
        return RuntimeSnapshotSource(
            runtime_version="1.5",
            build_version="v1.5-s4",
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            diagnostics_health=RuntimeHealthStatus.HEALTHY,
            diagnostics_issues=(),
            registered_runtime_services=container.registered_services(),
            compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            ai_manager_registered=True,
            conversation_runtime_state=RuntimeHealthStatus.HEALTHY,
            event_bus_available=True,
            logger_available=True,
            passed_diagnostics_checks=5,
            total_diagnostics_checks=5,
            diagnostics_summary="Runtime diagnostics report healthy metadata.",
            startup_timestamp=captured - timedelta(seconds=10),
            uptime_seconds=10.0,
            captured_at=captured,
            service_registry_snapshot=service_snapshot,
            capability_manifest=capability_manifest,
            feature_registry_snapshot=feature_snapshot,
            dependency_graph_snapshot=graph_snapshot,
            runtime_state_snapshot=state_snapshot,
            metadata={"environment": "test", "sprint": "4"},
        )

    def test_snapshot_identity_version_and_capture_are_deterministic(self) -> None:
        source = self._source(
            (
                _feature("feature.child", depends_on=("feature.root",)),
                _feature("feature.root"),
            )
        )
        engine = RuntimeSnapshotEngine()

        first = engine.snapshot(source)
        second = engine.capture(source)

        self.assertEqual(first, second)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertTrue(first.snapshot_id.startswith("runtime-snapshot-"))
        self.assertEqual(first.schema_version, RUNTIME_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(first.captured_at, source.captured_at)
        self.assertIs(first.overview.readiness, RuntimeStateReadiness.READY)
        self.assertTrue(first.metadata.deterministic)
        self.assertFalse(first.metadata.active_probes)

    def test_snapshot_and_mapping_export_are_deeply_immutable(self) -> None:
        snapshot = RuntimeSnapshotEngine().snapshot(
            self._source((_feature("feature.root"),))
        )

        first_export = snapshot.export()
        second_export = snapshot.export()

        self.assertEqual(first_export, second_export)
        self.assertEqual(first_export["snapshot_id"], snapshot.snapshot_id)
        with self.assertRaises(FrozenInstanceError):
            snapshot.metadata.schema_version = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            first_export["snapshot_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            first_export["metadata"]["attributes"]["sprint"] = "5"  # type: ignore[index]

    def test_observability_report_exports_every_runtime_summary(self) -> None:
        snapshot = RuntimeSnapshotEngine().snapshot(
            self._source(
                (
                    _feature("feature.child", depends_on=("feature.root",)),
                    _feature("feature.root"),
                )
            )
        )

        report = snapshot.observability_report

        self.assertIsInstance(report, RuntimeObservabilityReport)
        self.assertEqual(report.registered_services.total_services, 16)
        self.assertEqual(report.registered_features.total_features, 2)
        self.assertEqual(report.dependencies.node_count, 2)
        self.assertEqual(report.dependencies.edge_count, 1)
        self.assertEqual(report.readiness.ready_feature_count, 2)
        self.assertIn(
            "runtime_snapshot_engine",
            report.capabilities.enabled_feature_flags,
        )
        self.assertIs(snapshot.feature_snapshot, snapshot.state_snapshot.feature_registry_snapshot)  # type: ignore[union-attr]
        self.assertIs(snapshot.capability_snapshot, snapshot.state_snapshot.capability_manifest)  # type: ignore[union-attr]
        self.assertIs(snapshot.dependency_snapshot, snapshot.state_snapshot.dependency_graph_snapshot)  # type: ignore[union-attr]

    def test_snapshot_comparison_distinguishes_time_from_content(self) -> None:
        features = (_feature("feature.root"),)
        first = RuntimeSnapshotEngine().snapshot(self._source(features))
        later = RuntimeSnapshotEngine().snapshot(
            self._source(
                features,
                captured_at=first.captured_at + timedelta(minutes=1),
            )
        )

        identical = first.compare(first)
        comparison = RuntimeSnapshotEngine.compare(first, later)

        self.assertTrue(identical.same_snapshot)
        self.assertEqual(identical.changed_sections, ())
        self.assertFalse(comparison.same_snapshot)
        self.assertTrue(comparison.same_content)
        self.assertTrue(comparison.schema_compatible)
        self.assertEqual(comparison.timestamp_delta, timedelta(minutes=1))
        self.assertEqual(comparison.changed_sections, ("timestamp",))

    def test_snapshot_comparison_reports_feature_and_service_changes(self) -> None:
        captured = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
        first = RuntimeSnapshotEngine().snapshot(
            self._source((_feature("feature.root"),), captured_at=captured)
        )
        changed = RuntimeSnapshotEngine().snapshot(
            self._source(
                (
                    _feature("feature.added"),
                    _feature("feature.root"),
                ),
                captured_at=captured,
                extra_services=("service.added",),
            )
        )

        comparison = first.compare(changed)

        self.assertFalse(comparison.same_content)
        self.assertEqual(comparison.services_added, ("service.added",))
        self.assertEqual(comparison.features_added, ("feature.added",))
        self.assertIn("services", comparison.changed_sections)
        self.assertIn("features", comparison.changed_sections)
        self.assertTrue(comparison.readiness_changed)


class RuntimeObservabilityDiagnosticsTests(unittest.TestCase):
    """Verify same-timestamp passive diagnostics and composition integration."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def test_diagnostics_exports_observability_without_service_resolution(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        coordinator = SystemCoordinator()
        coordinator.register(
            SimpleNamespace(name="ai_runtime", state=ComponentState.INITIALIZED)
        )
        event_bus = EventBus()
        lifecycle = SimpleNamespace(
            started=True,
            bootstrapped=True,
            shutting_down=False,
        )
        service_registry = RuntimeServiceRegistry(container, coordinator)
        capability_service = RuntimeCapabilityManifestService()
        feature_registry = RuntimeFeatureRegistry(
            (
                _feature("feature.root"),
                _feature("feature.child", depends_on=("feature.root",)),
            )
        )
        dependency_graph = RuntimeDependencyGraph(feature_registry)
        state_engine = RuntimeStateEngine()
        snapshot_engine = RuntimeSnapshotEngine()
        diagnostics = RuntimeDiagnostics(
            container,
            coordinator,
            lifecycle,
            RuntimeBuildMetadata("1.5", 1, 4, "v1.5-s4", "test"),
            runtime_service_registry=service_registry,
            capability_manifest_service=capability_service,
            runtime_feature_registry=feature_registry,
            runtime_dependency_graph=dependency_graph,
            runtime_state_engine=state_engine,
            runtime_snapshot_engine=snapshot_engine,
            event_bus=event_bus,
            logger=_Logger(),
            clock=clock,
        )
        services = {
            "coordinator": coordinator,
            "event_bus": event_bus,
            "lifecycle_manager": object(),
            "runtime_status": lifecycle,
            "runtime_diagnostics": diagnostics,
            "runtime_service_registry": service_registry,
            "runtime_capability_manifest": capability_service,
            "runtime_feature_registry": feature_registry,
            "runtime_dependency_graph": dependency_graph,
            "runtime_state_engine": state_engine,
            "runtime_snapshot_engine": snapshot_engine,
            **{name: object() for name in self.required_services},
        }
        for name, instance in services.items():
            container.register_instance(name, instance)
        diagnostics.start()

        with mock.patch.object(
            container,
            "resolve",
            side_effect=AssertionError("runtime snapshots must not resolve services"),
        ):
            first = diagnostics.snapshot(at=clock.now)
            second = diagnostics.snapshot(at=clock.now)

        snapshot = first.runtime_snapshot
        self.assertIsInstance(snapshot, RuntimeSnapshot)
        self.assertEqual(snapshot, second.runtime_snapshot)
        self.assertEqual(snapshot.captured_at, first.captured_at)  # type: ignore[union-attr]
        self.assertEqual(snapshot.service_snapshot, first.service_registry_snapshot)  # type: ignore[union-attr]
        self.assertEqual(snapshot.feature_snapshot, first.feature_registry_snapshot)  # type: ignore[union-attr]
        self.assertEqual(snapshot.capability_snapshot, first.capability_manifest)  # type: ignore[union-attr]
        self.assertEqual(snapshot.dependency_snapshot, first.dependency_graph_snapshot)  # type: ignore[union-attr]
        self.assertEqual(snapshot.state_snapshot, first.runtime_state_snapshot)  # type: ignore[union-attr]
        self.assertEqual(first.observability_report, snapshot.observability_report)  # type: ignore[union-attr]
        self.assertTrue(
            first.capability_manifest.runtime_snapshot_engine_available  # type: ignore[union-attr]
        )
        self.assertTrue(
            first.capability_manifest.feature_flags["runtime_snapshot_engine"]  # type: ignore[union-attr]
        )

    def test_diagnostics_without_snapshot_engine_remains_backward_compatible(self) -> None:
        clock = _Clock()
        diagnostics = RuntimeDiagnostics(
            DependencyContainer(clock=clock),
            SystemCoordinator(),
            SimpleNamespace(started=False, bootstrapped=False, shutting_down=False),
            RuntimeBuildMetadata("1.5", 1, 4, "build", "test"),
            clock=clock,
        )

        snapshot = diagnostics.snapshot()

        self.assertIsNone(snapshot.runtime_snapshot)
        self.assertIsNone(snapshot.observability_report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
