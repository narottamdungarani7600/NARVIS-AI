"""Focused tests for the Phase 8 placeholder source-file executor."""

from __future__ import annotations

import hashlib
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from Evolution.models import MutationTarget
from Evolution.source_executor import SourceExecutionRequest, SourceExecutorService


def _workspace_temp_dir() -> Path:
    """Create one temporary source workspace inside the writable repository workspace."""

    root = Path.cwd() / "data" / "source_executor_test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SourceExecutorServiceTests(unittest.TestCase):
    """Verify approved source-file simulations stay inside the workspace and fail closed."""

    def setUp(self) -> None:
        self.workspace_root = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.workspace_root, ignore_errors=True))
        self.allowed_file = self.workspace_root / "Features" / "safe_module.py"
        self.allowed_file.parent.mkdir(parents=True, exist_ok=True)
        self.allowed_file.write_text("VALUE = 'before'\n", encoding="utf-8")
        self.protected_file = self.workspace_root / "Core" / "protected_module.py"
        self.protected_file.parent.mkdir(parents=True, exist_ok=True)
        self.protected_file.write_text("VALUE = 'protected'\n", encoding="utf-8")
        self.executor = SourceExecutorService(workspace_root=self.workspace_root)

    def _target(
        self,
        *,
        mutation_target_id: str = "source-target-001",
        locator: str = "Features/safe_module.py",
        action_kind: str = "source_modify",
        executor_category: str = "code_development",
        target_kind: str = "source_file",
        risk_classification: str = "high",
    ) -> MutationTarget:
        return MutationTarget(
            mutation_target_id=mutation_target_id,
            plan_step_id="plan-step-001",
            execution_step_request_id="step-request-001",
            executor_category=executor_category,
            action_kind=action_kind,
            target_kind=target_kind,
            locator=locator,
            risk_classification=risk_classification,
        )

    def test_modify_simulates_approved_source_without_changing_file(self) -> None:
        before = self.allowed_file.read_text(encoding="utf-8")
        result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(),
                operation="modify",
                metadata={"mutation_run_id": "mutation-run-001", "mutation_step_run_id": "mutation-step-run-001"},
            )
        )

        expected_hash = hashlib.sha256(self.allowed_file.read_bytes()).hexdigest()
        self.assertTrue(result.successful)
        self.assertEqual(result.decision, "simulated")
        self.assertEqual(result.reason_code, "source_operation_simulated")
        self.assertEqual(result.relative_path, "Features/safe_module.py")
        self.assertEqual(result.source_content_sha256, expected_hash)
        self.assertEqual(self.allowed_file.read_text(encoding="utf-8"), before)
        self.assertTrue(result.metadata["placeholder_only"])
        self.assertFalse(result.metadata["real_mutation_performed"])
        self.assertFalse(result.metadata["source_file_written"])
        self.assertFalse(result.metadata["shell_invoked"])
        self.assertFalse(result.metadata["package_manager_invoked"])
        self.assertFalse(result.metadata["git_invoked"])
        self.assertIsNotNone(result.rollback_artifact)
        self.assertEqual(result.rollback_artifact.artifact_kind, "source_file_rollback_plan")
        self.assertEqual(result.rollback_artifact.status, "planned")
        self.assertEqual(result.rollback_artifact.mutation_run_id, "mutation-run-001")
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "restore_verified_snapshot")
        self.assertEqual(result.rollback_artifact.metadata["pre_execution_fingerprint"], expected_hash)
        self.assertFalse(result.rollback_artifact.metadata["pre_execution_content_captured"])
        self.assertFalse(result.rollback_artifact.metadata["rollback_ready"])

    def test_delete_simulates_existing_source_without_removing_file(self) -> None:
        result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(action_kind="source_delete"),
                operation="delete",
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.operation, "delete")
        self.assertTrue(self.allowed_file.is_file())
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "restore_verified_snapshot")

    def test_rejects_protected_source_file(self) -> None:
        result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(locator="Core/protected_module.py"),
                operation="modify",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "protected_surface")
        self.assertEqual(result.matched_rule_id, "protected.core")

    def test_rejects_path_outside_workspace(self) -> None:
        outside_path = self.workspace_root.parent / "outside_module.py"
        result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(locator=str(outside_path)),
                operation="modify",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "path_outside_workspace")

    def test_rejects_directory_traversal_even_when_it_resolves_inside_workspace(self) -> None:
        result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(locator="Features/../Features/safe_module.py"),
                operation="modify",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "directory_traversal")

    def test_rejects_unknown_target_kind_and_non_source_file(self) -> None:
        target_kind_result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(target_kind="package_spec"),
                operation="modify",
            )
        )
        text_file = self.workspace_root / "Features" / "notes.txt"
        text_file.write_text("not source\n", encoding="utf-8")
        extension_result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(locator="Features/notes.txt"),
                operation="modify",
            )
        )

        self.assertEqual(target_kind_result.reason_code, "invalid_target_kind")
        self.assertEqual(extension_result.reason_code, "source_file_type_not_allowed")

    def test_rejects_unknown_or_missing_source_file(self) -> None:
        result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(locator="Features/missing_module.py"),
                operation="modify",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "unknown_target")

    def test_rejects_action_kind_or_risk_mismatch(self) -> None:
        action_kind_result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(action_kind="source_delete"),
                operation="modify",
            )
        )
        risk_result = self.executor.execute(
            SourceExecutionRequest(
                mutation_target=self._target(risk_classification="medium"),
                operation="modify",
            )
        )

        self.assertEqual(action_kind_result.reason_code, "action_kind_mismatch")
        self.assertEqual(risk_result.reason_code, "source_risk_classification_required")


if __name__ == "__main__":
    unittest.main()
