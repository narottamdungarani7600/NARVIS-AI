"""Standalone deterministic scheduling for Phase 9 execution plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import compact_text, sanitize_durable_mapping, stable_id
from .task_planner import ExecutionPlan, PlannedTask, TaskDependency

_SUPPORTED_STRATEGY = "dependency_order"
_SUPPORTED_DEPENDENCY_KIND = "finish_to_start"


def _normalized_text(value: Any, *, max_chars: int) -> str:
    """Normalize one bounded text field without interpreting arbitrary values as commands."""

    return compact_text(value if isinstance(value, str) else "", max_chars=max_chars).strip()


@dataclass(slots=True, frozen=True)
class SchedulingPolicy:
    """One strict scheduling policy that permits deterministic planning only."""

    policy_id: str = "dependency_order_v1"
    strategy: str = _SUPPORTED_STRATEGY
    allow_parallel_tasks: bool = False
    tie_breaker: str = "estimated_execution_order"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SchedulerRequest:
    """One typed request to schedule an approved execution plan without execution."""

    execution_plan: ExecutionPlan
    policy: SchedulingPolicy = field(default_factory=SchedulingPolicy)
    request_id: str = ""
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ScheduledTask:
    """One scheduled task record that contains no executable operation."""

    scheduled_task_id: str
    task_id: str
    task_kind: str
    sequence: int
    prerequisite_task_ids: tuple[str, ...] = ()
    status: str = "scheduled"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExecutionSchedule:
    """One typed, dependency-respecting execution schedule with no runtime behavior."""

    execution_schedule_id: str
    schedule_fingerprint: str
    execution_plan_id: str
    plan_fingerprint: str
    approval_reference: str
    policy: SchedulingPolicy
    scheduled_tasks: tuple[ScheduledTask, ...]
    execution_order: tuple[str, ...]
    status: str = "scheduled"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SchedulerResult:
    """One typed scheduler result that never represents task execution."""

    decision: str
    reason_code: str
    reason: str
    request_id: str = ""
    execution_plan_id: str = ""
    execution_schedule: ExecutionSchedule | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def scheduled(self) -> bool:
        """Return True only when a typed schedule was materialized without execution."""

        return self.decision == "scheduled" and self.execution_schedule is not None


class ExecutionSchedulerService:
    """Create deterministic dependency schedules without task execution or runtime integration."""

    def list_supported_strategies(self) -> tuple[str, ...]:
        """Return the one conservative scheduling strategy supported by this standalone service."""

        return (_SUPPORTED_STRATEGY,)

    def schedule(self, request: SchedulerRequest) -> SchedulerResult:
        """Materialize a deterministic typed schedule from one execution plan without executing tasks."""

        if not isinstance(request, SchedulerRequest):
            return self._reject(
                reason_code="invalid_scheduler_request",
                reason="Scheduling requires one typed SchedulerRequest.",
            )
        if not isinstance(request.execution_plan, ExecutionPlan):
            return self._reject(
                reason_code="invalid_execution_plan",
                reason="Scheduling requires one typed ExecutionPlan.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )
        if not self._is_supported_policy(request.policy):
            return self._reject(
                reason_code="invalid_scheduling_policy",
                reason="Scheduling supports only sequential dependency_order policy with the estimated execution-order tie breaker.",
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=request.execution_plan.execution_plan_id,
            )

        plan = request.execution_plan
        validation_error = self._validate_plan(plan)
        if validation_error is not None:
            reason_code, reason = validation_error
            return self._reject(
                reason_code=reason_code,
                reason=reason,
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=plan.execution_plan_id,
            )

        ordered_tasks = self._topological_order(plan)
        if ordered_tasks is None:
            return self._reject(
                reason_code="dependency_cycle",
                reason="Execution schedules cannot be created from plans with cyclic task dependencies.",
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=plan.execution_plan_id,
            )

        request_id = _normalized_text(request.request_id, max_chars=120) or stable_id(
            "scheduler_request",
            plan.execution_plan_id,
            plan.plan_fingerprint,
            self._policy_payload(request.policy),
        )
        schedule_fingerprint = stable_id(
            "execution_schedule_fingerprint",
            {
                "execution_plan_id": plan.execution_plan_id,
                "plan_fingerprint": plan.plan_fingerprint,
                "approval_reference": plan.approval_reference,
                "policy": self._policy_payload(request.policy),
                "execution_order": tuple(task.task_id for task in ordered_tasks),
            },
        )
        schedule_id = stable_id("execution_schedule", schedule_fingerprint)
        scheduled_tasks = tuple(
            ScheduledTask(
                scheduled_task_id=stable_id("scheduled_task", schedule_id, sequence, task.task_id),
                task_id=task.task_id,
                task_kind=task.task_kind,
                sequence=sequence,
                prerequisite_task_ids=task.dependency_task_ids,
                metadata=sanitize_durable_mapping(
                    {
                        "execution_performed": False,
                        "executor_invoked": False,
                        "source_task_order": task.estimated_execution_order,
                    }
                ),
            )
            for sequence, task in enumerate(ordered_tasks, start=1)
        )
        schedule = ExecutionSchedule(
            execution_schedule_id=schedule_id,
            schedule_fingerprint=schedule_fingerprint,
            execution_plan_id=plan.execution_plan_id,
            plan_fingerprint=plan.plan_fingerprint,
            approval_reference=plan.approval_reference,
            policy=request.policy,
            scheduled_tasks=scheduled_tasks,
            execution_order=tuple(task.task_id for task in ordered_tasks),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.execution_scheduling",
                    "task_count": len(scheduled_tasks),
                    "dependency_count": len(plan.dependencies),
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                    "request_metadata": request.metadata if isinstance(request.metadata, dict) else {},
                }
            ),
        )
        return SchedulerResult(
            decision="scheduled",
            reason_code="execution_schedule_created",
            reason="The execution plan was converted into a dependency-respecting typed schedule without task execution.",
            request_id=request_id,
            execution_plan_id=plan.execution_plan_id,
            execution_schedule=schedule,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.execution_scheduling",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )

    def _is_supported_policy(self, policy: SchedulingPolicy) -> bool:
        """Return True only for the strict non-parallel deterministic policy."""

        return bool(
            isinstance(policy, SchedulingPolicy)
            and _normalized_text(policy.strategy, max_chars=80) == _SUPPORTED_STRATEGY
            and not policy.allow_parallel_tasks
            and _normalized_text(policy.tie_breaker, max_chars=80) == "estimated_execution_order"
        )

    def _policy_payload(self, policy: SchedulingPolicy) -> dict[str, Any]:
        """Return the policy fields that define deterministic schedule identity."""

        return {
            "policy_id": _normalized_text(policy.policy_id, max_chars=120),
            "strategy": _normalized_text(policy.strategy, max_chars=80),
            "allow_parallel_tasks": bool(policy.allow_parallel_tasks),
            "tie_breaker": _normalized_text(policy.tie_breaker, max_chars=80),
        }

    def _validate_plan(self, plan: ExecutionPlan) -> tuple[str, str] | None:
        """Validate typed task and dependency bindings before scheduling any future work."""

        if _normalized_text(plan.status, max_chars=80).lower() != "planned":
            return (
                "execution_plan_not_planned",
                "Scheduling accepts only execution plans that remain in the planned state.",
            )
        if not isinstance(plan.tasks, tuple) or not plan.tasks or not all(
            isinstance(task, PlannedTask) for task in plan.tasks
        ):
            return (
                "execution_plan_tasks_invalid",
                "Scheduling requires one non-empty typed task tuple.",
            )
        if not isinstance(plan.dependencies, tuple) or not all(
            isinstance(dependency, TaskDependency) for dependency in plan.dependencies
        ):
            return (
                "execution_plan_dependencies_invalid",
                "Scheduling requires one typed dependency tuple.",
            )

        task_ids = tuple(task.task_id for task in plan.tasks)
        task_orders = tuple(task.estimated_execution_order for task in plan.tasks)
        if (
            not all(_normalized_text(task_id, max_chars=120) for task_id in task_ids)
            or len(set(task_ids)) != len(task_ids)
            or set(task_orders) != set(range(1, len(plan.tasks) + 1))
            or len(set(task_orders)) != len(task_orders)
            or set(plan.estimated_execution_order) != set(task_ids)
            or len(plan.estimated_execution_order) != len(task_ids)
        ):
            return (
                "execution_plan_order_invalid",
                "Task identifiers and estimated execution-order bindings must be complete and unique.",
            )

        task_id_set = set(task_ids)
        expected_edges = {
            (task.task_id, prerequisite_task_id)
            for task in plan.tasks
            for prerequisite_task_id in task.dependency_task_ids
        }
        declared_edges = {
            (dependency.dependent_task_id, dependency.prerequisite_task_id)
            for dependency in plan.dependencies
        }
        if (
            len(declared_edges) != len(plan.dependencies)
            or any(
                dependency.dependency_kind != _SUPPORTED_DEPENDENCY_KIND
                or dependency.dependent_task_id not in task_id_set
                or dependency.prerequisite_task_id not in task_id_set
                or dependency.dependent_task_id == dependency.prerequisite_task_id
                for dependency in plan.dependencies
            )
            or expected_edges != declared_edges
        ):
            return (
                "dependency_binding_invalid",
                "Dependencies must be unique finish-to-start bindings between distinct known plan tasks.",
            )
        return None

    def _topological_order(self, plan: ExecutionPlan) -> tuple[PlannedTask, ...] | None:
        """Return a deterministic sequential topological order or None when a dependency cycle exists."""

        task_by_id = {task.task_id: task for task in plan.tasks}
        prerequisites_by_task = {
            task.task_id: set(task.dependency_task_ids)
            for task in plan.tasks
        }
        dependents_by_task = {task.task_id: set() for task in plan.tasks}
        for task_id, prerequisite_ids in prerequisites_by_task.items():
            for prerequisite_task_id in prerequisite_ids:
                dependents_by_task[prerequisite_task_id].add(task_id)

        ready_task_ids = [task_id for task_id, prerequisites in prerequisites_by_task.items() if not prerequisites]
        ordered_task_ids: list[str] = []
        while ready_task_ids:
            ready_task_ids.sort(
                key=lambda task_id: (
                    task_by_id[task_id].estimated_execution_order,
                    task_id,
                )
            )
            task_id = ready_task_ids.pop(0)
            ordered_task_ids.append(task_id)
            for dependent_task_id in dependents_by_task[task_id]:
                prerequisites_by_task[dependent_task_id].remove(task_id)
                if not prerequisites_by_task[dependent_task_id]:
                    ready_task_ids.append(dependent_task_id)

        if len(ordered_task_ids) != len(plan.tasks):
            return None
        return tuple(task_by_id[task_id] for task_id in ordered_task_ids)

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        request_id: str = "",
        execution_plan_id: str = "",
    ) -> SchedulerResult:
        """Build one typed non-executing scheduling rejection."""

        return SchedulerResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            request_id=compact_text(request_id, max_chars=120),
            execution_plan_id=compact_text(execution_plan_id, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.execution_scheduling",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )


__all__ = [
    "ExecutionSchedule",
    "ExecutionSchedulerService",
    "ScheduledTask",
    "SchedulerRequest",
    "SchedulerResult",
    "SchedulingPolicy",
]
