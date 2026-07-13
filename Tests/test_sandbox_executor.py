"""Focused tests for the Phase 8 sandbox executor."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from Evolution.models import MutationTarget
from Evolution.sandbox_executor import SandboxExecutionRequest, SandboxExecutorService


def _workspace_temp_dir() -> Path:
    """Create a temporary directory inside the writable workspace."""

    root = Path.cwd() / "data" / "sandbox_executor_test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SandboxExecutorServiceTests(unittest.TestCase):
    """Verify narrow sandbox-local execution stays fail closed."""

    def setUp(self) -> None:
        self.temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.executor = SandboxExecutorService(sandbox_root=self.temp_dir)

    def _target(
        self,
        *,
        mutation_target_id: str = "mutation-target-001",
        target_kind: str = "sandbox_workspace",
        locator: str = "artifacts/result.txt",
        executor_category: str = "sandbox_execution",
    ) -> MutationTarget:
        return MutationTarget(
            mutation_target_id=mutation_target_id,
            plan_step_id="plan-step-001",
            execution_step_request_id="step-request-001",
            executor_category=executor_category,
            action_kind="code_execute",
            target_kind=target_kind,
            locator=locator,
            risk_classification="medium",
        )

    def test_apply_write_text_creates_text_artifact_and_returns_rollback_artifact(self) -> None:
        target = self._target(locator="artifacts/output.txt")

        result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="apply",
                text_content="sandbox output",
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.reason_code, "sandbox_text_written")
        self.assertEqual((self.temp_dir / "artifacts" / "output.txt").read_text(encoding="utf-8"), "sandbox output")
        self.assertIsNotNone(result.rollback_artifact)
        self.assertEqual(result.rollback_artifact.artifact_kind, "sandbox_text_snapshot")
        self.assertFalse(result.rollback_artifact.metadata["existed_before"])

    def test_rollback_write_text_restores_previous_content(self) -> None:
        target_path = self.temp_dir / "artifacts" / "output.txt"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("before", encoding="utf-8")
        target = self._target(locator="artifacts/output.txt")

        apply_result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="apply",
                text_content="after",
            )
        )
        rollback_result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="rollback",
                rollback_artifact=apply_result.rollback_artifact,
            )
        )

        self.assertTrue(apply_result.successful)
        self.assertTrue(rollback_result.successful)
        self.assertEqual(rollback_result.reason_code, "sandbox_text_rolled_back")
        self.assertEqual(target_path.read_text(encoding="utf-8"), "before")

    def test_apply_create_directory_creates_directory(self) -> None:
        target = self._target(
            mutation_target_id="mutation-target-dir-001",
            target_kind="sandbox_runtime",
            locator="runtime/session_001",
        )

        result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="create_directory",
                mode="apply",
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.reason_code, "sandbox_directory_ready")
        self.assertTrue((self.temp_dir / "runtime" / "session_001").is_dir())
        self.assertIsNotNone(result.rollback_artifact)

    def test_rollback_create_directory_removes_newly_created_empty_directory(self) -> None:
        target = self._target(
            mutation_target_id="mutation-target-dir-002",
            target_kind="sandbox_runtime",
            locator="runtime/session_rollback",
        )

        apply_result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="create_directory",
                mode="apply",
            )
        )
        rollback_result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="create_directory",
                mode="rollback",
                rollback_artifact=apply_result.rollback_artifact,
            )
        )

        self.assertTrue(apply_result.successful)
        self.assertTrue(rollback_result.successful)
        self.assertFalse((self.temp_dir / "runtime" / "session_rollback").exists())

    def test_rejects_path_escape_outside_sandbox(self) -> None:
        target = self._target(locator="../escape.txt")

        result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="apply",
                text_content="blocked",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "path_outside_sandbox")
        self.assertFalse((self.temp_dir.parent / "escape.txt").exists())

    def test_rejects_source_like_file_write(self) -> None:
        target = self._target(locator="scripts/runner.py")

        result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="apply",
                text_content="print('blocked')",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "file_type_not_allowed")
        self.assertFalse((self.temp_dir / "scripts" / "runner.py").exists())

    def test_rejects_git_like_path_inside_sandbox(self) -> None:
        target = self._target(locator=".git/config.txt")

        result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="apply",
                text_content="blocked",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "protected_sandbox_path")

    def test_rejects_rollback_without_exact_artifact(self) -> None:
        target = self._target(locator="artifacts/output.txt")

        result = self.executor.execute(
            SandboxExecutionRequest(
                mutation_target=target,
                operation="write_text",
                mode="rollback",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "rollback_artifact_required")


if __name__ == "__main__":
    unittest.main()
