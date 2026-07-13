"""Standalone typed task planning for future Phase 9 orchestration work."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import compact_text, sanitize_durable_mapping, stable_id

_RISK_LEVELS = ("low", "medium", "high")
_RISK_RANK = {risk_level: index for index, risk_level in enumerate(_RISK_LEVELS)}
_CATEGORY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("source", "high", ("source", "code", "patch", "refactor", "rewrite")),
    ("git", "high", ("git", "repository", "commit", "branch")),
    ("remote", "high", ("remote", "multi-device", "multi device", "network device")),
    ("sandbox", "medium", ("sandbox", "isolated runtime", "experiment runner")),
    ("package", "medium", ("package", "dependency", "install", "uninstall", "upgrade")),
    ("plugin", "medium", ("plugin", "extension", "integration", "connector")),
)
_DEFAULT_CATEGORY = ("general", "medium")


def _normalized_text(value: Any, *, max_chars: int) -> str:
    """Normalize one bounded text field without treating arbitrary objects as instructions."""

    return compact_text(value if isinstance(value, str) else "", max_chars=max_chars).strip()


@dataclass(slots=True, frozen=True)
class TaskPlanningRequest:
    """One high-level request to convert into a typed, non-executing task plan."""

    high_level_request: str
    request_id: str = ""
    approval_reference: str = ""
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PlannedTask:
    """One ordered task in an execution plan; it contains no executable operation."""

    task_id: str
    task_kind: str
    title: str
    description: str
    risk_level: str
    estimated_execution_order: int
    dependency_task_ids: tuple[str, ...] = ()
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class TaskDependency:
    """One finish-to-start dependency between two planned tasks."""

    dependency_id: str
    dependent_task_id: str
    prerequisite_task_id: str
    dependency_kind: str = "finish_to_start"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExecutionPlan:
    """One typed, reviewable execution plan with no execution capability."""

    execution_plan_id: str
    plan_fingerprint: str
    request_id: str
    high_level_request: str
    approval_reference: str
    tasks: tuple[PlannedTask, ...]
    dependencies: tuple[TaskDependency, ...]
    estimated_risk_level: str
    estimated_execution_order: tuple[str, ...]
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class TaskPlanningResult:
    """One typed result from standalone task planning."""

    decision: str
    reason_code: str
    reason: str
    request_id: str = ""
    execution_plan: ExecutionPlan | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def planned(self) -> bool:
        """Return True only when the request produced one typed execution plan."""

        return self.decision == "planned" and self.execution_plan is not None


class TaskPlannerService:
    """Build deterministic task plans without execution, runtime access, or approval changes."""

    def list_supported_risk_levels(self) -> tuple[str, ...]:
        """Return the supported conservative risk levels in deterministic order."""

        return _RISK_LEVELS

    def plan(self, request: TaskPlanningRequest) -> TaskPlanningResult:
        """Convert one high-level request into a typed task plan without performing any task."""

        if not isinstance(request, TaskPlanningRequest):
            return self._reject(
                reason_code="invalid_task_planning_request",
                reason="Task planning requires one typed TaskPlanningRequest.",
            )

        high_level_request = _normalized_text(request.high_level_request, max_chars=800)
        if not high_level_request:
            return self._reject(
                reason_code="high_level_request_required",
                reason="Task planning requires one non-empty high-level request.",
            )

        approval_reference = _normalized_text(request.approval_reference, max_chars=120)
        request_id = _normalized_text(request.request_id, max_chars=120) or stable_id(
            "task_planning_request",
            {
                "high_level_request": high_level_request,
                "approval_reference": approval_reference,
            },
        )
        categories = self._classify_categories(high_level_request)
        estimated_risk_level = self._estimate_risk_level(categories)
        plan_fingerprint = stable_id(
            "task_execution_plan_fingerprint",
            {
                "request_id": request_id,
                "high_level_request": high_level_request,
                "approval_reference": approval_reference,
                "categories": categories,
                "estimated_risk_level": estimated_risk_level,
            },
        )
        execution_plan_id = stable_id("task_execution_plan", plan_fingerprint)
        tasks, dependencies = self._build_tasks(
            execution_plan_id=execution_plan_id,
            categories=categories,
            estimated_risk_level=estimated_risk_level,
        )
        execution_order = tuple(task.task_id for task in tasks)
        plan = ExecutionPlan(
            execution_plan_id=execution_plan_id,
            plan_fingerprint=plan_fingerprint,
            request_id=request_id,
            high_level_request=high_level_request,
            approval_reference=approval_reference,
            tasks=tasks,
            dependencies=dependencies,
            estimated_risk_level=estimated_risk_level,
            estimated_execution_order=execution_order,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.task_planning",
                    "planned_categories": categories,
                    "task_count": len(tasks),
                    "dependency_count": len(dependencies),
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                    "request_metadata": request.metadata if isinstance(request.metadata, dict) else {},
                }
            ),
        )
        return TaskPlanningResult(
            decision="planned",
            reason_code="task_plan_created",
            reason="The high-level request was converted into an ordered typed task plan without execution.",
            request_id=request_id,
            execution_plan=plan,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.task_planning",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )

    def _classify_categories(self, high_level_request: str) -> tuple[str, ...]:
        """Classify request text into a narrow deterministic set of planning categories."""

        normalized_request = high_level_request.lower()
        categories = tuple(
            category
            for category, _risk_level, markers in _CATEGORY_RULES
            if any(marker in normalized_request for marker in markers)
        )
        return categories or (_DEFAULT_CATEGORY[0],)

    def _estimate_risk_level(self, categories: tuple[str, ...]) -> str:
        """Return the highest conservative risk estimate among the planned categories."""

        risk_by_category = {
            category: risk_level
            for category, risk_level, _markers in _CATEGORY_RULES
        }
        risk_levels = [risk_by_category.get(category, _DEFAULT_CATEGORY[1]) for category in categories]
        return max(risk_levels, key=lambda risk_level: _RISK_RANK[risk_level])

    def _build_tasks(
        self,
        *,
        execution_plan_id: str,
        categories: tuple[str, ...],
        estimated_risk_level: str,
    ) -> tuple[tuple[PlannedTask, ...], tuple[TaskDependency, ...]]:
        """Build an ordered acyclic task graph with explicit review gates before any future execution."""

        task_specs: list[tuple[str, str, str, str, tuple[str, ...]]] = [
            (
                "scope_review",
                "Review requested scope",
                "Identify the requested capability boundaries and record non-executing constraints.",
                "low",
                (),
            )
        ]
        scope_task_id = stable_id("planned_task", execution_plan_id, 1, "scope_review")
        task_specs.append(
            (
                "precondition_review",
                "Review preconditions",
                "Confirm that future approval, verification, recovery, and mutation boundaries remain external to this planner.",
                "low",
                (scope_task_id,),
            )
        )
        precondition_task_id = stable_id("planned_task", execution_plan_id, 2, "precondition_review")

        category_risk = {
            category: risk_level
            for category, risk_level, _markers in _CATEGORY_RULES
        }
        category_task_ids: list[str] = []
        for sequence, category in enumerate(categories, start=3):
            task_kind = f"{category}_task_planning"
            category_task_id = stable_id("planned_task", execution_plan_id, sequence, task_kind)
            category_task_ids.append(category_task_id)
            task_specs.append(
                (
                    task_kind,
                    f"Prepare {category} task plan",
                    f"Describe the bounded {category} work for later human review without executing or invoking an executor.",
                    category_risk.get(category, _DEFAULT_CATEGORY[1]),
                    (precondition_task_id,),
                )
            )

        task_specs.append(
            (
                "execution_plan_assembly",
                "Assemble reviewable execution plan",
                "Combine planned tasks into an ordered, dependency-aware plan for later approval-bound handling.",
                estimated_risk_level,
                tuple(category_task_ids),
            )
        )

        tasks: list[PlannedTask] = []
        dependencies: list[TaskDependency] = []
        for sequence, (task_kind, title, description, risk_level, prerequisite_ids) in enumerate(task_specs, start=1):
            task_id = stable_id("planned_task", execution_plan_id, sequence, task_kind)
            task = PlannedTask(
                task_id=task_id,
                task_kind=task_kind,
                title=title,
                description=description,
                risk_level=risk_level,
                estimated_execution_order=sequence,
                dependency_task_ids=prerequisite_ids,
                metadata=sanitize_durable_mapping(
                    {
                        "execution_performed": False,
                        "executor_invoked": False,
                    }
                ),
            )
            tasks.append(task)
            for prerequisite_task_id in prerequisite_ids:
                dependencies.append(
                    TaskDependency(
                        dependency_id=stable_id(
                            "task_dependency",
                            execution_plan_id,
                            task_id,
                            prerequisite_task_id,
                        ),
                        dependent_task_id=task_id,
                        prerequisite_task_id=prerequisite_task_id,
                        metadata=sanitize_durable_mapping(
                            {
                                "execution_performed": False,
                                "executor_invoked": False,
                            }
                        ),
                    )
                )

        return tuple(tasks), tuple(dependencies)

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        request_id: str = "",
    ) -> TaskPlanningResult:
        """Build one typed non-executing rejection result."""

        return TaskPlanningResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            request_id=compact_text(request_id, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.task_planning",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )


__all__ = [
    "ExecutionPlan",
    "PlannedTask",
    "TaskDependency",
    "TaskPlannerService",
    "TaskPlanningRequest",
    "TaskPlanningResult",
]
