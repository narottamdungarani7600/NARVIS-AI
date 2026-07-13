"""Focused tests for the standalone Phase 9 task planner."""

from __future__ import annotations

import unittest

from Evolution.task_planner import TaskPlannerService, TaskPlanningRequest


class TaskPlannerServiceTests(unittest.TestCase):
    """Verify task plans remain typed, deterministic, ordered, and non-executing."""

    def setUp(self) -> None:
        self.planner = TaskPlannerService()

    def test_plan_creates_ordered_high_risk_source_and_git_tasks_with_dependencies(self) -> None:
        result = self.planner.plan(
            TaskPlanningRequest(
                request_id="task-request-001",
                approval_reference="approval-reference-001",
                high_level_request="Prepare a source patch and local git commit plan for the approved capability.",
            )
        )

        self.assertTrue(result.planned)
        self.assertEqual(result.decision, "planned")
        self.assertEqual(result.reason_code, "task_plan_created")
        self.assertEqual(result.request_id, "task-request-001")
        self.assertIsNotNone(result.execution_plan)
        assert result.execution_plan is not None
        plan = result.execution_plan
        self.assertEqual(plan.estimated_risk_level, "high")
        self.assertEqual(plan.approval_reference, "approval-reference-001")
        self.assertEqual(
            [task.task_kind for task in plan.tasks],
            [
                "scope_review",
                "precondition_review",
                "source_task_planning",
                "git_task_planning",
                "execution_plan_assembly",
            ],
        )
        self.assertEqual(
            [task.estimated_execution_order for task in plan.tasks],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(plan.estimated_execution_order, tuple(task.task_id for task in plan.tasks))
        self.assertEqual(len(plan.dependencies), 5)
        self.assertEqual(plan.tasks[1].dependency_task_ids, (plan.tasks[0].task_id,))
        self.assertEqual(plan.tasks[2].dependency_task_ids, (plan.tasks[1].task_id,))
        self.assertEqual(plan.tasks[3].dependency_task_ids, (plan.tasks[1].task_id,))
        self.assertEqual(plan.tasks[4].dependency_task_ids, (plan.tasks[2].task_id, plan.tasks[3].task_id))
        self.assertTrue(all(task.status == "planned" for task in plan.tasks))
        self.assertFalse(plan.metadata["execution_performed"])
        self.assertFalse(plan.metadata["executor_invoked"])
        self.assertFalse(result.metadata["execution_performed"])

    def test_plan_estimates_medium_risk_for_package_plugin_and_sandbox_work(self) -> None:
        result = self.planner.plan(
            TaskPlanningRequest(
                high_level_request="Plan an isolated sandbox package install with a local plugin integration.",
            )
        )

        self.assertTrue(result.planned)
        assert result.execution_plan is not None
        plan = result.execution_plan
        self.assertEqual(plan.estimated_risk_level, "medium")
        self.assertEqual(plan.metadata["planned_categories"], ["sandbox", "package", "plugin"])
        self.assertEqual(
            [task.risk_level for task in plan.tasks[2:-1]],
            ["medium", "medium", "medium"],
        )

    def test_plan_uses_conservative_general_category_when_no_specific_surface_matches(self) -> None:
        result = self.planner.plan(
            TaskPlanningRequest(high_level_request="Improve the approved capability discovery summary.")
        )

        self.assertTrue(result.planned)
        assert result.execution_plan is not None
        plan = result.execution_plan
        self.assertEqual(plan.estimated_risk_level, "medium")
        self.assertEqual(plan.metadata["planned_categories"], ["general"])
        self.assertEqual(
            [task.task_kind for task in plan.tasks],
            ["scope_review", "precondition_review", "general_task_planning", "execution_plan_assembly"],
        )

    def test_plan_is_deterministic_for_the_same_typed_request(self) -> None:
        request = TaskPlanningRequest(
            high_level_request="Prepare a package upgrade task plan.",
            approval_reference="approval-reference-002",
            metadata={"source": "approved-review"},
        )

        first = self.planner.plan(request)
        second = self.planner.plan(request)

        self.assertTrue(first.planned)
        self.assertTrue(second.planned)
        assert first.execution_plan is not None
        assert second.execution_plan is not None
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.execution_plan.execution_plan_id, second.execution_plan.execution_plan_id)
        self.assertEqual(first.execution_plan.plan_fingerprint, second.execution_plan.plan_fingerprint)
        self.assertEqual(first.execution_plan.tasks, second.execution_plan.tasks)
        self.assertEqual(first.execution_plan.dependencies, second.execution_plan.dependencies)
        self.assertFalse(first.execution_plan.metadata["executor_invoked"])
        self.assertFalse(first.execution_plan.metadata["approval_validation_performed"])

    def test_plan_rejects_missing_or_untyped_high_level_requests(self) -> None:
        empty_result = self.planner.plan(TaskPlanningRequest(high_level_request="   "))
        invalid_result = self.planner.plan("prepare a task plan")  # type: ignore[arg-type]

        self.assertFalse(empty_result.planned)
        self.assertEqual(empty_result.reason_code, "high_level_request_required")
        self.assertIsNone(empty_result.execution_plan)
        self.assertFalse(empty_result.metadata["execution_performed"])
        self.assertFalse(invalid_result.planned)
        self.assertEqual(invalid_result.reason_code, "invalid_task_planning_request")
        self.assertFalse(invalid_result.metadata["executor_invoked"])

    def test_lists_conservative_supported_risk_levels(self) -> None:
        self.assertEqual(self.planner.list_supported_risk_levels(), ("low", "medium", "high"))


if __name__ == "__main__":
    unittest.main()
