"""Focused tests for the Phase 7 mutation guard service."""

from __future__ import annotations

import unittest
from pathlib import Path

from Evolution.mutation_policy import MutationGuardRequest, MutationGuardService


class MutationGuardServiceTests(unittest.TestCase):
    """Verify pure deny-by-default mutation guard validation."""

    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[1]
        self.guard = MutationGuardService(workspace_root=self.workspace_root)

    def test_allows_existing_non_protected_source_file_with_valid_risk(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="approved_source_file",
                locator="Skills/builtin.py",
                target_kind="source_file",
                risk_classification="medium",
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "guard_allowed")
        self.assertEqual(decision.normalized_locator, "Skills/builtin.py")

    def test_high_risk_classification_is_valid_when_surface_is_allowed(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="approved_source_file",
                locator="Skills/builtin.py",
                target_kind="source_file",
                risk_classification="high",
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.risk_classification, "high")

    def test_rejects_invalid_risk_classification(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="approved_source_file",
                locator="Skills/builtin.py",
                target_kind="source_file",
                risk_classification="critical",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "invalid_risk_classification")

    def test_rejects_unknown_surface(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="mystery_surface",
                locator="anything",
                target_kind="source_file",
                risk_classification="low",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "surface_unregistered")

    def test_rejects_protected_target(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="approved_source_file",
                locator="Docs/AI_DEVELOPMENT_RULES.md",
                target_kind="source_file",
                risk_classification="low",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "protected_surface")
        self.assertEqual(decision.matched_rule_id, "protected.docs")

    def test_rejects_absolute_path_outside_workspace(self) -> None:
        outside_file = self.workspace_root.parent / "outside.py"
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="approved_source_file",
                locator=str(outside_file),
                target_kind="source_file",
                risk_classification="low",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "path_outside_workspace")

    def test_rejects_relative_escape_path_outside_workspace(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="approved_source_file",
                locator="../outside.py",
                target_kind="source_file",
                risk_classification="low",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "path_outside_workspace")

    def test_rejects_invalid_target_kind(self) -> None:
        decision = self.guard.validate(
            MutationGuardRequest(
                surface_id="package",
                locator="requests>=2.32,<3",
                target_kind="source_file",
                risk_classification="medium",
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "target_kind_not_allowed")


if __name__ == "__main__":
    unittest.main()
