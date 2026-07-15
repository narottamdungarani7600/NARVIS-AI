"""Focused tests for Version 1.5 Sprint 2 runtime feature relationships."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest import mock

from Core import (
    RuntimeBuildMetadata,
    RuntimeCapabilityManifestService,
    RuntimeDependencyGraph,
    RuntimeDependencyGraphSnapshot,
    RuntimeDiagnostics,
    RuntimeFeatureAvailability,
    RuntimeFeatureCommercialVisibility,
    RuntimeFeatureCompatibilityStatus,
    RuntimeFeatureDependencyType,
    RuntimeFeatureDescriptor,
    RuntimeFeatureMaturity,
    RuntimeFeatureRegistry,
    RuntimeFeatureSafetyLevel,
    RuntimeFeatureValidationStatus,
    RuntimeHealthStatus,
    RuntimeServiceRegistry,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)

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
    compatible_with: tuple[str, ...] = (),
    conflicts_with: tuple[str, ...] = (),
    parent_feature_id: str | None = None,
    category: str = "runtime",
    category_parent: str | None = None,
    groups: tuple[str, ...] = (),
) -> RuntimeFeatureDescriptor:
    return RuntimeFeatureDescriptor(
        id=feature_id,
        display_name=feature_id.replace(".", " ").title(),
        description=f"Relationship metadata for {feature_id}.",
        category=category,
        maturity=RuntimeFeatureMaturity.STABLE,
        availability=availability,
        required_services=(),
        required_capabilities=(),
        safety_level=RuntimeFeatureSafetyLevel.METADATA_ONLY,
        commercial_visibility=RuntimeFeatureCommercialVisibility.PUBLIC,
        experimental=False,
        depends_on=depends_on,
        optional_dependencies=optional_dependencies,
        compatible_with=compatible_with,
        conflicts_with=conflicts_with,
        parent_feature_id=parent_feature_id,
        category_parent=category_parent,
        groups=groups,
    )


class RuntimeDependencyGraphTests(unittest.TestCase):
    """Verify graph structure, ordering, relationships, and immutability."""

    def test_graph_is_deterministic_with_parent_child_and_reverse_edges(self) -> None:
        registry = RuntimeFeatureRegistry(
            (
                _feature(
                    "feature.leaf",
                    depends_on=("feature.child",),
                    parent_feature_id="feature.child",
                    groups=("suite",),
                ),
                _feature(
                    "feature.root",
                    category="core",
                    category_parent="platform",
                    groups=("suite",),
                ),
                _feature(
                    "feature.child",
                    depends_on=("feature.root",),
                    optional_dependencies=("feature.addon",),
                    parent_feature_id="feature.root",
                    groups=("suite",),
                ),
            )
        )
        graph = RuntimeDependencyGraph(registry)

        first = graph.snapshot()
        second = graph.snapshot()

        self.assertEqual(first, second)
        self.assertEqual(
            first.ordered_feature_ids,
            ("feature.root", "feature.child", "feature.leaf"),
        )
        self.assertEqual(
            tuple(
                (edge.feature_id, edge.dependency_id, edge.dependency_type)
                for edge in first.edges
            ),
            (
                (
                    "feature.child",
                    "feature.root",
                    RuntimeFeatureDependencyType.REQUIRED,
                ),
                (
                    "feature.child",
                    "feature.addon",
                    RuntimeFeatureDependencyType.OPTIONAL,
                ),
                (
                    "feature.leaf",
                    "feature.child",
                    RuntimeFeatureDependencyType.REQUIRED,
                ),
            ),
        )
        root = first.get("feature.root")
        child = first.relationship_summary.get("feature.child")
        self.assertEqual(root.child_feature_ids, ("feature.child",))  # type: ignore[union-attr]
        self.assertEqual(root.required_by, ("feature.child",))  # type: ignore[union-attr]
        self.assertEqual(child.depends_on, ("feature.root",))  # type: ignore[union-attr]
        self.assertEqual(child.required_by, ("feature.leaf",))  # type: ignore[union-attr]
        self.assertEqual(
            first.relationship_summary.category_hierarchy,
            {"platform": ("core",)},
        )
        self.assertEqual(
            first.relationship_summary.feature_groups["suite"],
            ("feature.child", "feature.leaf", "feature.root"),
        )

    def test_graph_and_relationship_exports_are_deeply_immutable(self) -> None:
        snapshot = RuntimeDependencyGraph(
            RuntimeFeatureRegistry((_feature("feature.one", groups=("suite",)),))
        ).snapshot()

        self.assertIsInstance(snapshot, RuntimeDependencyGraphSnapshot)
        with self.assertRaises(FrozenInstanceError):
            snapshot.nodes[0].feature_id = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            snapshot.relationship_summary.feature_groups["suite"] = ()  # type: ignore[index]
        with self.assertRaises(TypeError):
            snapshot.ordered_feature_ids[0] = "changed"  # type: ignore[index]

    def test_required_missing_dependencies_block_and_propagate_readiness(self) -> None:
        registry = RuntimeFeatureRegistry(
            (
                _feature("feature.base", depends_on=("feature.missing",)),
                _feature("feature.consumer", depends_on=("feature.base",)),
                _feature(
                    "feature.optional",
                    optional_dependencies=("feature.addon",),
                ),
            )
        )

        report = RuntimeDependencyGraph(registry).snapshot().validation_report

        self.assertIs(report.status, RuntimeFeatureValidationStatus.INVALID)
        self.assertEqual(
            tuple(
                (edge.feature_id, edge.dependency_id)
                for edge in report.missing_required_dependencies
            ),
            (("feature.base", "feature.missing"),),
        )
        self.assertEqual(
            tuple(
                (edge.feature_id, edge.dependency_id)
                for edge in report.missing_optional_dependencies
            ),
            (("feature.optional", "feature.addon"),),
        )
        self.assertIs(
            report.get("feature.base").readiness,  # type: ignore[union-attr]
            RuntimeFeatureAvailability.UNAVAILABLE,
        )
        consumer = report.get("feature.consumer")
        self.assertEqual(
            consumer.unavailable_required_dependencies,  # type: ignore[union-attr]
            ("feature.base",),
        )
        self.assertIs(
            consumer.readiness,  # type: ignore[union-attr]
            RuntimeFeatureAvailability.UNAVAILABLE,
        )
        self.assertIs(
            report.get("feature.optional").readiness,  # type: ignore[union-attr]
            RuntimeFeatureAvailability.AVAILABLE,
        )

    def test_required_and_optional_cycles_are_detected_deterministically(self) -> None:
        required_cycle = RuntimeDependencyGraph(
            RuntimeFeatureRegistry(
                (
                    _feature("feature.a", depends_on=("feature.b",)),
                    _feature("feature.b", depends_on=("feature.a",)),
                )
            )
        ).snapshot()
        optional_cycle = RuntimeDependencyGraph(
            RuntimeFeatureRegistry(
                (
                    _feature(
                        "feature.c",
                        optional_dependencies=("feature.d",),
                    ),
                    _feature(
                        "feature.d",
                        optional_dependencies=("feature.c",),
                    ),
                )
            )
        ).snapshot()

        self.assertEqual(
            tuple(
                (cycle.feature_ids, cycle.required_only)
                for cycle in required_cycle.circular_dependencies
            ),
            ((("feature.a", "feature.b"), True),),
        )
        self.assertIs(
            required_cycle.validation_report.status,
            RuntimeFeatureValidationStatus.INVALID,
        )
        self.assertEqual(
            required_cycle.validation_report.unavailable_feature_ids,
            ("feature.a", "feature.b"),
        )
        self.assertEqual(
            tuple(
                (cycle.feature_ids, cycle.required_only)
                for cycle in optional_cycle.circular_dependencies
            ),
            ((("feature.c", "feature.d"), False),),
        )
        self.assertIs(
            optional_cycle.validation_report.status,
            RuntimeFeatureValidationStatus.DEGRADED,
        )
        self.assertEqual(
            optional_cycle.validation_report.ready_feature_ids,
            ("feature.c", "feature.d"),
        )

    def test_missing_parent_and_category_cycles_are_reported(self) -> None:
        snapshot = RuntimeDependencyGraph(
            RuntimeFeatureRegistry(
                (
                    _feature(
                        "feature.child",
                        parent_feature_id="feature.missing",
                        category="child_category",
                        category_parent="parent_category",
                    ),
                    _feature(
                        "feature.parent-category",
                        category="parent_category",
                        category_parent="child_category",
                    ),
                )
            )
        ).snapshot()

        report = snapshot.validation_report
        self.assertEqual(
            report.missing_parents,
            (("feature.child", "feature.missing"),),
        )
        self.assertEqual(
            report.category_cycles,
            (("child_category", "parent_category"),),
        )
        self.assertIs(report.status, RuntimeFeatureValidationStatus.INVALID)


class RuntimeFeatureCompatibilityTests(unittest.TestCase):
    """Verify compatibility, conflict, and contradiction validation."""

    def test_symmetric_compatibility_is_valid(self) -> None:
        snapshot = RuntimeDependencyGraph(
            RuntimeFeatureRegistry(
                (
                    _feature("feature.a", compatible_with=("feature.b",)),
                    _feature("feature.b", compatible_with=("feature.a",)),
                )
            )
        ).snapshot()

        report = snapshot.compatibility_report
        self.assertIs(
            report.status,
            RuntimeFeatureCompatibilityStatus.COMPATIBLE,
        )
        self.assertEqual(report.compatible_pairs, (("feature.a", "feature.b"),))
        self.assertEqual(report.asymmetric_compatibilities, ())

    def test_missing_and_asymmetric_compatibility_is_degraded(self) -> None:
        report = RuntimeDependencyGraph(
            RuntimeFeatureRegistry(
                (
                    _feature(
                        "feature.a",
                        compatible_with=("feature.b", "feature.missing"),
                    ),
                    _feature("feature.b"),
                )
            )
        ).snapshot().compatibility_report

        self.assertIs(
            report.status,
            RuntimeFeatureCompatibilityStatus.DEGRADED,
        )
        self.assertEqual(
            report.asymmetric_compatibilities,
            (("feature.a", "feature.b"),),
        )
        self.assertEqual(
            report.missing_references,
            (("feature.a", "feature.missing", "compatible_with"),),
        )

    def test_active_conflicts_invalidate_compatibility_and_readiness(self) -> None:
        snapshot = RuntimeDependencyGraph(
            RuntimeFeatureRegistry(
                (
                    _feature(
                        "feature.a",
                        compatible_with=("feature.b",),
                        conflicts_with=("feature.b",),
                    ),
                    _feature("feature.b", compatible_with=("feature.a",)),
                )
            )
        ).snapshot()

        compatibility = snapshot.compatibility_report
        self.assertIs(
            compatibility.status,
            RuntimeFeatureCompatibilityStatus.INCOMPATIBLE,
        )
        self.assertEqual(
            compatibility.active_conflicts,
            (("feature.a", "feature.b"),),
        )
        self.assertEqual(
            compatibility.contradictory_relationships,
            (("feature.a", "feature.b"),),
        )
        self.assertEqual(
            snapshot.validation_report.unavailable_feature_ids,
            ("feature.a", "feature.b"),
        )


class RuntimeDependencyGraphDiagnosticsTests(unittest.TestCase):
    """Verify same-timestamp passive diagnostics and DI integration."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def test_diagnostics_exports_graph_and_reports_without_service_resolution(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        coordinator = SystemCoordinator()
        coordinator.register(
            SimpleNamespace(name="ai_runtime", state=ComponentState.INITIALIZED)
        )
        bus = EventBus()
        state = SimpleNamespace(started=True, bootstrapped=True, shutting_down=False)
        service_registry = RuntimeServiceRegistry(container, coordinator)
        capability_service = RuntimeCapabilityManifestService()
        feature_registry = RuntimeFeatureRegistry(
            (
                _feature("feature.root"),
                _feature("feature.child", depends_on=("feature.root",)),
            )
        )
        dependency_graph = RuntimeDependencyGraph(feature_registry)
        diagnostics = RuntimeDiagnostics(
            container,
            coordinator,
            state,
            RuntimeBuildMetadata("1.5", 1, 2, "v1.5-s2", "test"),
            runtime_service_registry=service_registry,
            capability_manifest_service=capability_service,
            runtime_feature_registry=feature_registry,
            runtime_dependency_graph=dependency_graph,
            event_bus=bus,
            logger=_Logger(),
            clock=clock,
        )
        services = {
            "coordinator": coordinator,
            "event_bus": bus,
            "lifecycle_manager": object(),
            "runtime_status": state,
            "runtime_diagnostics": diagnostics,
            "runtime_service_registry": service_registry,
            "runtime_capability_manifest": capability_service,
            "runtime_feature_registry": feature_registry,
            "runtime_dependency_graph": dependency_graph,
            **{name: object() for name in self.required_services},
        }
        for name, instance in services.items():
            container.register_instance(name, instance)
        diagnostics.start()

        with mock.patch.object(
            container,
            "resolve",
            side_effect=AssertionError("dependency graphs must not resolve services"),
        ):
            snapshot = diagnostics.snapshot()

        graph = snapshot.dependency_graph_snapshot
        self.assertIsInstance(graph, RuntimeDependencyGraphSnapshot)
        self.assertEqual(graph.diagnostics_timestamp, snapshot.captured_at)
        self.assertIs(snapshot.relationship_summary, graph.relationship_summary)  # type: ignore[union-attr]
        self.assertIs(snapshot.validation_report, graph.validation_report)  # type: ignore[union-attr]
        self.assertIs(snapshot.compatibility_report, graph.compatibility_report)  # type: ignore[union-attr]
        self.assertTrue(snapshot.capability_manifest.runtime_dependency_graph_available)  # type: ignore[union-attr]
        self.assertTrue(snapshot.capability_manifest.feature_flags["runtime_dependency_graph"])  # type: ignore[union-attr]
        self.assertIn(
            "runtime_dependency_graph",
            tuple(
                item.service_name
                for item in snapshot.service_registry_snapshot.services  # type: ignore[union-attr]
            ),
        )
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.HEALTHY)

    def test_diagnostics_without_graph_remains_backward_compatible(self) -> None:
        clock = _Clock()
        diagnostics = RuntimeDiagnostics(
            DependencyContainer(clock=clock),
            SystemCoordinator(),
            SimpleNamespace(started=False, bootstrapped=False, shutting_down=False),
            RuntimeBuildMetadata("1.5", 1, 2, "build", "test"),
            clock=clock,
        )

        snapshot = diagnostics.snapshot()
        self.assertIsNone(snapshot.dependency_graph_snapshot)
        self.assertIsNone(snapshot.relationship_summary)
        self.assertIsNone(snapshot.validation_report)
        self.assertIsNone(snapshot.compatibility_report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
