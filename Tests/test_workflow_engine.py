"""Focused tests for the standalone Phase 9 workflow engine."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.execution_scheduler import ExecutionSchedulerService, SchedulerRequest
from Evolution.risk_analyzer import RiskAnalysisRequest, RiskAnalyzerService, RiskLevel
from Evolution.task_planner import ExecutionPlan, TaskPlannerService, TaskPlanningRequest
from Evolution.workflow_engine import WorkflowEngineService, WorkflowRequest, WorkflowState


class WorkflowEngineServiceTests(unittest.TestCase):
    """Verify workflow composition stays deterministic, typed, and non-executing."""

    def setUp(self) -> None:
        self.planner = TaskPlannerService()
        self.analyzer = RiskAnalyzerService()
        self.scheduler = ExecutionSchedulerService()
        self.engine = WorkflowEngineService()

    def _artifacts(self, request_text: str) -> tuple[ExecutionPlan, object, object]:
        planning_result = self.planner.plan(TaskPlanningRequest(high_level_request=request_text))
        self.assertTrue(planning_result.planned)
        assert planning_result.execution_plan is not None
        plan = planning_result.execution_plan
        risk_result = self.analyzer.analyze(RiskAnalysisRequest(execution_plan=plan))
        self.assertTrue(risk_result.analyzed)
        schedule_result = self.scheduler.schedule(SchedulerRequest(execution_plan=plan))
        self.assertTrue(schedule_result.scheduled)
        assert schedule_result.execution_schedule is not None
        return plan, risk_result, schedule_result.execution_schedule

    def test_orchestrates_typed_artifacts_into_review_workflow(self) -> None:
        plan, risk_result, schedule = self._artifacts("Prepare a source patch and local git commit plan.")

        result = self.engine.orchestrate(
            WorkflowRequest(
                execution_plan=plan,
                risk_analysis=risk_result,
                execution_schedule=schedule,
                request_id="workflow-request-001",
            )
        )

        self.assertTrue(result.orchestrated)
        self.assertEqual(result.reason_code, "workflow_ready_for_human_review")
        self.assertEqual(result.request_id, "workflow-request-001")
        self.assertIsNotNone(result.workflow_definition)
        assert result.workflow_definition is not None
        workflow = result.workflow_definition
        self.assertEqual(workflow.execution_plan_id, plan.execution_plan_id)
        self.assertEqual(workflow.approval_reference, plan.approval_reference)
        self.assertEqual(workflow.risk_level, RiskLevel.HIGH)
        self.assertEqual(workflow.execution_schedule_id, schedule.execution_schedule_id)
        self.assertEqual(workflow.state, WorkflowState.READY_FOR_HUMAN_REVIEW)
        self.assertEqual(
            workflow.state_transitions,
            (
                WorkflowState.PLANNED,
                WorkflowState.RISK_ANALYZED,
                WorkflowState.SCHEDULED,
                WorkflowState.READY_FOR_HUMAN_REVIEW,
            ),
        )
        self.assertEqual([step.step_kind for step in workflow.steps], ["planning", "risk_analysis", "scheduling"])
        self.assertEqual([step.sequence for step in workflow.steps], [1, 2, 3])
        self.assertEqual(workflow.completed_step_count, workflow.total_step_count)
        self.assertFalse(workflow.metadata["execution_performed"])
        self.assertFalse(result.metadata["executor_invoked"])

    def test_critical_risk_creates_a_blocked_non_executing_workflow(self) -> None:
        plan, risk_result, schedule = self._artifacts("Prepare a remote multi-device control plan.")

        result = self.engine.orchestrate(
            WorkflowRequest(execution_plan=plan, risk_analysis=risk_result, execution_schedule=schedule)
        )

        self.assertTrue(result.orchestrated)
        self.assertEqual(result.reason_code, "workflow_blocked_by_critical_risk")
        assert result.workflow_definition is not None
        self.assertEqual(result.workflow_definition.risk_level, RiskLevel.CRITICAL)
        self.assertEqual(result.workflow_definition.state, WorkflowState.BLOCKED)
        self.assertEqual(result.workflow_definition.state_transitions[-1], WorkflowState.BLOCKED)
        self.assertFalse(result.metadata["execution_performed"])

    def test_workflow_identity_is_deterministic_for_identical_artifacts(self) -> None:
        plan, risk_result, schedule = self._artifacts("Prepare a package upgrade plan.")
        request = WorkflowRequest(execution_plan=plan, risk_analysis=risk_result, execution_schedule=schedule)

        first = self.engine.orchestrate(request)
        second = self.engine.orchestrate(request)

        self.assertTrue(first.orchestrated)
        self.assertTrue(second.orchestrated)
        assert first.workflow_definition is not None
        assert second.workflow_definition is not None
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.workflow_definition.workflow_id, second.workflow_definition.workflow_id)
        self.assertEqual(first.workflow_definition.workflow_fingerprint, second.workflow_definition.workflow_fingerprint)
        self.assertEqual(first.workflow_definition.steps, second.workflow_definition.steps)

    def test_rejects_analysis_and_schedule_binding_mismatches(self) -> None:
        plan, _, schedule = self._artifacts("Prepare a package plan.")
        other_plan, other_risk_result, _ = self._artifacts("Prepare a source plan.")
        mismatched_analysis_result = self.engine.orchestrate(
            WorkflowRequest(execution_plan=plan, risk_analysis=other_risk_result, execution_schedule=schedule)
        )
        mismatched_schedule_result = self.engine.orchestrate(
            WorkflowRequest(
                execution_plan=plan,
                risk_analysis=self.analyzer.analyze(RiskAnalysisRequest(execution_plan=plan)),
                execution_schedule=replace(schedule, plan_fingerprint=other_plan.plan_fingerprint),
            )
        )

        self.assertFalse(mismatched_analysis_result.orchestrated)
        self.assertEqual(mismatched_analysis_result.reason_code, "risk_analysis_plan_binding_mismatch")
        self.assertFalse(mismatched_schedule_result.orchestrated)
        self.assertEqual(mismatched_schedule_result.reason_code, "execution_schedule_plan_binding_mismatch")
        self.assertFalse(mismatched_schedule_result.metadata["executor_invoked"])

    def test_rejects_untyped_requests_and_nonsequential_schedules(self) -> None:
        plan, risk_result, schedule = self._artifacts("Prepare a package plan.")
        invalid_request_result = self.engine.orchestrate("not-a-workflow-request")  # type: ignore[arg-type]
        parallel_schedule_result = self.engine.orchestrate(
            WorkflowRequest(
                execution_plan=plan,
                risk_analysis=risk_result,
                execution_schedule=replace(schedule, policy=replace(schedule.policy, allow_parallel_tasks=True)),
            )
        )

        self.assertFalse(invalid_request_result.orchestrated)
        self.assertEqual(invalid_request_result.reason_code, "invalid_workflow_request")
        self.assertFalse(parallel_schedule_result.orchestrated)
        self.assertEqual(parallel_schedule_result.reason_code, "execution_schedule_policy_invalid")
        self.assertFalse(parallel_schedule_result.metadata["execution_performed"])


if __name__ == "__main__":
    unittest.main()
