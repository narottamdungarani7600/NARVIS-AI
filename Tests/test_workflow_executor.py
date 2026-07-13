"""Focused tests for the standalone Phase 10 non-executing workflow executor."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.execution_validator import ExecutionValidationReason, ExecutionValidationResult
from Evolution.workflow_executor import (
    WorkflowExecutionRequest,
    WorkflowExecutionStatus,
    WorkflowExecutionStep,
    WorkflowExecutorService,
)


class WorkflowExecutorServiceTests(unittest.TestCase):
    """Verify validated workflow composition remains deterministic, ordered, and non-executing."""

    def setUp(self) -> None:
        self.executor = WorkflowExecutorService()

    def _validation(self, action_id: str = "desktop.open_application") -> ExecutionValidationResult:
        return ExecutionValidationResult(
            decision="ALLOW",
            reason=ExecutionValidationReason.ALLOWED,
            detail="A complete future request was validated without execution.",
            action_id=action_id,
            context_snapshot_id="execution-context-001",
            mutation_approval_id="mutation-approval-001",
            recovery_outcome_id="recovery-outcome-001",
            mutation_target_ids=("target-001",),
        )

    def _step(
        self,
        step_id: str,
        sequence: int,
        dependencies: tuple[str, ...] = (),
        validation_result: ExecutionValidationResult | None = None,
    ) -> WorkflowExecutionStep:
        return WorkflowExecutionStep(
            step_id=step_id,
            sequence=sequence,
            validation_result=validation_result or self._validation(),
            depends_on_step_ids=dependencies,
        )

    def test_composes_unsorted_valid_steps_into_a_deterministic_dependency_ordered_plan(self) -> None:
        request = WorkflowExecutionRequest(
            workflow_id="workflow-001",
            steps=(
                self._step("verify", 3, ("navigate",), self._validation("system.inspect_status")),
                self._step("launch", 1),
                self._step("navigate", 2, ("launch",), self._validation("browser.navigate")),
            ),
        )

        first = self.executor.compose(request)
        second = self.executor.compose(request)

        self.assertTrue(first.planned)
        self.assertEqual(first.status, WorkflowExecutionStatus.PLANNED)
        self.assertEqual(first.reason_code, "workflow_execution_plan_created")
        self.assertEqual([step.step_id for step in first.ordered_steps], ["launch", "navigate", "verify"])
        self.assertEqual([step.sequence for step in first.ordered_steps], [1, 2, 3])
        self.assertEqual(first.workflow_fingerprint, second.workflow_fingerprint)
        self.assertEqual(first.workflow_plan_id, second.workflow_plan_id)
        self.assertFalse(first.executor_invoked)
        self.assertFalse(first.desktop_executor_invoked)
        self.assertFalse(first.application_executor_invoked)
        self.assertFalse(first.browser_executor_invoked)

    def test_rejects_untyped_empty_or_malformed_workflows(self) -> None:
        untyped = self.executor.compose("not-a-workflow-request")  # type: ignore[arg-type]
        empty = self.executor.compose(WorkflowExecutionRequest("workflow-001", ()))
        malformed_id = self.executor.compose(WorkflowExecutionRequest("workflow with spaces", (self._step("launch", 1),)))

        self.assertEqual(untyped.status, WorkflowExecutionStatus.REJECTED)
        self.assertEqual(untyped.reason_code, "invalid_workflow_execution_request")
        self.assertEqual(empty.reason_code, "workflow_steps_required")
        self.assertEqual(malformed_id.reason_code, "invalid_workflow_identifier")

    def test_rejects_duplicate_nonsequential_and_backward_step_ordering(self) -> None:
        duplicate_order = self.executor.compose(
            WorkflowExecutionRequest(
                "workflow-001",
                (self._step("first", 1), self._step("second", 1)),
            )
        )
        nonsequential_order = self.executor.compose(
            WorkflowExecutionRequest(
                "workflow-001",
                (self._step("first", 1), self._step("second", 3)),
            )
        )
        backward_dependency = self.executor.compose(
            WorkflowExecutionRequest(
                "workflow-001",
                (self._step("first", 1, ("second",)), self._step("second", 2)),
            )
        )

        self.assertEqual(duplicate_order.reason_code, "invalid_workflow_step_order")
        self.assertEqual(nonsequential_order.reason_code, "invalid_workflow_step_order")
        self.assertEqual(backward_dependency.reason_code, "dependency_order_invalid")

    def test_rejects_unknown_self_referential_and_cyclic_dependencies(self) -> None:
        unknown_dependency = self.executor.compose(
            WorkflowExecutionRequest("workflow-001", (self._step("first", 1, ("missing",)),))
        )
        self_dependency = self.executor.compose(
            WorkflowExecutionRequest("workflow-001", (self._step("first", 1, ("first",)),))
        )
        cycle = self.executor.compose(
            WorkflowExecutionRequest(
                "workflow-001",
                (self._step("first", 1, ("second",)), self._step("second", 2, ("first",))),
            )
        )

        self.assertEqual(unknown_dependency.reason_code, "unknown_dependency_reference")
        self.assertEqual(self_dependency.reason_code, "invalid_dependency_reference")
        self.assertEqual(cycle.reason_code, "workflow_dependency_cycle")

    def test_rejects_denied_or_incompletely_bound_step_validation_results(self) -> None:
        denied = self.executor.compose(
            WorkflowExecutionRequest(
                "workflow-001",
                (self._step("first", 1, validation_result=replace(self._validation(), decision="DENY")),),
            )
        )
        incomplete = self.executor.compose(
            WorkflowExecutionRequest(
                "workflow-001",
                (self._step("first", 1, validation_result=replace(self._validation(), mutation_target_ids=())),),
            )
        )

        self.assertEqual(denied.reason_code, "step_execution_not_validated")
        self.assertEqual(incomplete.reason_code, "step_validation_binding_incomplete")

    def test_service_has_no_runtime_executor_or_host_interaction_integration(self) -> None:
        result = self.executor.compose(WorkflowExecutionRequest("workflow-001", (self._step("first", 1),)))

        self.assertTrue(result.planned)
        self.assertFalse(result.filesystem_operation_performed)
        self.assertFalse(result.network_accessed)
        self.assertFalse(result.operating_system_interaction_performed)
        self.assertFalse(result.browser_interaction_performed)
        self.assertFalse(hasattr(self.executor, "runtime"))
        self.assertFalse(hasattr(self.executor, "desktop_executor"))
        self.assertFalse(hasattr(self.executor, "application_executor"))
        self.assertFalse(hasattr(self.executor, "browser_executor"))


if __name__ == "__main__":
    unittest.main()
