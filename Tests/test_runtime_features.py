"""Focused tests for Version 1.5 Sprint 1 Runtime Feature Registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest import mock

from Core import (
    RuntimeBuildMetadata,
    RuntimeCapabilityManifestService,
    RuntimeCapabilitySource,
    RuntimeCompatibilityStatus,
    RuntimeDiagnostics,
    RuntimeFeatureAvailability,
    RuntimeFeatureCommercialVisibility,
    RuntimeFeatureDescriptor,
    RuntimeFeatureMaturity,
    RuntimeFeatureRegistry,
    RuntimeFeatureRegistrySnapshot,
    RuntimeFeatureSafetyLevel,
    RuntimeHealthStatus,
    RuntimeLifecycleState,
    RuntimeServiceRegistry,
    build_runtime_feature_registry,
    build_runtime_configuration_registry,
    build_runtime_metadata_catalog,
)
from Core.system import ComponentState, DependencyContainer, EventBus, SystemCoordinator


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Logger:
    def log(self, level: object, message: str, **context: object) -> None:
        return None


def _feature(
    feature_id: str,
    *,
    category: str = "runtime",
    visibility: RuntimeFeatureCommercialVisibility = (
        RuntimeFeatureCommercialVisibility.PUBLIC
    ),
    required_services: tuple[str, ...] = (),
    required_capabilities: tuple[str, ...] = (),
) -> RuntimeFeatureDescriptor:
    return RuntimeFeatureDescriptor(
        id=feature_id,
        display_name=feature_id.replace(".", " ").title(),
        description=f"Description for {feature_id}.",
        category=category,
        maturity=RuntimeFeatureMaturity.STABLE,
        availability=RuntimeFeatureAvailability.AVAILABLE,
        required_services=required_services,
        required_capabilities=required_capabilities,
        safety_level=RuntimeFeatureSafetyLevel.METADATA_ONLY,
        commercial_visibility=visibility,
        experimental=False,
    )


class RuntimeFeatureRegistryTests(unittest.TestCase):
    """Verify registration, validation, ordering, grouping, and exports."""

    def test_registers_and_returns_immutable_feature_descriptors(self) -> None:
        registry = RuntimeFeatureRegistry()
        descriptor = _feature(
            "runtime.catalogue",
            required_services=("runtime_service_registry", "event_bus"),
            required_capabilities=("diagnostics", "lifecycle"),
        )

        registered = registry.register(descriptor)

        self.assertIs(registered, descriptor)
        self.assertIs(registry.get(descriptor.id), descriptor)
        self.assertEqual(
            descriptor.required_services,
            ("event_bus", "runtime_service_registry"),
        )
        self.assertEqual(
            descriptor.required_capabilities,
            ("diagnostics", "lifecycle"),
        )
        with self.assertRaises(FrozenInstanceError):
            descriptor.display_name = "Changed"  # type: ignore[misc]

    def test_duplicate_ids_are_rejected_without_partial_registration(self) -> None:
        existing = _feature("runtime.existing")
        registry = RuntimeFeatureRegistry((existing,))

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(_feature("runtime.existing"))
        with self.assertRaisesRegex(ValueError, "duplicate feature ids"):
            registry.register_many(
                (_feature("runtime.new"), _feature("runtime.new"))
            )
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register_many(
                (_feature("runtime.other"), _feature("runtime.existing"))
            )

        self.assertIsNone(registry.get("runtime.new"))
        self.assertIsNone(registry.get("runtime.other"))
        self.assertEqual(registry.snapshot().features, (existing,))

    def test_snapshots_use_deterministic_id_and_category_ordering(self) -> None:
        registry = RuntimeFeatureRegistry(
            (
                _feature("voice.listen", category="voice"),
                _feature("core.lifecycle", category="core"),
                _feature("voice.speak", category="voice"),
            )
        )

        first = registry.snapshot()
        second = registry.snapshot()

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(item.id for item in first.features),
            ("core.lifecycle", "voice.listen", "voice.speak"),
        )
        self.assertEqual(tuple(first.features_by_category), ("core", "voice"))
        self.assertEqual(
            tuple(item.id for item in first.by_category("voice")),
            ("voice.listen", "voice.speak"),
        )
        self.assertEqual(first.by_category("missing"), ())

    def test_public_exports_are_deeply_immutable_and_visibility_filtered(self) -> None:
        registry = RuntimeFeatureRegistry(
            (
                _feature("runtime.public"),
                _feature(
                    "runtime.internal",
                    visibility=RuntimeFeatureCommercialVisibility.INTERNAL,
                ),
            )
        )

        snapshot = registry.snapshot()
        exported = snapshot.export_public_summaries()

        self.assertEqual(tuple(item.id for item in exported), ("runtime.public",))
        self.assertIs(exported, snapshot.public_summaries)
        self.assertFalse(hasattr(exported[0], "required_services"))
        with self.assertRaises(TypeError):
            snapshot.features_by_category["runtime"] = ()  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            exported[0].display_name = "Changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            exported[0].required_capabilities[0] = "changed"  # type: ignore[index]


class RuntimeFeatureDiagnosticsIntegrationTests(unittest.TestCase):
    """Verify passive service, capability, and diagnostics integration."""

    required_services = (
        "ai_manager",
        "ai_provider",
        "ai_runtime_adapter",
        "brain_engine",
        "brain_provider",
        "conversation_manager",
    )

    def test_diagnostics_embeds_same_timestamp_evaluated_feature_snapshot(self) -> None:
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
        feature_registry = build_runtime_feature_registry()
        configuration_registry = build_runtime_configuration_registry()
        metadata_catalog = build_runtime_metadata_catalog()
        diagnostics = RuntimeDiagnostics(
            container,
            coordinator,
            state,
            RuntimeBuildMetadata("1.5", 1, 1, "v1.5-s1", "test"),
            runtime_service_registry=service_registry,
            capability_manifest_service=capability_service,
            runtime_feature_registry=feature_registry,
            runtime_configuration_registry=configuration_registry,
            runtime_metadata_catalog=metadata_catalog,
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
            "runtime_configuration_registry": configuration_registry,
            "runtime_metadata_catalog": metadata_catalog,
            **{name: object() for name in self.required_services},
        }
        for name, instance in services.items():
            container.register_instance(name, instance)
        diagnostics.start()

        with mock.patch.object(
            container,
            "resolve",
            side_effect=AssertionError("feature snapshots must not resolve services"),
        ):
            snapshot = diagnostics.snapshot()

        feature_snapshot = snapshot.feature_registry_snapshot
        self.assertIsInstance(feature_snapshot, RuntimeFeatureRegistrySnapshot)
        self.assertEqual(feature_snapshot.diagnostics_timestamp, snapshot.captured_at)
        self.assertTrue(feature_snapshot.evaluated_from_runtime_metadata)
        self.assertTrue(snapshot.capability_manifest.runtime_feature_registry_available)  # type: ignore[union-attr]
        self.assertTrue(snapshot.capability_manifest.feature_flags["runtime_feature_registry"])  # type: ignore[union-attr]
        self.assertIn(
            "runtime_feature_registry",
            tuple(
                item.service_name
                for item in snapshot.service_registry_snapshot.services  # type: ignore[union-attr]
            ),
        )
        self.assertIs(
            feature_snapshot.get("runtime.dependency_graph").availability,
            RuntimeFeatureAvailability.UNAVAILABLE,
        )
        self.assertTrue(
            all(
                item.availability is RuntimeFeatureAvailability.AVAILABLE
                for item in feature_snapshot.features
                if item.id
                not in (
                    "runtime.dependency_graph",
                    "runtime.observability",
                    "runtime.policy_registry",
                    "runtime.profile_registry",
                    "runtime.state_engine",
                )
            )
        )
        self.assertIs(snapshot.health.status, RuntimeHealthStatus.HEALTHY)

    def test_runtime_metadata_marks_unmet_feature_requirements_unavailable(self) -> None:
        clock = _Clock()
        container = DependencyContainer(clock=clock)
        container.register_instance("runtime_service_registry", object())
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
                build_version="v1.5-s1",
                registered_runtime_services=container.registered_services(),
                lifecycle_state=RuntimeLifecycleState.RUNNING,
                diagnostics_health=RuntimeHealthStatus.HEALTHY,
                service_registry_health=service_snapshot.health.status,
                event_bus_available=False,
                compatibility_mode=RuntimeCompatibilityStatus.COMPATIBLE,
                service_registry_snapshot=service_snapshot,
                diagnostics_timestamp=clock.now,
            )
        )
        registry = RuntimeFeatureRegistry(
            (
                _feature(
                    "runtime.missing",
                    required_services=("missing_service",),
                    required_capabilities=("missing_capability",),
                ),
            )
        )

        snapshot = registry.snapshot(
            service_registry_snapshot=service_snapshot,
            capability_manifest=capability_manifest,
        )

        self.assertIs(
            snapshot.features[0].availability,
            RuntimeFeatureAvailability.UNAVAILABLE,
        )
        self.assertEqual(snapshot.diagnostics_timestamp, clock.now)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
