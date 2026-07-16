"""Focused tests for Version 1.5 Sprint 7 Runtime Profile Registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.runtime_profiles import (
    RUNTIME_PROFILE_REGISTRY_VERSION,
    RuntimeProfileCompatibilityStatus,
    RuntimeProfileDescriptor,
    RuntimeProfileReadiness,
    RuntimeProfileReferenceKind,
    RuntimeProfileRegistry,
    RuntimeProfileRegistrySnapshot,
    RuntimeProfileSource,
    RuntimeProfileValidationStatus,
    build_runtime_profile_reference,
    build_runtime_profile_registry,
)


class RuntimeProfileRegistryTests(unittest.TestCase):
    """Verify immutable, deterministic operating-profile metadata."""

    def setUp(self) -> None:
        self.captured_at = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
        self.registry = build_runtime_profile_registry()
        self.source = self._source()

    def _source(
        self,
        *,
        captured_at: datetime | None = None,
        capability_content: str = "ready",
    ) -> RuntimeProfileSource:
        def reference(
            kind: RuntimeProfileReferenceKind,
            content: object,
        ):
            return build_runtime_profile_reference(
                kind,
                version="1.0",
                content=content,
            )

        return RuntimeProfileSource(
            runtime_version="1.5",
            readiness=RuntimeProfileReadiness.READY,
            readiness_issues=(),
            configuration_reference=reference(
                RuntimeProfileReferenceKind.CONFIGURATION,
                {"environment": "development"},
            ),
            metadata_reference=reference(
                RuntimeProfileReferenceKind.METADATA,
                {"runtime": "1.5"},
            ),
            capability_reference=reference(
                RuntimeProfileReferenceKind.CAPABILITY,
                {"readiness": capability_content},
            ),
            feature_reference=reference(
                RuntimeProfileReferenceKind.FEATURE,
                {"features": ("runtime.profile_registry",)},
            ),
            captured_at=captured_at or self.captured_at,
        )

    def test_profiles_and_exports_are_deeply_immutable(self) -> None:
        snapshot = self.registry.snapshot(self.source)
        profile = snapshot.get("runtime.default")

        self.assertIsNotNone(profile)
        self.assertEqual(snapshot.registry_version, RUNTIME_PROFILE_REGISTRY_VERSION)
        self.assertTrue(  # type: ignore[union-attr]
            profile.profile_id.startswith("runtime-profile-")
        )
        self.assertEqual(profile.id, "runtime.default")  # type: ignore[union-attr]
        self.assertTrue(profile.readiness.ready)  # type: ignore[union-attr]
        self.assertTrue(snapshot.read_only)
        self.assertFalse(snapshot.active_application)
        with self.assertRaises(FrozenInstanceError):
            profile.descriptor.name = "Changed"  # type: ignore[misc, union-attr]
        exported = snapshot.export()
        with self.assertRaises(TypeError):
            exported["registry_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            exported["profiles"][0]["description"] = "changed"  # type: ignore[index]

    def test_serialization_round_trip_preserves_registry_and_profiles(self) -> None:
        snapshot = self.registry.snapshot(self.source)
        serialized = snapshot.serialize()
        restored = RuntimeProfileRegistrySnapshot.deserialize(serialized)

        self.assertEqual(restored, snapshot)
        self.assertEqual(restored.serialize(), serialized)
        profile = snapshot.profiles[0]
        self.assertEqual(type(profile).deserialize(profile.serialize()), profile)

    def test_hashing_snapshot_equality_and_timestamp_semantics(self) -> None:
        first = self.registry.snapshot(self.source)
        repeated = self.registry.snapshot(self.source)
        later = self.registry.snapshot(
            self._source(captured_at=self.captured_at + timedelta(seconds=1))
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first.registry_id, repeated.registry_id)
        self.assertNotEqual(first, later)
        self.assertEqual(first.registry_id, later.registry_id)
        comparison = first.compare(later)
        self.assertTrue(comparison.same_content)
        self.assertTrue(comparison.timestamp_changed)

    def test_profile_and_registry_validation_reports_errors(self) -> None:
        invalid = replace(
            self.registry.descriptors[0],
            minimum_runtime_version="2.0",
            maximum_runtime_version="1.5",
        )
        registry = RuntimeProfileRegistry(descriptors=(invalid,))
        report = registry.validate()

        self.assertIs(report.status, RuntimeProfileValidationStatus.INVALID)
        self.assertIn(
            "runtime.default: minimum runtime version cannot exceed maximum",
            report.issues,
        )
        with self.assertRaises(ValueError):
            self.registry.register(self.registry.descriptors[0])
        with self.assertRaises(ValueError):
            replace(invalid, id="Invalid Profile")

    def test_compatibility_validation_uses_runtime_version_range(self) -> None:
        descriptor = self.registry.descriptors[0]
        compatible = self.registry.verify_compatibility(descriptor, "1.5")
        old = self.registry.verify_compatibility(descriptor, "1.3")
        future = self.registry.verify_compatibility(descriptor, "1.6")
        unknown = self.registry.verify_compatibility(descriptor, "development")

        self.assertIs(
            compatible.status,
            RuntimeProfileCompatibilityStatus.COMPATIBLE,
        )
        self.assertIs(old.status, RuntimeProfileCompatibilityStatus.INCOMPATIBLE)
        self.assertIs(future.status, RuntimeProfileCompatibilityStatus.INCOMPATIBLE)
        self.assertIs(unknown.status, RuntimeProfileCompatibilityStatus.UNKNOWN)

    def test_comparison_reports_changed_profile_content(self) -> None:
        first = self.registry.snapshot(self.source)
        changed = self.registry.snapshot(
            self._source(capability_content="partial")
        )
        comparison = self.registry.compare(first, changed)

        self.assertFalse(comparison.same_content)
        self.assertEqual(
            comparison.changed_profile_ids,
            ("runtime.default", "runtime.observability"),
        )
        profile_comparison = first.profiles[0].compare(changed.profiles[0])
        self.assertIn("capability_reference", profile_comparison.changed_sections)

    def test_detached_serialized_copy_cannot_mutate_snapshot(self) -> None:
        snapshot = self.registry.snapshot(self.source)
        detached = snapshot.to_dict()
        detached["profiles"][0]["descriptor"]["name"] = "Changed"  # type: ignore[index]
        detached["profiles"].append({"id": "added"})  # type: ignore[union-attr]

        self.assertEqual(snapshot.profiles[0].name, "Default Runtime Profile")
        self.assertNotEqual(snapshot.to_dict(), detached)

    def test_registration_and_exports_use_deterministic_ordering(self) -> None:
        descriptor = RuntimeProfileDescriptor(
            id="commercial.standard",
            name="Commercial Standard Profile",
            version="1.0",
            category="commercial",
            description="Describes passive commercial runtime metadata.",
            minimum_runtime_version="1.4",
            maximum_runtime_version="1.5",
        )
        registry = RuntimeProfileRegistry(
            descriptors=tuple(reversed((*self.registry.descriptors, descriptor)))
        )
        snapshot = registry.snapshot(self.source)

        self.assertEqual(
            tuple(item.id for item in registry.descriptors),
            tuple(sorted(item.id for item in registry.descriptors)),
        )
        self.assertEqual(
            tuple(item.id for item in snapshot.profiles),
            tuple(sorted(item.id for item in snapshot.profiles)),
        )
        self.assertEqual(
            snapshot.profile_summary.categories,
            ("commercial", "observability", "runtime"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
