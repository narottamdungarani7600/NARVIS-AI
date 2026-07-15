"""Focused tests for Version 1.5 Sprint 3 runtime state and readiness."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest import mock

from Core import (
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
    RuntimeServiceRegistry,
    RuntimeStateEngine,
    RuntimeStateReadiness,
    RuntimeStateSource,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 23, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Logger:
    def log(self, level: object, message: str, **context: object) -> None:
        return None


def _feature(
    feature_id: str,
    *,
    availability: RuntimeFeatureAvailability = RuntimeFeatureAvailability.AVAILABLE,
    depends_on: tuple[str, ...] = (),
    optional_dependencies: tuple[str, ...] = (),
    conflicts_with: tuple[str, ...] = (),
) -> RuntimeFeatureDescriptor:
    return RuntimeFeatureDescriptor(
        id=feature_id,
        display_name=feature_id.replace(".", " ").title(),
        description=f"Runtime state metadata for {feature_id}.",
        category="runtime",
        maturity=RuntimeFeatureMaturity.STABLE,
        availability=availability,
        required_services=(),
        required_capabilities=(),
        safety_level=RuntimeFeatureSafetyLevel.METADATA_ONLY,
        commercial_visibility=RuntimeFeatureCommercialVisibility.PUBLIC,
        experimental=False,
        depends_on=depends_on,
        optional_dependencies=optional_dependencies,
        conflicts_with=conflicts_with,
    )


class RuntimeStateEngineTests(unittest.TestCase):
    """Verify deterministic state calculation, propagation, and reports."""

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
        "runtime_state_engine",
    )

    def _source(
        self,
        features: tuple[RuntimeFeatureDescriptor, ...],
    ) -> RuntimeStateSource:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        for name in self.required_services:
            container.register_instance(name, object())
        service_snapshot = RuntimeServiceRegistry(
            container,
            SystemCoordinator(),
        ).snapshot(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            runtime_compatibility_status=RuntimeCompatibilityStatus.COMPATIBLE,
            diagnostics_timestamp=clock.now,
        )
        capability_manifest = RuntimeCapabilityManifestService().snapshot(
            RuntimeCapabilitySource(
                runtime_version="1.5",
                build_version="v1.5-s3",
                registered_runtime_services=container.registered_services(),
                lifecycle_state=RuntimeLifecycleState.RUNNING,
                diagnostics_health=RuntimeHealthStatus.HEALTHY,
                service_registry_health=service_snapshot.health.status,
                event_bus_available=True,
                compatibility_mode=RuntimeCompatibilityStatus.COMPATIBLE,
                service_registry_snapshot=service_snapshot,
                diagnostics_timestamp=clock.now,
                feature_registry_available=True,
                dependency_graph_available=True,
                state_engine_available=True,
            )
        )
        registry = RuntimeFeatureRegistry(features)
        feature_snapshot = registry.snapshot(
            service_registry_snapshot=service_snapshot,
            capability_manifest=capability_manifest,
            diagnostics_timestamp=clock.now,
        )
        graph_snapshot = RuntimeDependencyGraph(registry).snapshot(
            feature_registry_snapshot=feature_snapshot,
            diagnostics_timestamp=clock.now,
        )
        return RuntimeStateSource(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            diagnostics_health=RuntimeHealthStatus.HEALTHY,
            diagnostics_issues=(),
            diagnostics_timestamp=clock.now,
            service_registry_snapshot=service_snapshot,
            capability_manifest=capability_manifest,
            feature_registry_snapshot=feature_snapshot,
            dependency_graph_snapshot=graph_snapshot,
        )

    def test_ready_snapshot_is_deterministic_and_deeply_immutable(self) -> None:
        source = self._source(
            (
                _feature("feature.child", depends_on=("feature.root",)),
                _feature("feature.root"),
            )
        )
        engine = RuntimeStateEngine()

        first = engine.snapshot(source)
        second = engine.evaluate(source)

        self.assertEqual(first, second)
        self.assertIs(first.state, RuntimeStateReadiness.READY)
        self.assertEqual(
            tuple(item.feature_id for item in first.feature_readiness),
            ("feature.child", "feature.root"),
        )
        self.assertEqual(first.readiness_summary.ready_feature_count, 2)
        self.assertTrue(first.calculated_from_metadata)
        self.assertFalse(first.active_probes)
        with self.assertRaises(FrozenInstanceError):
            first.state = RuntimeStateReadiness.PARTIAL  # type: ignore[misc]
        with self.assertRaises(TypeError):
            first.dependency_impact_summary.blocking_dependencies["feature.child"] = ()  # type: ignore[index]

    def test_required_dependency_unavailability_propagates_to_consumers(self) -> None:
        source = self._source(
            (
                _feature(
                    "feature.base",
                    availability=RuntimeFeatureAvailability.UNAVAILABLE,
                ),
                _feature("feature.consumer", depends_on=("feature.base",)),
                _feature("feature.independent"),
            )
        )

        snapshot = RuntimeStateEngine().snapshot(source)

        self.assertIs(
            snapshot.get("feature.base").readiness,  # type: ignore[union-attr]
            RuntimeStateReadiness.NOT_READY,
        )
        consumer = snapshot.get("feature.consumer")
        self.assertIs(consumer.readiness, RuntimeStateReadiness.NOT_READY)  # type: ignore[union-attr]
        self.assertEqual(consumer.blocking_dependencies, ("feature.base",))  # type: ignore[union-attr]
        self.assertIs(snapshot.state, RuntimeStateReadiness.PARTIAL)
        self.assertEqual(
            snapshot.dependency_impact_summary.impacted_feature_ids,
            ("feature.base", "feature.consumer"),
        )

    def test_missing_dependencies_are_reported_in_deterministic_order(self) -> None:
        source = self._source(
            (
                _feature("feature.independent"),
                _feature(
                    "feature.required",
                    depends_on=("feature.z_missing",),
                ),
                _feature(
                    "feature.optional",
                    optional_dependencies=("feature.a_missing",),
                ),
            )
        )

        report = RuntimeStateEngine().snapshot(source).dependency_impact_summary

        self.assertEqual(
            report.missing_required_dependencies,
            (("feature.required", "feature.z_missing"),),
        )
        self.assertEqual(
            report.missing_optional_dependencies,
            (("feature.optional", "feature.a_missing"),),
        )
        self.assertEqual(
            report.blocking_dependencies,
            {"feature.required": ("feature.z_missing",)},
        )

    def test_aggregate_supports_partial_not_ready_and_unknown(self) -> None:
        partial_source = self._source(
            (
                _feature(
                    "feature.conditional",
                    availability=RuntimeFeatureAvailability.CONDITIONAL,
                ),
                _feature("feature.ready"),
            )
        )
        conflict_source = self._source(
            (
                _feature("feature.a", conflicts_with=("feature.b",)),
                _feature("feature.b", conflicts_with=("feature.a",)),
            )
        )
        timestamp = partial_source.diagnostics_timestamp
        unknown_source = RuntimeStateSource(
            lifecycle_state=RuntimeLifecycleState.RUNNING,
            diagnostics_health=RuntimeHealthStatus.UNKNOWN,
            diagnostics_issues=(),
            diagnostics_timestamp=timestamp,
        )

        partial = RuntimeStateEngine().snapshot(partial_source)
        not_ready = RuntimeStateEngine().snapshot(conflict_source)
        unknown = RuntimeStateEngine().snapshot(unknown_source)

        self.assertIs(partial.state, RuntimeStateReadiness.PARTIAL)
        self.assertEqual(partial.readiness_summary.partial_feature_count, 1)
        self.assertIs(not_ready.state, RuntimeStateReadiness.NOT_READY)
        self.assertEqual(not_ready.compatibility_summary.active_conflict_count, 1)
        self.assertIs(unknown.state, RuntimeStateReadiness.UNKNOWN)

    def test_lifecycle_and_health_are_applied_without_mutating_sources(self) -> None:
        source = self._source((_feature("feature.ready"),))

        stopped = RuntimeStateEngine().snapshot(
            replace(source, lifecycle_state=RuntimeLifecycleState.STOPPED)
        )
        degraded = RuntimeStateEngine().snapshot(
            replace(
                source,
                diagnostics_health=RuntimeHealthStatus.DEGRADED,
                diagnostics_issues=("diagnostics degraded",),
            )
        )

        self.assertIs(stopped.state, RuntimeStateReadiness.NOT_READY)
        self.assertIs(degraded.state, RuntimeStateReadiness.PARTIAL)
        self.assertEqual(degraded.health_summary.issues, ("diagnostics degraded",))
        self.assertIs(source.diagnostics_health, RuntimeHealthStatus.HEALTHY)


class RuntimeStateDiagnosticsTests(unittest.TestCase):
    """Verify same-timestamp diagnostics, capability, and DI integration."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def test_diagnostics_exports_state_reports_without_service_resolution(self) -> None:
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
        diagnostics = RuntimeDiagnostics(
            container,
            coordinator,
            lifecycle,
            RuntimeBuildMetadata("1.5", 1, 3, "v1.5-s3", "test"),
            runtime_service_registry=service_registry,
            capability_manifest_service=capability_service,
            runtime_feature_registry=feature_registry,
            runtime_dependency_graph=dependency_graph,
            runtime_state_engine=state_engine,
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
            **{name: object() for name in self.required_services},
        }
        for name, instance in services.items():
            container.register_instance(name, instance)
        diagnostics.start()

        with mock.patch.object(
            container,
            "resolve",
            side_effect=AssertionError("runtime state must not resolve services"),
        ):
            snapshot = diagnostics.snapshot()

        state = snapshot.runtime_state_snapshot
        self.assertEqual(state.diagnostics_timestamp, snapshot.captured_at)  # type: ignore[union-attr]
        self.assertIs(snapshot.readiness_summary, state.readiness_summary)  # type: ignore[union-attr]
        self.assertIs(
            snapshot.dependency_impact_summary,
            state.dependency_impact_summary,  # type: ignore[union-attr]
        )
        self.assertIs(
            snapshot.state_compatibility_summary,
            state.compatibility_summary,  # type: ignore[union-attr]
        )
        self.assertIs(snapshot.state_health_summary, state.health_summary)  # type: ignore[union-attr]
        self.assertTrue(
            snapshot.capability_manifest.runtime_state_engine_available  # type: ignore[union-attr]
        )
        self.assertTrue(
            snapshot.capability_manifest.feature_flags["runtime_state_engine"]  # type: ignore[union-attr]
        )

    def test_diagnostics_without_state_engine_remains_backward_compatible(self) -> None:
        clock = _Clock()
        diagnostics = RuntimeDiagnostics(
            DependencyContainer(clock=clock),
            SystemCoordinator(),
            SimpleNamespace(started=False, bootstrapped=False, shutting_down=False),
            RuntimeBuildMetadata("1.5", 1, 3, "build", "test"),
            clock=clock,
        )

        snapshot = diagnostics.snapshot()

        self.assertIsNone(snapshot.runtime_state_snapshot)
        self.assertIsNone(snapshot.readiness_summary)
        self.assertIsNone(snapshot.dependency_impact_summary)
        self.assertIsNone(snapshot.state_compatibility_summary)
        self.assertIsNone(snapshot.state_health_summary)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
