"""Focused tests for the standalone Phase 9 decision engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from Evolution.decision_engine import DecisionEngineService, DecisionRequest, DecisionState
from Evolution.execution_scheduler import ExecutionSchedule, ExecutionSchedulerService, SchedulerRequest
from Evolution.models import MutationApproval
from Evolution.risk_analyzer import RiskAnalysisRequest, RiskAnalysisResult, RiskAnalyzerService
from Evolution.task_planner import ExecutionPlan, TaskPlannerService, TaskPlanningRequest
from Evolution.workflow_engine import WorkflowEngineService, WorkflowRequest, WorkflowResult


class DecisionEngineServiceTests(unittest.TestCase):
    """Verify readiness decisions remain deterministic, approval-bound, and non-executing."""

    evaluated_at = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.planner = TaskPlannerService()
        self.analyzer = RiskAnalyzerService()
        self.scheduler = ExecutionSchedulerService()
        self.workflow_engine = WorkflowEngineService()
        self.decision_engine = DecisionEngineService()

    def _artifacts(self, request_text: str) -> tuple[ExecutionPlan, RiskAnalysisResult, ExecutionSchedule, WorkflowResult]:
        planning_result = self.planner.plan(TaskPlanningRequest(high_level_request=request_text))
        self.assertTrue(planning_result.planned)
        assert planning_result.execution_plan is not None
        plan = planning_result.execution_plan
        risk_analysis = self.analyzer.analyze(RiskAnalysisRequest(execution_plan=plan))
        self.assertTrue(risk_analysis.analyzed)
        schedule_result = self.scheduler.schedule(SchedulerRequest(execution_plan=plan))
        self.assertTrue(schedule_result.scheduled)
        assert schedule_result.execution_schedule is not None
        workflow_result = self.workflow_engine.orchestrate(
            WorkflowRequest(
                execution_plan=plan,
                risk_analysis=risk_analysis,
                execution_schedule=schedule_result.execution_schedule,
            )
        )
        self.assertTrue(workflow_result.orchestrated)
        return plan, risk_analysis, schedule_result.execution_schedule, workflow_result

    def _approval(self, plan: ExecutionPlan, *, expires_at: datetime | None = None) -> MutationApproval:
        return MutationApproval(
            mutation_approval_id="mutation-approval-001",
            mutation_approval_fingerprint="mutation-approval-fingerprint-001",
            recovery_outcome_id="recovery-outcome-001",
            recovery_outcome_fingerprint="recovery-outcome-fingerprint-001",
            recovery_run_id="recovery-run-001",
            recovery_run_fingerprint="recovery-run-fingerprint-001",
            execution_request_id="execution-request-001",
            request_fingerprint="execution-request-fingerprint-001",
            plan_id=plan.execution_plan_id,
            plan_fingerprint=plan.plan_fingerprint,
            proposal_id="proposal-001",
            proposal_fingerprint="proposal-fingerprint-001",
            proposal_version=1,
            approval_decision_id="approval-decision-001",
            mutation_target_ids=("mutation-target-001",),
            mode="apply",
            decision="approved",
            actor="human-reviewer",
            expires_at=expires_at or self.evaluated_at + timedelta(days=1),
        )

    def test_waits_for_explicit_approval_for_a_noncritical_review_workflow(self) -> None:
        plan, risk_analysis, _, workflow_result = self._artifacts("Prepare a package upgrade plan.")

        result = self.decision_engine.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=risk_analysis,
                evaluated_at=self.evaluated_at,
            )
        )

        self.assertTrue(result.decided)
        self.assertEqual(result.state, DecisionState.WAITING_FOR_APPROVAL)
        self.assertEqual(result.reason_code, "mutation_approval_required")
        assert result.execution_decision is not None
        self.assertEqual(result.execution_decision.execution_plan_id, plan.execution_plan_id)
        self.assertTrue(result.execution_decision.requires_human_approval)
        self.assertFalse(result.execution_decision.execution_allowed)
        self.assertFalse(result.metadata["execution_performed"])

    def test_matching_current_mutation_approval_records_ready_without_execution(self) -> None:
        plan, risk_analysis, _, workflow_result = self._artifacts("Prepare a package upgrade plan.")
        approval = self._approval(plan)

        result = self.decision_engine.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=risk_analysis,
                mutation_approval=approval,
                evaluated_at=self.evaluated_at,
                request_id="decision-request-001",
            )
        )

        self.assertTrue(result.decided)
        self.assertEqual(result.state, DecisionState.READY)
        self.assertEqual(result.reason_code, "matching_mutation_approval_recorded")
        self.assertEqual(result.request_id, "decision-request-001")
        assert result.execution_decision is not None
        self.assertEqual(result.execution_decision.mutation_approval_id, approval.mutation_approval_id)
        self.assertFalse(result.execution_decision.requires_human_approval)
        self.assertFalse(result.execution_decision.execution_allowed)
        self.assertFalse(result.execution_decision.metadata["executor_invoked"])

    def test_critical_risk_blocks_before_approval_evaluation(self) -> None:
        plan, risk_analysis, _, workflow_result = self._artifacts("Prepare a remote multi-device control plan.")

        result = self.decision_engine.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=risk_analysis,
                mutation_approval=self._approval(plan),
                evaluated_at=self.evaluated_at,
            )
        )

        self.assertTrue(result.decided)
        self.assertEqual(result.state, DecisionState.BLOCKED)
        self.assertEqual(result.reason_code, "workflow_or_risk_blocked")
        assert result.execution_decision is not None
        self.assertFalse(result.execution_decision.execution_allowed)

    def test_rejects_mismatched_risk_and_approval_bindings(self) -> None:
        plan, risk_analysis, _, workflow_result = self._artifacts("Prepare a package plan.")
        other_plan, other_risk_analysis, _, _ = self._artifacts("Prepare a source plan.")
        mismatched_risk = self.decision_engine.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=other_risk_analysis,
                evaluated_at=self.evaluated_at,
            )
        )
        mismatched_approval = self.decision_engine.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=risk_analysis,
                mutation_approval=replace(self._approval(plan), plan_fingerprint=other_plan.plan_fingerprint),
                evaluated_at=self.evaluated_at,
            )
        )

        self.assertFalse(mismatched_risk.decided)
        self.assertEqual(mismatched_risk.state, DecisionState.REJECTED)
        self.assertEqual(mismatched_risk.reason_code, "risk_analysis_workflow_binding_mismatch")
        self.assertTrue(mismatched_approval.decided)
        self.assertEqual(mismatched_approval.state, DecisionState.REJECTED)
        self.assertEqual(mismatched_approval.reason_code, "mutation_approval_plan_binding_mismatch")
        self.assertFalse(mismatched_approval.metadata["executor_invoked"])

    def test_expired_approval_waits_for_a_fresh_human_approval(self) -> None:
        plan, risk_analysis, _, workflow_result = self._artifacts("Prepare a package plan.")
        expired_approval = self._approval(plan, expires_at=self.evaluated_at - timedelta(seconds=1))

        result = self.decision_engine.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=risk_analysis,
                mutation_approval=expired_approval,
                evaluated_at=self.evaluated_at,
            )
        )

        self.assertTrue(result.decided)
        self.assertEqual(result.state, DecisionState.WAITING_FOR_APPROVAL)
        self.assertEqual(result.reason_code, "mutation_approval_expired")
        assert result.execution_decision is not None
        self.assertTrue(result.execution_decision.requires_human_approval)

    def test_is_deterministic_and_rejects_untyped_requests(self) -> None:
        _, risk_analysis, _, workflow_result = self._artifacts("Prepare a package upgrade plan.")
        request = DecisionRequest(
            workflow_result=workflow_result,
            risk_analysis=risk_analysis,
            evaluated_at=self.evaluated_at,
        )

        first = self.decision_engine.decide(request)
        second = self.decision_engine.decide(request)
        invalid = self.decision_engine.decide("not-a-decision-request")  # type: ignore[arg-type]

        self.assertTrue(first.decided)
        self.assertTrue(second.decided)
        assert first.execution_decision is not None
        assert second.execution_decision is not None
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.execution_decision.execution_decision_id, second.execution_decision.execution_decision_id)
        self.assertEqual(first.execution_decision.decision_fingerprint, second.execution_decision.decision_fingerprint)
        self.assertFalse(invalid.decided)
        self.assertEqual(invalid.state, DecisionState.REJECTED)
        self.assertEqual(invalid.reason_code, "invalid_decision_request")
        self.assertEqual(
            self.decision_engine.list_decision_states(),
            (
                DecisionState.READY,
                DecisionState.WAITING_FOR_APPROVAL,
                DecisionState.BLOCKED,
                DecisionState.REJECTED,
            ),
        )


if __name__ == "__main__":
    unittest.main()
