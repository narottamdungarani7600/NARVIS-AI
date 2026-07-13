"""Focused tests for the standalone Phase 9 risk analyzer."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.models import MutationTarget
from Evolution.risk_analyzer import RiskAnalysisRequest, RiskAnalyzerService, RiskLevel
from Evolution.task_planner import ExecutionPlan, PlannedTask, TaskPlannerService, TaskPlanningRequest


class RiskAnalyzerServiceTests(unittest.TestCase):
    """Verify execution-plan risk analysis remains typed, deterministic, and non-executing."""

    def setUp(self) -> None:
        self.planner = TaskPlannerService()
        self.analyzer = RiskAnalyzerService()

    def _plan(self, request_text: str) -> ExecutionPlan:
        result = self.planner.plan(TaskPlanningRequest(high_level_request=request_text))
        self.assertTrue(result.planned)
        assert result.execution_plan is not None
        return result.execution_plan

    def test_source_and_git_task_types_are_high_risk_with_human_review_recommendation(self) -> None:
        result = self.analyzer.analyze(
            RiskAnalysisRequest(
                execution_plan=self._plan("Prepare a source patch and local git commit plan."),
            )
        )

        self.assertTrue(result.analyzed)
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertEqual(result.reason_code, "risk_analysis_completed")
        self.assertTrue(any(factor.factor_type == "high_impact_task_type" for factor in result.factors))
        self.assertEqual(result.recommendations[0].code, "require_explicit_human_review")
        self.assertTrue(result.recommendations[0].requires_human_approval)
        self.assertFalse(result.metadata["execution_performed"])
        self.assertFalse(result.metadata["executor_invoked"])

    def test_package_plugin_and_sandbox_tasks_are_medium_risk_and_include_dependency_count(self) -> None:
        result = self.analyzer.analyze(
            RiskAnalysisRequest(
                execution_plan=self._plan("Plan sandbox package installation with a local plugin integration."),
            )
        )

        self.assertTrue(result.analyzed)
        self.assertEqual(result.risk_level, RiskLevel.MEDIUM)
        self.assertGreaterEqual(
            sum(factor.factor_type == "controlled_mutation_task_type" for factor in result.factors),
            3,
        )
        self.assertTrue(any(factor.factor_type == "dependency_count_medium" for factor in result.factors))
        self.assertEqual(result.recommendations[0].code, "require_focused_verification")

    def test_remote_task_planning_is_critical_and_remains_review_only(self) -> None:
        result = self.analyzer.analyze(
            RiskAnalysisRequest(execution_plan=self._plan("Prepare a remote multi-device control plan."))
        )

        self.assertTrue(result.analyzed)
        self.assertEqual(result.risk_level, RiskLevel.CRITICAL)
        self.assertTrue(any(factor.factor_type == "remote_task_type" for factor in result.factors))
        self.assertEqual(result.recommendations[0].code, "block_pending_design_review")
        self.assertFalse(result.recommendations[0].metadata["executor_invoked"])

    def test_protected_mutation_target_is_critical_without_target_validation_or_execution(self) -> None:
        target = MutationTarget(
            mutation_target_id="protected-target-001",
            plan_step_id="plan-step-001",
            execution_step_request_id="step-request-001",
            executor_category="code_development",
            action_kind="source_modify",
            target_kind="source_file",
            locator="Docs/AI_DEVELOPMENT_RULES.md",
            risk_classification="high",
        )
        result = self.analyzer.analyze(
            RiskAnalysisRequest(
                execution_plan=self._plan("Prepare a source change review."),
                mutation_targets=(target,),
            )
        )

        self.assertTrue(result.analyzed)
        self.assertEqual(result.risk_level, RiskLevel.CRITICAL)
        protected_factor = next(factor for factor in result.factors if factor.factor_type == "protected_mutation_target")
        self.assertEqual(protected_factor.mutation_target_ids, ("protected-target-001",))
        self.assertFalse(protected_factor.metadata["execution_performed"])

    def test_low_risk_typed_plan_is_assessed_as_low_when_no_elevated_tasks_or_targets_exist(self) -> None:
        task = PlannedTask(
            task_id="safe-task-001",
            task_kind="scope_review",
            title="Review scope",
            description="Review only.",
            risk_level="low",
            estimated_execution_order=1,
        )
        plan = ExecutionPlan(
            execution_plan_id="safe-plan-001",
            plan_fingerprint="safe-plan-fingerprint-001",
            request_id="safe-request-001",
            high_level_request="Review a non-mutating summary.",
            approval_reference="",
            tasks=(task,),
            dependencies=(),
            estimated_risk_level="low",
            estimated_execution_order=(task.task_id,),
        )

        result = self.analyzer.analyze(RiskAnalysisRequest(execution_plan=plan))

        self.assertTrue(result.analyzed)
        self.assertEqual(result.risk_level, RiskLevel.LOW)
        self.assertEqual(result.recommendations[0].code, "maintain_standard_review")
        self.assertTrue(any(factor.factor_type == "mutation_targets_unresolved" for factor in result.factors))

    def test_malformed_execution_order_is_critical_and_invalid_request_is_rejected(self) -> None:
        plan = self._plan("Prepare a package plan.")
        malformed_plan = replace(plan, estimated_execution_order=())

        malformed_result = self.analyzer.analyze(RiskAnalysisRequest(execution_plan=malformed_plan))
        invalid_result = self.analyzer.analyze("not-a-risk-request")  # type: ignore[arg-type]

        self.assertTrue(malformed_result.analyzed)
        self.assertEqual(malformed_result.risk_level, RiskLevel.CRITICAL)
        self.assertTrue(any(factor.factor_type == "execution_order_mismatch" for factor in malformed_result.factors))
        self.assertFalse(invalid_result.analyzed)
        self.assertEqual(invalid_result.reason_code, "invalid_risk_analysis_request")
        self.assertFalse(invalid_result.metadata["execution_performed"])

    def test_lists_all_typed_risk_levels(self) -> None:
        self.assertEqual(
            self.analyzer.list_risk_levels(),
            (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL),
        )


if __name__ == "__main__":
    unittest.main()
