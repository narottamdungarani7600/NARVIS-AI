"""Focused tests for the Phase 8 placeholder local-Git executor."""

from __future__ import annotations

import unittest
from pathlib import Path

from Evolution.git_executor import GitExecutionRequest, GitExecutorService
from Evolution.models import MutationTarget


class GitExecutorServiceTests(unittest.TestCase):
    """Verify local Git simulations remain typed, rooted, and fail closed."""

    def setUp(self) -> None:
        self.repository_root = Path.cwd().resolve()
        self.executor = GitExecutorService(repository_root=self.repository_root)

    def _target(
        self,
        *,
        mutation_target_id: str = "git-target-001",
        locator: str = "local_repository",
        action_kind: str = "git_operation",
        executor_category: str = "git_operation",
        target_kind: str = "local_repository",
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

    def test_stage_simulates_approved_local_repository_with_rollback_metadata(self) -> None:
        result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(),
                operation="stage",
                metadata={"mutation_run_id": "mutation-run-001", "mutation_step_run_id": "mutation-step-run-001"},
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.decision, "simulated")
        self.assertEqual(result.reason_code, "git_operation_simulated")
        self.assertEqual(result.repository_identifier, "local_repository")
        self.assertEqual(result.repository_root, str(self.repository_root))
        self.assertEqual(result.transport, "local")
        self.assertTrue(result.metadata["placeholder_only"])
        self.assertFalse(result.metadata["real_mutation_performed"])
        self.assertFalse(result.metadata["git_executed"])
        self.assertFalse(result.metadata["index_mutated"])
        self.assertFalse(result.metadata["commit_created"])
        self.assertFalse(result.metadata["network_invoked"])
        self.assertFalse(result.metadata["shell_invoked"])
        self.assertFalse(result.metadata["package_manager_invoked"])
        self.assertIsNotNone(result.rollback_artifact)
        self.assertEqual(result.rollback_artifact.artifact_kind, "local_git_rollback_plan")
        self.assertEqual(result.rollback_artifact.status, "planned")
        self.assertEqual(result.rollback_artifact.mutation_run_id, "mutation-run-001")
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "unstage")
        self.assertTrue(result.rollback_artifact.metadata["pre_execution_state_required"])
        self.assertFalse(result.rollback_artifact.metadata["pre_execution_state_captured"])
        self.assertFalse(result.rollback_artifact.metadata["rollback_ready"])

    def test_unstage_commit_and_rollback_commit_simulate_only(self) -> None:
        requests = (
            ("unstage", "stage"),
            ("commit", "rollback_commit"),
            ("rollback_commit", "commit"),
        )

        for operation, rollback_operation in requests:
            with self.subTest(operation=operation):
                result = self.executor.execute(
                    GitExecutionRequest(
                        mutation_target=self._target(),
                        operation=operation,  # type: ignore[arg-type]
                    )
                )

                self.assertTrue(result.successful)
                self.assertEqual(result.operation, operation)
                self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], rollback_operation)

    def test_rejects_remote_repository_locator(self) -> None:
        result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(locator="https://github.com/example/narvis.git"),
                operation="stage",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "remote_repository_not_allowed")

    def test_rejects_remote_transport_or_network_metadata(self) -> None:
        remote_transport_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(),
                operation="stage",
                transport="remote",  # type: ignore[arg-type]
            )
        )
        metadata_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(),
                operation="stage",
                metadata={"remote_url": "https://example.invalid/narvis.git"},
            )
        )

        self.assertEqual(remote_transport_result.reason_code, "network_operation_not_allowed")
        self.assertEqual(metadata_result.reason_code, "network_operation_not_allowed")

    def test_rejects_prohibited_remote_or_history_rewriting_operations(self) -> None:
        for operation in ("push", "pull", "fetch", "clone", "merge", "rebase", "force", "force_push"):
            with self.subTest(operation=operation):
                result = self.executor.execute(
                    GitExecutionRequest(
                        mutation_target=self._target(),
                        operation=operation,  # type: ignore[arg-type]
                    )
                )

                self.assertEqual(result.decision, "rejected")
                self.assertEqual(result.reason_code, "git_operation_not_allowed")

    def test_rejects_force_flags_and_git_metadata_paths(self) -> None:
        force_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(),
                operation="commit",
                force=True,
            )
        )
        metadata_path_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(locator=".git/config"),
                operation="stage",
            )
        )

        self.assertEqual(force_result.reason_code, "force_operation_not_allowed")
        self.assertEqual(metadata_path_result.reason_code, "git_metadata_target_not_allowed")

    def test_rejects_traversal_or_unknown_target_type(self) -> None:
        traversal_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(locator="../NARVIS"),
                operation="stage",
            )
        )
        target_kind_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(target_kind="source_file"),
                operation="stage",
            )
        )

        self.assertEqual(traversal_result.reason_code, "directory_traversal")
        self.assertEqual(target_kind_result.reason_code, "invalid_target_kind")

    def test_rejects_action_kind_category_or_risk_mismatch(self) -> None:
        action_kind_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(action_kind="source_modify"),
                operation="stage",
            )
        )
        category_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(executor_category="plugin_management"),
                operation="stage",
            )
        )
        risk_result = self.executor.execute(
            GitExecutionRequest(
                mutation_target=self._target(risk_classification="medium"),
                operation="stage",
            )
        )

        self.assertEqual(action_kind_result.reason_code, "action_kind_mismatch")
        self.assertEqual(category_result.reason_code, "invalid_executor_category")
        self.assertEqual(risk_result.reason_code, "git_risk_classification_required")


if __name__ == "__main__":
    unittest.main()
