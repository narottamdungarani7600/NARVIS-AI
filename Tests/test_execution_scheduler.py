"""Focused tests for the standalone Phase 9 execution scheduler."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.execution_scheduler import (
    ExecutionSchedulerService,
    SchedulerRequest,
    SchedulingPolicy,
)
from Evolution.task_planner import ExecutionPlan, PlannedTask, TaskDependency, TaskPlannerService, TaskPlanningRequest


class ExecutionSchedulerServiceTests(unittest.TestCase):
    """Verify typed schedules remain dependency-respecting, deterministic, and non-executing."""

    def setUp(self) -> None:
        self.planner = TaskPlannerService()
        self.scheduler = ExecutionSchedulerService()

    def _plan(self, request_text: str) -> ExecutionPlan:
        result = self.planner.plan(TaskPlanningRequest(high_level_request=request_text))
        self.assertTrue(result.planned)
        assert result.execution_plan is not None
        return result.execution_plan

    def test_schedules_planner_tasks_in_deterministic_dependency_order(self) -> None:
        plan = self._plan("Prepare a source patch and local git commit plan.")
        result = self.scheduler.schedule(SchedulerRequest(execution_plan=plan, request_id="schedule-request-001"))

        self.assertTrue(result.scheduled)
        self.assertEqual(result.decision, "scheduled")
        self.assertEqual(result.reason_code, "execution_schedule_created")
        self.assertEqual(result.request_id, "schedule-request-001")
        self.assertIsNotNone(result.execution_schedule)
        assert result.execution_schedule is not None
        schedule = result.execution_schedule
        self.assertEqual(schedule.execution_plan_id, plan.execution_plan_id)
        self.assertEqual(schedule.approval_reference, plan.approval_reference)
        self.assertEqual(
            [task.task_kind for task in schedule.scheduled_tasks],
            [
                "scope_review",
                "precondition_review",
                "source_task_planning",
                "git_task_planning",
                "execution_plan_assembly",
            ],
        )
        self.assertEqual(schedule.execution_order, tuple(task.task_id for task in schedule.scheduled_tasks))
        self.assertEqual([task.sequence for task in schedule.scheduled_tasks], [1, 2, 3, 4, 5])
        self.assertEqual(schedule.scheduled_tasks[-1].prerequisite_task_ids, (plan.tasks[2].task_id, plan.tasks[3].task_id))
        self.assertTrue(all(task.status == "scheduled" for task in schedule.scheduled_tasks))
        self.assertFalse(schedule.metadata["execution_performed"])
        self.assertFalse(result.metadata["executor_invoked"])

    def test_dependency_order_overrides_input_task_tuple_order(self) -> None:
        root = PlannedTask("root-task", "scope_review", "Review", "Review only.", "low", 1)
        middle = PlannedTask("middle-task", "precondition_review", "Review", "Review only.", "low", 2, ("root-task",))
        final = PlannedTask("final-task", "execution_plan_assembly", "Assemble", "Review only.", "low", 3, ("middle-task",))
        dependencies = (
            TaskDependency("dependency-middle", "middle-task", "root-task"),
            TaskDependency("dependency-final", "final-task", "middle-task"),
        )
        plan = ExecutionPlan(
            execution_plan_id="manual-plan-001",
            plan_fingerprint="manual-fingerprint-001",
            request_id="manual-request-001",
            high_level_request="Review only.",
            approval_reference="approval-reference-001",
            tasks=(final, root, middle),
            dependencies=dependencies,
            estimated_risk_level="low",
            estimated_execution_order=("final-task", "root-task", "middle-task"),
        )

        result = self.scheduler.schedule(SchedulerRequest(execution_plan=plan))

        self.assertTrue(result.scheduled)
        assert result.execution_schedule is not None
        self.assertEqual(result.execution_schedule.execution_order, ("root-task", "middle-task", "final-task"))

    def test_schedule_is_deterministic_for_same_plan_and_policy(self) -> None:
        plan = self._plan("Prepare a package upgrade plan.")
        request = SchedulerRequest(execution_plan=plan, policy=SchedulingPolicy())

        first = self.scheduler.schedule(request)
        second = self.scheduler.schedule(request)

        self.assertTrue(first.scheduled)
        self.assertTrue(second.scheduled)
        assert first.execution_schedule is not None
        assert second.execution_schedule is not None
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.execution_schedule.execution_schedule_id, second.execution_schedule.execution_schedule_id)
        self.assertEqual(first.execution_schedule.schedule_fingerprint, second.execution_schedule.schedule_fingerprint)
        self.assertEqual(first.execution_schedule.scheduled_tasks, second.execution_schedule.scheduled_tasks)

    def test_detects_dependency_cycle_without_scheduling_tasks(self) -> None:
        first = PlannedTask("cycle-first", "scope_review", "First", "Review only.", "low", 1, ("cycle-second",))
        second = PlannedTask("cycle-second", "precondition_review", "Second", "Review only.", "low", 2, ("cycle-first",))
        dependencies = (
            TaskDependency("cycle-dependency-1", "cycle-first", "cycle-second"),
            TaskDependency("cycle-dependency-2", "cycle-second", "cycle-first"),
        )
        plan = ExecutionPlan(
            execution_plan_id="cycle-plan-001",
            plan_fingerprint="cycle-fingerprint-001",
            request_id="cycle-request-001",
            high_level_request="Review only.",
            approval_reference="approval-reference-001",
            tasks=(first, second),
            dependencies=dependencies,
            estimated_risk_level="low",
            estimated_execution_order=("cycle-first", "cycle-second"),
        )

        result = self.scheduler.schedule(SchedulerRequest(execution_plan=plan))

        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason_code, "dependency_cycle")
        self.assertIsNone(result.execution_schedule)
        self.assertFalse(result.metadata["execution_performed"])

    def test_rejects_invalid_policy_and_dependency_bindings(self) -> None:
        plan = self._plan("Prepare a package plan.")
        parallel_result = self.scheduler.schedule(
            SchedulerRequest(execution_plan=plan, policy=SchedulingPolicy(allow_parallel_tasks=True))
        )
        invalid_dependency_plan = replace(plan, dependencies=())
        dependency_result = self.scheduler.schedule(SchedulerRequest(execution_plan=invalid_dependency_plan))

        self.assertFalse(parallel_result.scheduled)
        self.assertEqual(parallel_result.reason_code, "invalid_scheduling_policy")
        self.assertFalse(dependency_result.scheduled)
        self.assertEqual(dependency_result.reason_code, "dependency_binding_invalid")
        self.assertFalse(dependency_result.metadata["executor_invoked"])

    def test_rejects_untyped_request_and_lists_supported_strategy(self) -> None:
        result = self.scheduler.schedule("not-a-scheduler-request")  # type: ignore[arg-type]

        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason_code, "invalid_scheduler_request")
        self.assertFalse(result.metadata["execution_performed"])
        self.assertEqual(self.scheduler.list_supported_strategies(), ("dependency_order",))


if __name__ == "__main__":
    unittest.main()
