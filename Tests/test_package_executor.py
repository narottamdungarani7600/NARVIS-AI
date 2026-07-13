"""Focused tests for the Phase 8 placeholder package executor."""

from __future__ import annotations

import unittest

from Evolution.models import MutationTarget
from Evolution.package_executor import PackageExecutionRequest, PackageExecutorService


class PackageExecutorServiceTests(unittest.TestCase):
    """Verify typed package operations remain validated and placeholder-only."""

    def setUp(self) -> None:
        self.executor = PackageExecutorService()

    def _target(
        self,
        *,
        mutation_target_id: str = "package-target-001",
        locator: str = "requests>=2.32,<3",
        action_kind: str = "package_install",
        executor_category: str = "package_management",
        target_kind: str = "dependency_spec",
        risk_classification: str = "medium",
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

    def test_install_simulates_valid_package_specification_with_rollback_metadata(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(locator="Requests[security]>=2.32,<3"),
                operation="install",
                metadata={"mutation_run_id": "mutation-run-001", "mutation_step_run_id": "mutation-step-run-001"},
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.decision, "simulated")
        self.assertEqual(result.reason_code, "package_operation_simulated")
        self.assertEqual(result.package_name, "requests")
        self.assertEqual(result.package_specification, "requests[security]>=2.32,<3")
        self.assertTrue(result.metadata["placeholder_only"])
        self.assertFalse(result.metadata["real_mutation_performed"])
        self.assertFalse(result.metadata["package_manager_invoked"])
        self.assertIsNotNone(result.rollback_artifact)
        self.assertEqual(result.rollback_artifact.artifact_kind, "package_rollback_plan")
        self.assertEqual(result.rollback_artifact.status, "planned")
        self.assertEqual(result.rollback_artifact.mutation_run_id, "mutation-run-001")
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "uninstall")
        self.assertTrue(result.rollback_artifact.metadata["pre_execution_state_required"])
        self.assertFalse(result.rollback_artifact.metadata["pre_execution_state_captured"])
        self.assertFalse(result.rollback_artifact.metadata["rollback_ready"])

    def test_uninstall_simulates_one_bare_package_name(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(locator="requests", action_kind="package_remove"),
                operation="uninstall",
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.operation, "uninstall")
        self.assertEqual(result.package_name, "requests")
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "install")

    def test_upgrade_simulates_one_bare_package_name(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(locator="requests", action_kind="package_upgrade"),
                operation="upgrade",
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.operation, "upgrade")
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "install")

    def test_rejects_unknown_package_operation(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(),
                operation="download",  # type: ignore[arg-type]
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "invalid_operation")
        self.assertFalse(result.metadata["package_manager_invoked"])

    def test_rejects_direct_reference_or_command_like_package_specification(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(locator="requests @ https://example.invalid/requests.whl"),
                operation="install",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "invalid_package_specification")

    def test_rejects_uninstall_with_version_specification(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(locator="requests==2.32.0", action_kind="package_remove"),
                operation="uninstall",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "operation_requires_bare_package_name")

    def test_rejects_non_package_target_category(self) -> None:
        result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(executor_category="sandbox_execution"),
                operation="install",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "invalid_executor_category")

    def test_rejects_target_kind_or_action_kind_mismatch(self) -> None:
        target_kind_result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(target_kind="source_file"),
                operation="install",
            )
        )
        action_kind_result = self.executor.execute(
            PackageExecutionRequest(
                mutation_target=self._target(locator="requests", action_kind="package_remove"),
                operation="upgrade",
            )
        )

        self.assertEqual(target_kind_result.reason_code, "invalid_target_kind")
        self.assertEqual(action_kind_result.reason_code, "action_kind_mismatch")


if __name__ == "__main__":
    unittest.main()
