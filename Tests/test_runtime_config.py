"""Focused tests for Version 1.5 Sprint 6 Runtime Configuration Registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.runtime_config import (
    RUNTIME_CONFIGURATION_SCHEMA_VERSION,
    RUNTIME_CONFIGURATION_VERSION,
    RuntimeConfigurationCompatibilityStatus,
    RuntimeConfigurationEntry,
    RuntimeConfigurationRegistry,
    RuntimeConfigurationSnapshot,
    RuntimeConfigurationValidationStatus,
    RuntimeConfigurationVersions,
    build_runtime_configuration_registry,
)


class RuntimeConfigurationRegistryTests(unittest.TestCase):
    """Verify immutable, deterministic configuration metadata behavior."""

    def setUp(self) -> None:
        self.captured_at = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
        self.registry = build_runtime_configuration_registry()

    def test_default_configuration_and_exports_are_immutable(self) -> None:
        snapshot = self.registry.snapshot(captured_at=self.captured_at)

        self.assertEqual(
            snapshot.configuration_version,
            RUNTIME_CONFIGURATION_VERSION,
        )
        self.assertEqual(snapshot.schema_version, RUNTIME_CONFIGURATION_SCHEMA_VERSION)
        self.assertEqual(snapshot.values()["runtime.environment"], "development")
        self.assertEqual(snapshot.defaults()["runtime.debug"], True)
        self.assertEqual(
            snapshot.values()["runtime.profile_registry_version"],
            "1.5.7",
        )
        self.assertEqual(
            snapshot.values()["runtime.policy_registry_version"],
            "1.5.8",
        )
        self.assertTrue(snapshot.read_only)
        self.assertFalse(snapshot.active_application)
        with self.assertRaises(FrozenInstanceError):
            snapshot.versions.schema_version = "9.0"  # type: ignore[misc]
        exported = snapshot.export()
        with self.assertRaises(TypeError):
            exported["content_hash"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            exported["entries"][0]["value"] = "changed"  # type: ignore[index]

    def test_configuration_hashing_and_snapshot_equality_are_deterministic(self) -> None:
        first = self.registry.snapshot(captured_at=self.captured_at)
        repeated = self.registry.snapshot(captured_at=self.captured_at)
        later = self.registry.snapshot(
            captured_at=self.captured_at + timedelta(seconds=1)
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first.configuration_id, repeated.configuration_id)
        self.assertEqual(first.content_hash, repeated.content_hash)
        self.assertNotEqual(first, later)
        self.assertEqual(first.configuration_id, later.configuration_id)
        comparison = first.compare(later)
        self.assertFalse(comparison.same_snapshot)
        self.assertTrue(comparison.same_content)
        self.assertTrue(comparison.timestamp_changed)

    def test_serialization_round_trip_preserves_configuration(self) -> None:
        snapshot = self.registry.snapshot(captured_at=self.captured_at)
        serialized = snapshot.serialize()
        restored = RuntimeConfigurationSnapshot.deserialize(serialized)

        self.assertEqual(restored, snapshot)
        self.assertEqual(restored.serialize(), serialized)
        self.assertEqual(RuntimeConfigurationSnapshot.from_json(serialized), snapshot)

    def test_compatibility_validation_uses_schema_range(self) -> None:
        compatible = self.registry.verify_compatibility("1.0")
        self.assertIs(
            compatible.status,
            RuntimeConfigurationCompatibilityStatus.COMPATIBLE,
        )
        self.assertTrue(compatible.compatible)

        for version in ("0.9", "1.1", "2.0"):
            with self.subTest(version=version):
                report = self.registry.verify_compatibility(version)
                self.assertIs(
                    report.status,
                    RuntimeConfigurationCompatibilityStatus.INCOMPATIBLE,
                )
        unknown = self.registry.verify_compatibility("development")
        self.assertIs(
            unknown.status,
            RuntimeConfigurationCompatibilityStatus.UNKNOWN,
        )

    def test_version_validation_reports_semantic_and_syntax_errors(self) -> None:
        invalid_versions = RuntimeConfigurationVersions(
            configuration_version="1.5.6",
            schema_version="1.0",
            compatibility_version="1.1",
        )
        report = RuntimeConfigurationRegistry(
            entries=self.registry.entries,
            versions=invalid_versions,
        ).validate()

        self.assertIs(report.status, RuntimeConfigurationValidationStatus.INVALID)
        self.assertIn(
            "compatibility version cannot exceed schema version",
            report.issues,
        )
        with self.assertRaises(ValueError):
            replace(invalid_versions, configuration_version="invalid version")

    def test_serialized_copy_and_input_values_are_deeply_isolated(self) -> None:
        mutable_value = {"channels": ["dashboard", "api"]}
        entry = RuntimeConfigurationEntry(
            key="metadata.channels",
            value=mutable_value,
            default_value={"channels": ["dashboard"]},
            category="metadata",
            description="Configured metadata publication channels.",
        )
        registry = RuntimeConfigurationRegistry(entries=(entry,))
        snapshot = registry.snapshot(captured_at=self.captured_at)
        mutable_value["channels"].append("voice")
        detached = snapshot.to_dict()
        detached["entries"][0]["value"]["channels"].append("plugins")  # type: ignore[index]

        self.assertEqual(
            snapshot.get("metadata.channels").value["channels"],  # type: ignore[union-attr]
            ("dashboard", "api"),
        )
        self.assertNotEqual(snapshot.to_dict(), detached)

    def test_registry_and_mapping_exports_use_deterministic_ordering(self) -> None:
        entries = tuple(reversed(self.registry.entries))
        reordered = RuntimeConfigurationRegistry(entries=entries)
        snapshot = reordered.snapshot(captured_at=self.captured_at)
        keys = tuple(item.key for item in snapshot.entries)

        self.assertEqual(keys, tuple(sorted(keys)))
        self.assertEqual(tuple(snapshot.values()), tuple(sorted(snapshot.values())))
        self.assertEqual(
            snapshot.serialize(),
            self.registry.snapshot(captured_at=self.captured_at).serialize(),
        )

    def test_immutable_updates_and_comparison_report_changed_keys(self) -> None:
        original = self.registry.snapshot(captured_at=self.captured_at)
        updated_registry = self.registry.with_values(
            {"runtime.environment": "production"}
        ).register(
            RuntimeConfigurationEntry(
                key="runtime.region",
                value="local",
                default_value="local",
                category="runtime",
                description="Configured runtime region metadata.",
            )
        )
        updated = updated_registry.snapshot(captured_at=self.captured_at)
        comparison = self.registry.compare(original, updated)

        self.assertEqual(comparison.changed_keys, ("runtime.environment",))
        self.assertEqual(comparison.added_keys, ("runtime.region",))
        self.assertEqual(comparison.removed_keys, ())
        self.assertEqual(
            self.registry.get("runtime.environment").value,  # type: ignore[union-attr]
            "development",
        )
        with self.assertRaises(ValueError):
            self.registry.register(self.registry.entries[0])
        with self.assertRaises(KeyError):
            self.registry.with_values({"runtime.unknown": True})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
