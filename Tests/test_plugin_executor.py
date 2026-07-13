"""Focused tests for the Phase 8 placeholder local-plugin executor."""

from __future__ import annotations

import unittest

from Evolution.models import MutationTarget
from Evolution.plugin_executor import PluginExecutionRequest, PluginExecutorService


class PluginExecutorServiceTests(unittest.TestCase):
    """Verify approved local-plugin simulations remain typed and fail closed."""

    def setUp(self) -> None:
        self.executor = PluginExecutorService()

    def _target(
        self,
        *,
        mutation_target_id: str = "plugin-target-001",
        locator: str = "cloud.integration",
        action_kind: str = "plugin_install",
        executor_category: str = "plugin_management",
        target_kind: str = "plugin_identifier",
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

    def test_install_simulates_approved_local_plugin_with_rollback_metadata(self) -> None:
        result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(),
                operation="install",
                metadata={"mutation_run_id": "mutation-run-001", "mutation_step_run_id": "mutation-step-run-001"},
            )
        )

        self.assertTrue(result.successful)
        self.assertEqual(result.decision, "simulated")
        self.assertEqual(result.reason_code, "plugin_operation_simulated")
        self.assertEqual(result.plugin_identifier, "cloud.integration")
        self.assertEqual(result.source_kind, "local")
        self.assertTrue(result.metadata["placeholder_only"])
        self.assertFalse(result.metadata["real_mutation_performed"])
        self.assertFalse(result.metadata["plugin_registry_mutated"])
        self.assertFalse(result.metadata["network_invoked"])
        self.assertFalse(result.metadata["shell_invoked"])
        self.assertFalse(result.metadata["package_manager_invoked"])
        self.assertFalse(result.metadata["git_invoked"])
        self.assertIsNotNone(result.rollback_artifact)
        self.assertEqual(result.rollback_artifact.artifact_kind, "local_plugin_rollback_plan")
        self.assertEqual(result.rollback_artifact.status, "planned")
        self.assertEqual(result.rollback_artifact.mutation_run_id, "mutation-run-001")
        self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], "uninstall")
        self.assertTrue(result.rollback_artifact.metadata["pre_execution_state_required"])
        self.assertFalse(result.rollback_artifact.metadata["pre_execution_state_captured"])
        self.assertFalse(result.rollback_artifact.metadata["rollback_ready"])

    def test_uninstall_enable_and_disable_simulate_only(self) -> None:
        requests = (
            ("uninstall", "plugin_remove", "install"),
            ("enable", "plugin_enable", "disable"),
            ("disable", "plugin_disable", "enable"),
        )

        for operation, action_kind, rollback_operation in requests:
            with self.subTest(operation=operation):
                result = self.executor.execute(
                    PluginExecutionRequest(
                        mutation_target=self._target(action_kind=action_kind),
                        operation=operation,  # type: ignore[arg-type]
                    )
                )

                self.assertTrue(result.successful)
                self.assertEqual(result.operation, operation)
                self.assertEqual(result.rollback_artifact.metadata["rollback_operation"], rollback_operation)

    def test_rejects_unknown_plugin_identifier(self) -> None:
        result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(locator="unknown.integration"),
                operation="install",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "unknown_plugin_identifier")

    def test_rejects_external_repository_or_url_locator(self) -> None:
        result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(locator="https://github.com/example/plugin"),
                operation="install",
            )
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "external_repository_not_allowed")

    def test_rejects_remote_source_or_network_metadata(self) -> None:
        remote_source_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(),
                operation="install",
                source_kind="remote",  # type: ignore[arg-type]
            )
        )
        metadata_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(),
                operation="install",
                metadata={"repository_url": "https://example.invalid/plugin"},
            )
        )

        self.assertEqual(remote_source_result.reason_code, "network_operation_not_allowed")
        self.assertEqual(metadata_result.reason_code, "network_operation_not_allowed")

    def test_rejects_unknown_target_type_or_action_kind(self) -> None:
        target_kind_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(target_kind="plugin_package"),
                operation="install",
            )
        )
        action_kind_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(action_kind="plugin_remove"),
                operation="install",
            )
        )

        self.assertEqual(target_kind_result.reason_code, "invalid_target_kind")
        self.assertEqual(action_kind_result.reason_code, "action_kind_mismatch")

    def test_rejects_invalid_operation_category_or_risk(self) -> None:
        operation_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(),
                operation="reload",  # type: ignore[arg-type]
            )
        )
        category_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(executor_category="package_management"),
                operation="install",
            )
        )
        risk_result = self.executor.execute(
            PluginExecutionRequest(
                mutation_target=self._target(risk_classification="high"),
                operation="install",
            )
        )

        self.assertEqual(operation_result.reason_code, "invalid_operation")
        self.assertEqual(category_result.reason_code, "invalid_executor_category")
        self.assertEqual(risk_result.reason_code, "plugin_risk_classification_required")


if __name__ == "__main__":
    unittest.main()
