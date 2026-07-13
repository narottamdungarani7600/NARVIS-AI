"""Focused tests for the Phase 7 mutation surface registry."""

from __future__ import annotations

import unittest
from pathlib import Path

from Evolution.mutation_surfaces import MutationSurfaceRegistry, MutationSurfaceRequest


class MutationSurfaceRegistryTests(unittest.TestCase):
    """Verify the deny-by-default mutation surface registry."""

    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[1]
        self.registry = MutationSurfaceRegistry(workspace_root=self.workspace_root)

    def test_default_registry_contains_expected_surfaces(self) -> None:
        surface_ids = [surface.surface_id for surface in self.registry.list_surfaces()]
        self.assertEqual(
            surface_ids,
            [
                "approved_source_file",
                "package",
                "plugin",
                "sandbox",
            ],
        )

    def test_unknown_surface_is_denied_by_default(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="mystery-surface",
                locator="whatever",
                target_kind="unknown",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.decision, "denied")
        self.assertEqual(decision.reason_code, "surface_unregistered")

    def test_protected_exact_file_is_denied_for_source_surface(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="approved_source_file",
                locator="narvis.py",
                target_kind="source_file",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "protected_surface")
        self.assertEqual(decision.matched_rule_id, "protected.narvis")

    def test_protected_prefix_path_is_denied_for_source_surface(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="approved_source_file",
                locator=str(self.workspace_root / "Docs" / "AI_DEVELOPMENT_RULES.md"),
                target_kind="source_file",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "protected_surface")
        self.assertEqual(decision.matched_rule_id, "protected.docs")

    def test_existing_non_protected_source_file_is_allowed(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="approved_source_file",
                locator="Skills/builtin.py",
                target_kind="source_file",
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.normalized_locator, "Skills/builtin.py")

    def test_unknown_source_file_target_is_denied(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="approved_source_file",
                locator="Skills/not_a_real_file.py",
                target_kind="source_file",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unknown_target")

    def test_source_file_outside_workspace_is_denied(self) -> None:
        outside_file = self.workspace_root.parent / "outside.py"
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="approved_source_file",
                locator=str(outside_file),
                target_kind="source_file",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unknown_target")

    def test_registered_sandbox_identifier_is_allowed(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="sandbox",
                locator="sandbox_runtime",
                target_kind="sandbox_runtime",
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "surface_allowed")

    def test_unknown_sandbox_identifier_is_denied(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="sandbox",
                locator="mystery_box",
                target_kind="sandbox_runtime",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unknown_target")

    def test_typed_package_specifier_is_allowed(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="package",
                locator="requests>=2.32,<3",
                target_kind="dependency_spec",
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "surface_allowed")

    def test_invalid_package_target_is_denied(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="package",
                locator="Docs/requirements.txt",
                target_kind="dependency_spec",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unknown_target")

    def test_typed_plugin_identifier_is_allowed(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="plugin",
                locator="cloud.integration",
                target_kind="plugin_identifier",
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "surface_allowed")

    def test_target_kind_mismatch_is_denied(self) -> None:
        decision = self.registry.evaluate(
            MutationSurfaceRequest(
                surface_id="plugin",
                locator="cloud.integration",
                target_kind="source_file",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "target_kind_not_allowed")


if __name__ == "__main__":
    unittest.main()
