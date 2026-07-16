"""Focused tests for Version 1.5 Sprint 8 Runtime Policy Registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.runtime_policies import (
    RUNTIME_POLICY_REGISTRY_VERSION,
    RuntimePolicyCompatibilityStatus,
    RuntimePolicyDescriptor,
    RuntimePolicyReadiness,
    RuntimePolicyRegistry,
    RuntimePolicyRegistrySnapshot,
    RuntimePolicySource,
    RuntimePolicyValidationStatus,
    build_runtime_policy_registry,
)


class RuntimePolicyRegistryTests(unittest.TestCase):
    """Verify passive immutable deterministic policy metadata."""

    def setUp(self) -> None:
        self.captured_at = datetime(2026, 7, 16, 22, 0, tzinfo=timezone.utc)
        self.registry = build_runtime_policy_registry()
        self.source = RuntimePolicySource(
            runtime_version="1.5",
            runtime_readiness=RuntimePolicyReadiness.READY,
            readiness_issues=(),
            captured_at=self.captured_at,
        )

    @staticmethod
    def _descriptor(
        policy_id: str,
        *,
        priority: int = 300,
        depends_on: tuple[str, ...] = (),
        optional_dependencies: tuple[str, ...] = (),
    ) -> RuntimePolicyDescriptor:
        return RuntimePolicyDescriptor(
            id=policy_id,
            name=f"Policy {policy_id}",
            version="1.0",
            description="Describes passive runtime policy metadata.",
            category="runtime_policy",
            scope="runtime.metadata",
            priority=priority,
            minimum_runtime_version="1.4",
            maximum_runtime_version="1.5",
            depends_on=depends_on,
            optional_dependencies=optional_dependencies,
        )

    def test_policy_descriptors_snapshots_and_exports_are_immutable(self) -> None:
        snapshot = self.registry.snapshot(self.source)
        policy = snapshot.get("runtime.metadata_integrity")

        self.assertIsNotNone(policy)
        self.assertEqual(snapshot.registry_version, RUNTIME_POLICY_REGISTRY_VERSION)
        self.assertEqual(  # type: ignore[union-attr]
            policy.name,
            "Runtime Metadata Integrity Policy",
        )
        self.assertEqual(policy.scope, "runtime.metadata")  # type: ignore[union-attr]
        self.assertTrue(policy.readiness.ready)  # type: ignore[union-attr]
        self.assertFalse(policy.active_enforcement)  # type: ignore[union-attr]
        with self.assertRaises(FrozenInstanceError):
            policy.descriptor.priority = 1  # type: ignore[misc, union-attr]
        exported = snapshot.export()
        with self.assertRaises(TypeError):
            exported["registry_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            exported["policies"][0]["descriptor"]["name"] = "changed"  # type: ignore[index]

    def test_serialization_round_trip_preserves_integrity(self) -> None:
        snapshot = self.registry.snapshot(self.source)
        serialized = snapshot.serialize()
        restored = RuntimePolicyRegistrySnapshot.deserialize(serialized)

        self.assertEqual(restored, snapshot)
        self.assertEqual(restored.serialize(), serialized)
        policy = snapshot.policies[0]
        self.assertEqual(type(policy).deserialize(policy.serialize()), policy)

    def test_hashing_and_timestamp_comparison_are_deterministic(self) -> None:
        first = self.registry.snapshot(self.source)
        repeated = self.registry.snapshot(self.source)
        later = self.registry.snapshot(
            replace(
                self.source,
                captured_at=self.captured_at + timedelta(seconds=1),
            )
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first.registry_id, repeated.registry_id)
        self.assertNotEqual(first, later)
        self.assertEqual(first.registry_id, later.registry_id)
        comparison = first.compare(later)
        self.assertTrue(comparison.same_content)
        self.assertTrue(comparison.timestamp_changed)

    def test_registration_uses_priority_then_identifier_ordering(self) -> None:
        later = self._descriptor("runtime.zeta", priority=300)
        earlier = self._descriptor("runtime.alpha", priority=50)
        registry = RuntimePolicyRegistry(
            descriptors=tuple(reversed((*self.registry.descriptors, later, earlier)))
        )
        snapshot = registry.snapshot(self.source)

        self.assertEqual(registry.descriptors[0].id, "runtime.alpha")
        self.assertEqual(
            tuple((item.priority, item.id) for item in snapshot.policies),
            tuple(
                sorted(
                    (item.priority, item.id) for item in snapshot.policies
                )
            ),
        )
        with self.assertRaises(ValueError):
            registry.register(registry.descriptors[0])

    def test_compatibility_validation_uses_runtime_range(self) -> None:
        descriptor = self.registry.descriptors[0]
        compatible = self.registry.verify_compatibility(descriptor, "1.5")
        old = self.registry.verify_compatibility(descriptor, "1.3")
        future = self.registry.verify_compatibility(descriptor, "1.6")
        unknown = self.registry.verify_compatibility(descriptor, "development")

        self.assertIs(
            compatible.status,
            RuntimePolicyCompatibilityStatus.COMPATIBLE,
        )
        self.assertIs(old.status, RuntimePolicyCompatibilityStatus.INCOMPATIBLE)
        self.assertIs(future.status, RuntimePolicyCompatibilityStatus.INCOMPATIBLE)
        self.assertIs(unknown.status, RuntimePolicyCompatibilityStatus.UNKNOWN)

    def test_dependency_and_validation_metadata_report_missing_and_cycles(self) -> None:
        missing = self._descriptor(
            "runtime.missing_consumer",
            depends_on=("runtime.absent",),
            optional_dependencies=("runtime.optional",),
        )
        cycle_a = self._descriptor(
            "runtime.cycle_a",
            depends_on=("runtime.cycle_b",),
        )
        cycle_b = self._descriptor(
            "runtime.cycle_b",
            depends_on=("runtime.cycle_a",),
        )
        registry = RuntimePolicyRegistry(descriptors=(missing, cycle_b, cycle_a))
        snapshot = registry.snapshot(self.source)
        missing_policy = snapshot.get("runtime.missing_consumer")

        self.assertIs(
            snapshot.validation_report.status,
            RuntimePolicyValidationStatus.INVALID,
        )
        self.assertEqual(
            missing_policy.dependencies.missing_required_dependencies,  # type: ignore[union-attr]
            ("runtime.absent",),
        )
        self.assertEqual(
            missing_policy.dependencies.missing_optional_dependencies,  # type: ignore[union-attr]
            ("runtime.optional",),
        )
        self.assertTrue(  # type: ignore[union-attr]
            snapshot.get("runtime.cycle_a").dependencies.circular
        )

    def test_readiness_is_metadata_only_and_dependency_aware(self) -> None:
        partial = self.registry.snapshot(
            replace(
                self.source,
                runtime_readiness=RuntimePolicyReadiness.PARTIAL,
                readiness_issues=("runtime metadata is partial",),
            )
        )
        missing_registry = RuntimePolicyRegistry(
            descriptors=(
                self._descriptor(
                    "runtime.blocked",
                    depends_on=("runtime.absent",),
                ),
            )
        )
        blocked = missing_registry.snapshot(self.source).policies[0]

        self.assertTrue(
            all(
                item.readiness.state is RuntimePolicyReadiness.PARTIAL
                for item in partial.policies
            )
        )
        self.assertIs(blocked.readiness.state, RuntimePolicyReadiness.NOT_READY)
        self.assertTrue(blocked.readiness.calculated_from_metadata)
        self.assertFalse(blocked.readiness.active_evaluation)

    def test_comparison_and_detached_copy_report_policy_changes(self) -> None:
        first = self.registry.snapshot(self.source)
        changed_registry = RuntimePolicyRegistry(
            descriptors=(
                replace(self.registry.descriptors[0], description="Changed metadata."),
                self.registry.descriptors[1],
            )
        )
        changed = changed_registry.snapshot(self.source)
        comparison = first.compare(changed)
        detached = first.to_dict()
        detached["policies"][0]["descriptor"]["description"] = "Detached"  # type: ignore[index]

        self.assertEqual(
            comparison.changed_policy_ids,
            ("runtime.metadata_integrity",),
        )
        self.assertIn(
            "descriptor",
            first.policies[0].compare(changed.policies[0]).changed_sections,
        )
        self.assertNotEqual(first.to_dict(), detached)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
