"""Focused tests for Version 1.5 Sprint 5 Runtime Metadata Catalog."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.runtime_metadata import (
    NARVIS_ARCHITECTURE_VERSION,
    NARVIS_COMPATIBILITY_VERSION,
    NARVIS_REPOSITORY_VERSION,
    RUNTIME_CAPABILITY_MANIFEST_VERSION,
    RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION,
    RUNTIME_CONFIGURATION_SCHEMA_VERSION,
    RUNTIME_CONFIGURATION_VERSION,
    RUNTIME_DEPENDENCY_GRAPH_VERSION,
    RUNTIME_DIAGNOSTICS_VERSION,
    RUNTIME_FEATURE_REGISTRY_VERSION,
    RUNTIME_METADATA_CATALOG_VERSION,
    RUNTIME_METADATA_SCHEMA_VERSION,
    RUNTIME_OBSERVABILITY_VERSION,
    RUNTIME_PROFILE_COMPATIBILITY_VERSION,
    RUNTIME_PROFILE_REGISTRY_VERSION,
    RUNTIME_PROFILE_SCHEMA_VERSION,
    RUNTIME_POLICY_COMPATIBILITY_VERSION,
    RUNTIME_POLICY_REGISTRY_VERSION,
    RUNTIME_POLICY_SCHEMA_VERSION,
    RUNTIME_STATE_VERSION,
    RuntimeMetadataCatalog,
    RuntimeMetadataCompatibilityStatus,
    RuntimeMetadataSnapshot,
    RuntimeMetadataValidationStatus,
    build_runtime_metadata_catalog,
)


class RuntimeMetadataCatalogTests(unittest.TestCase):
    """Verify deterministic immutable version metadata behavior."""

    def setUp(self) -> None:
        self.captured_at = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
        self.catalog = build_runtime_metadata_catalog()

    def test_complete_metadata_is_valid_and_immutable(self) -> None:
        snapshot = self.catalog.snapshot(captured_at=self.captured_at)

        self.assertEqual(snapshot.runtime_version, NARVIS_ARCHITECTURE_VERSION)
        self.assertEqual(
            snapshot.architecture_version,
            NARVIS_ARCHITECTURE_VERSION,
        )
        self.assertEqual(snapshot.schema_version, RUNTIME_METADATA_SCHEMA_VERSION)
        self.assertEqual(snapshot.repository_version, NARVIS_REPOSITORY_VERSION)
        self.assertEqual(
            snapshot.compatibility_version,
            NARVIS_COMPATIBILITY_VERSION,
        )
        self.assertEqual(
            snapshot.feature_registry_version,
            RUNTIME_FEATURE_REGISTRY_VERSION,
        )
        self.assertEqual(
            snapshot.capability_manifest_version,
            RUNTIME_CAPABILITY_MANIFEST_VERSION,
        )
        self.assertEqual(
            snapshot.dependency_graph_version,
            RUNTIME_DEPENDENCY_GRAPH_VERSION,
        )
        self.assertEqual(snapshot.runtime_state_version, RUNTIME_STATE_VERSION)
        self.assertEqual(
            snapshot.observability_version,
            RUNTIME_OBSERVABILITY_VERSION,
        )
        self.assertEqual(snapshot.diagnostics_version, RUNTIME_DIAGNOSTICS_VERSION)
        self.assertEqual(
            snapshot.versions.metadata_catalog_version,
            RUNTIME_METADATA_CATALOG_VERSION,
        )
        self.assertEqual(
            snapshot.runtime_configuration_version,
            RUNTIME_CONFIGURATION_VERSION,
        )
        self.assertEqual(
            snapshot.configuration_schema_version,
            RUNTIME_CONFIGURATION_SCHEMA_VERSION,
        )
        self.assertEqual(
            snapshot.configuration_compatibility_version,
            RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION,
        )
        self.assertEqual(
            snapshot.runtime_profile_registry_version,
            RUNTIME_PROFILE_REGISTRY_VERSION,
        )
        self.assertEqual(snapshot.profile_schema_version, RUNTIME_PROFILE_SCHEMA_VERSION)
        self.assertEqual(
            snapshot.profile_compatibility_version,
            RUNTIME_PROFILE_COMPATIBILITY_VERSION,
        )
        self.assertEqual(
            snapshot.runtime_policy_registry_version,
            RUNTIME_POLICY_REGISTRY_VERSION,
        )
        self.assertEqual(snapshot.policy_schema_version, RUNTIME_POLICY_SCHEMA_VERSION)
        self.assertEqual(
            snapshot.policy_compatibility_version,
            RUNTIME_POLICY_COMPATIBILITY_VERSION,
        )
        self.assertIs(
            snapshot.validation_report.status,
            RuntimeMetadataValidationStatus.VALID,
        )
        self.assertTrue(snapshot.validation_report.valid)
        with self.assertRaises(FrozenInstanceError):
            snapshot.versions.runtime_version = "9.9"  # type: ignore[misc]
        exported = snapshot.export()
        with self.assertRaises(TypeError):
            exported["snapshot_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            exported["versions"]["runtime_version"] = "9.9"  # type: ignore[index]

    def test_snapshot_equality_hashing_and_timestamp_comparison_are_deterministic(self) -> None:
        first = self.catalog.snapshot(captured_at=self.captured_at)
        repeated = self.catalog.snapshot(captured_at=self.captured_at)
        later = self.catalog.snapshot(
            captured_at=self.captured_at + timedelta(seconds=1)
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first.snapshot_id, repeated.snapshot_id)
        self.assertEqual(first.content_hash, repeated.content_hash)
        self.assertNotEqual(first.snapshot_id, later.snapshot_id)
        self.assertEqual(first.content_hash, later.content_hash)
        comparison = first.compare(later)
        self.assertFalse(comparison.same_snapshot)
        self.assertTrue(comparison.same_content)
        self.assertTrue(comparison.same_versions)
        self.assertTrue(comparison.timestamp_changed)
        self.assertEqual(comparison.changed_components, ())

    def test_version_validation_reports_semantic_and_syntax_errors(self) -> None:
        incompatible_versions = replace(
            self.catalog.versions,
            runtime_version="2.0",
        )
        report = RuntimeMetadataCatalog(incompatible_versions).validate()

        self.assertIs(report.status, RuntimeMetadataValidationStatus.INVALID)
        self.assertEqual(report.issues, tuple(sorted(report.issues)))
        self.assertIn(
            "runtime and architecture major versions must match",
            report.issues,
        )
        with self.assertRaises(ValueError):
            replace(self.catalog.versions, repository_version="invalid version")

    def test_compatibility_verification_uses_declared_version_range(self) -> None:
        for version in ("1.4", "1.5"):
            with self.subTest(version=version):
                report = self.catalog.verify_compatibility(version)
                self.assertIs(
                    report.status,
                    RuntimeMetadataCompatibilityStatus.COMPATIBLE,
                )
                self.assertTrue(report.compatible)

        for version in ("1.3", "1.6", "2.0"):
            with self.subTest(version=version):
                report = self.catalog.verify_compatibility(version)
                self.assertIs(
                    report.status,
                    RuntimeMetadataCompatibilityStatus.INCOMPATIBLE,
                )
                self.assertFalse(report.compatible)

        unknown = self.catalog.verify_compatibility("development")
        self.assertIs(
            unknown.status,
            RuntimeMetadataCompatibilityStatus.UNKNOWN,
        )

    def test_entries_and_exports_use_deterministic_ordering(self) -> None:
        first = self.catalog.snapshot(captured_at=self.captured_at)
        second = build_runtime_metadata_catalog().snapshot(
            captured_at=self.captured_at
        )
        components = tuple(item.component for item in first.entries)
        version_keys = tuple(first.versions.as_mapping())

        self.assertEqual(components, tuple(sorted(components)))
        self.assertEqual(version_keys, tuple(sorted(version_keys)))
        self.assertEqual(first.serialize(), second.serialize())
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_serialization_round_trip_preserves_snapshot_identity(self) -> None:
        snapshot = self.catalog.snapshot(captured_at=self.captured_at)
        serialized = snapshot.serialize()
        restored = RuntimeMetadataSnapshot.deserialize(serialized)

        self.assertEqual(restored, snapshot)
        self.assertEqual(restored.serialize(), serialized)
        self.assertEqual(RuntimeMetadataSnapshot.from_json(serialized), snapshot)

    def test_mutable_serialization_copy_cannot_change_snapshot(self) -> None:
        snapshot = self.catalog.snapshot(captured_at=self.captured_at)
        detached = snapshot.to_dict()
        detached_versions = detached["versions"]
        detached_entries = detached["entries"]
        self.assertIsInstance(detached_versions, dict)
        self.assertIsInstance(detached_entries, list)

        detached_versions["runtime_version"] = "9.9"  # type: ignore[index]
        detached_entries[0]["version"] = "9.9"  # type: ignore[index]

        self.assertEqual(snapshot.runtime_version, NARVIS_ARCHITECTURE_VERSION)
        self.assertNotEqual(snapshot.to_dict(), detached)

    def test_snapshot_comparison_reports_changed_components(self) -> None:
        left = self.catalog.snapshot(captured_at=self.captured_at)
        updated_versions = replace(
            self.catalog.versions,
            observability_version="1.5.40",
        )
        right = RuntimeMetadataCatalog(updated_versions).snapshot(
            captured_at=self.captured_at
        )

        comparison = self.catalog.compare(left, right)
        self.assertFalse(comparison.same_content)
        self.assertFalse(comparison.same_versions)
        self.assertEqual(comparison.changed_components, ("observability",))
        self.assertFalse(comparison.compatibility_changed)
        self.assertFalse(comparison.validation_changed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
