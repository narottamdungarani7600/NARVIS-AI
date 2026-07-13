"""Standalone typed workflow composition for Phase 9 planning artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .execution_scheduler import ExecutionSchedule, ScheduledTask, SchedulingPolicy
from .models import compact_text, sanitize_durable_mapping, stable_id
from .risk_analyzer import RiskAnalysisResult, RiskLevel
from .task_planner import ExecutionPlan, PlannedTask


class WorkflowState(str, Enum):
    """The bounded states available to a non-executing Phase 9 workflow."""

    PLANNED = "planned"
    RISK_ANALYZED = "risk_analyzed"
    SCHEDULED = "scheduled"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    BLOCKED = "blocked"


def _normalized_text(value: Any, *, max_chars: int) -> str:
    """Normalize one bounded text field without interpreting arbitrary values as commands."""

    return compact_text(value if isinstance(value, str) else "", max_chars=max_chars).strip()


@dataclass(slots=True, frozen=True)
class WorkflowRequest:
    """One typed request to compose previously produced planning artifacts into a workflow."""

    execution_plan: ExecutionPlan
    risk_analysis: RiskAnalysisResult
    execution_schedule: ExecutionSchedule
    request_id: str = ""
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class WorkflowStep:
    """One completed orchestration step; it contains no executable task operation."""

    workflow_step_id: str
    step_kind: str
    sequence: int
    state: WorkflowState
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class WorkflowDefinition:
    """One deterministic, review-only workflow composed from planning artifacts."""

    workflow_id: str
    workflow_fingerprint: str
    execution_plan_id: str
    plan_fingerprint: str
    approval_reference: str
    risk_analysis_request_id: str
    risk_level: RiskLevel
    execution_schedule_id: str
    schedule_fingerprint: str
    steps: tuple[WorkflowStep, ...]
    state: WorkflowState
    state_transitions: tuple[WorkflowState, ...]
    completed_step_count: int
    total_step_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class WorkflowResult:
    """One typed result from workflow composition that never represents task execution."""

    decision: str
    reason_code: str
    reason: str
    request_id: str = ""
    execution_plan_id: str = ""
    workflow_definition: WorkflowDefinition | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def orchestrated(self) -> bool:
        """Return True only when a typed review workflow was composed."""

        return self.decision == "orchestrated" and self.workflow_definition is not None


class WorkflowEngineService:
    """Compose validated planning artifacts into a deterministic workflow without execution."""

    def orchestrate(self, request: WorkflowRequest) -> WorkflowResult:
        """Create one typed review workflow from a plan, analysis, and schedule."""

        if not isinstance(request, WorkflowRequest):
            return self._reject(
                reason_code="invalid_workflow_request",
                reason="Workflow orchestration requires one typed WorkflowRequest.",
            )
        if not isinstance(request.execution_plan, ExecutionPlan):
            return self._reject(
                reason_code="invalid_execution_plan",
                reason="Workflow orchestration requires one typed ExecutionPlan.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )
        if not isinstance(request.risk_analysis, RiskAnalysisResult):
            return self._reject(
                reason_code="invalid_risk_analysis_result",
                reason="Workflow orchestration requires one typed RiskAnalysisResult.",
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=request.execution_plan.execution_plan_id,
            )
        if not isinstance(request.execution_schedule, ExecutionSchedule):
            return self._reject(
                reason_code="invalid_execution_schedule",
                reason="Workflow orchestration requires one typed ExecutionSchedule.",
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=request.execution_plan.execution_plan_id,
            )

        plan = request.execution_plan
        risk_analysis = request.risk_analysis
        schedule = request.execution_schedule
        validation_error = self._validate_bindings(plan, risk_analysis, schedule)
        if validation_error is not None:
            reason_code, reason = validation_error
            return self._reject(
                reason_code=reason_code,
                reason=reason,
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=plan.execution_plan_id,
            )

        request_id = _normalized_text(request.request_id, max_chars=120) or stable_id(
            "workflow_request",
            plan.execution_plan_id,
            plan.plan_fingerprint,
            risk_analysis.request_id,
            schedule.schedule_fingerprint,
        )
        terminal_state = (
            WorkflowState.BLOCKED
            if risk_analysis.risk_level is RiskLevel.CRITICAL
            else WorkflowState.READY_FOR_HUMAN_REVIEW
        )
        state_transitions = (
            WorkflowState.PLANNED,
            WorkflowState.RISK_ANALYZED,
            WorkflowState.SCHEDULED,
            terminal_state,
        )
        workflow_fingerprint = stable_id(
            "workflow_fingerprint",
            {
                "execution_plan_id": plan.execution_plan_id,
                "plan_fingerprint": plan.plan_fingerprint,
                "approval_reference": plan.approval_reference,
                "risk_analysis_request_id": risk_analysis.request_id,
                "risk_level": risk_analysis.risk_level.value,
                "execution_schedule_id": schedule.execution_schedule_id,
                "schedule_fingerprint": schedule.schedule_fingerprint,
                "execution_order": schedule.execution_order,
                "state_transitions": tuple(state.value for state in state_transitions),
            },
        )
        workflow_id = stable_id("workflow", workflow_fingerprint)
        steps = (
            self._step(workflow_id, 1, "planning", WorkflowState.PLANNED, plan.execution_plan_id),
            self._step(workflow_id, 2, "risk_analysis", WorkflowState.RISK_ANALYZED, risk_analysis.request_id),
            self._step(workflow_id, 3, "scheduling", WorkflowState.SCHEDULED, schedule.execution_schedule_id),
        )
        definition = WorkflowDefinition(
            workflow_id=workflow_id,
            workflow_fingerprint=workflow_fingerprint,
            execution_plan_id=plan.execution_plan_id,
            plan_fingerprint=plan.plan_fingerprint,
            approval_reference=plan.approval_reference,
            risk_analysis_request_id=risk_analysis.request_id,
            risk_level=risk_analysis.risk_level,
            execution_schedule_id=schedule.execution_schedule_id,
            schedule_fingerprint=schedule.schedule_fingerprint,
            steps=steps,
            state=terminal_state,
            state_transitions=state_transitions,
            completed_step_count=len(steps),
            total_step_count=len(steps),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.workflow_engine",
                    "execution_schedule_order": schedule.execution_order,
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                    "request_metadata": request.metadata if isinstance(request.metadata, dict) else {},
                }
            ),
        )
        is_blocked = terminal_state is WorkflowState.BLOCKED
        return WorkflowResult(
            decision="orchestrated",
            reason_code=("workflow_blocked_by_critical_risk" if is_blocked else "workflow_ready_for_human_review"),
            reason=(
                "The planning workflow is blocked by a critical risk assessment and remains non-executing."
                if is_blocked
                else "The planning workflow is ready for human review and remains non-executing."
            ),
            request_id=request_id,
            execution_plan_id=plan.execution_plan_id,
            workflow_definition=definition,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.workflow_engine",
                    "workflow_state": terminal_state.value,
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )

    def _validate_bindings(
        self,
        plan: ExecutionPlan,
        risk_analysis: RiskAnalysisResult,
        schedule: ExecutionSchedule,
    ) -> tuple[str, str] | None:
        """Verify exact artifact bindings before composing any workflow state."""

        if _normalized_text(plan.status, max_chars=80).lower() != WorkflowState.PLANNED.value:
            return (
                "execution_plan_not_planned",
                "Workflow orchestration accepts only execution plans that remain in the planned state.",
            )
        if not risk_analysis.analyzed or not isinstance(risk_analysis.risk_level, RiskLevel):
            return (
                "risk_analysis_not_completed",
                "Workflow orchestration requires one completed typed risk analysis result.",
            )
        if risk_analysis.execution_plan_id != plan.execution_plan_id:
            return (
                "risk_analysis_plan_binding_mismatch",
                "The risk analysis result must bind to the exact execution plan identifier.",
            )
        if _normalized_text(schedule.status, max_chars=80).lower() != WorkflowState.SCHEDULED.value:
            return (
                "execution_schedule_not_scheduled",
                "Workflow orchestration requires one completed typed execution schedule.",
            )
        if (
            schedule.execution_plan_id != plan.execution_plan_id
            or schedule.plan_fingerprint != plan.plan_fingerprint
            or schedule.approval_reference != plan.approval_reference
        ):
            return (
                "execution_schedule_plan_binding_mismatch",
                "The execution schedule must preserve the exact plan, fingerprint, and approval-reference bindings.",
            )
        if not isinstance(schedule.policy, SchedulingPolicy) or schedule.policy.allow_parallel_tasks:
            return (
                "execution_schedule_policy_invalid",
                "Workflow orchestration requires one sequential typed execution schedule.",
            )
        if not isinstance(plan.tasks, tuple) or not plan.tasks or not all(isinstance(task, PlannedTask) for task in plan.tasks):
            return (
                "execution_plan_tasks_invalid",
                "Workflow orchestration requires one non-empty typed execution-plan task tuple.",
            )
        if not isinstance(schedule.scheduled_tasks, tuple) or not all(
            isinstance(task, ScheduledTask) for task in schedule.scheduled_tasks
        ):
            return (
                "execution_schedule_tasks_invalid",
                "Workflow orchestration requires one typed execution-schedule task tuple.",
            )

        plan_tasks_by_id = {task.task_id: task for task in plan.tasks}
        scheduled_tasks_by_id = {task.task_id: task for task in schedule.scheduled_tasks}
        scheduled_task_ids = tuple(task.task_id for task in schedule.scheduled_tasks)
        if (
            len(plan_tasks_by_id) != len(plan.tasks)
            or len(scheduled_tasks_by_id) != len(schedule.scheduled_tasks)
            or set(plan_tasks_by_id) != set(scheduled_tasks_by_id)
            or schedule.execution_order != scheduled_task_ids
            or tuple(task.sequence for task in schedule.scheduled_tasks) != tuple(range(1, len(schedule.scheduled_tasks) + 1))
        ):
            return (
                "execution_schedule_tasks_invalid",
                "Scheduled task identities, order, and sequences must exactly describe the execution plan tasks.",
            )

        schedule_positions = {task_id: sequence for sequence, task_id in enumerate(schedule.execution_order)}
        for task_id, plan_task in plan_tasks_by_id.items():
            scheduled_task = scheduled_tasks_by_id[task_id]
            if (
                scheduled_task.task_kind != plan_task.task_kind
                or scheduled_task.prerequisite_task_ids != plan_task.dependency_task_ids
                or scheduled_task.status != WorkflowState.SCHEDULED.value
                or any(
                    prerequisite_task_id not in schedule_positions
                    or schedule_positions[prerequisite_task_id] >= schedule_positions[task_id]
                    for prerequisite_task_id in plan_task.dependency_task_ids
                )
            ):
                return (
                    "execution_schedule_dependency_invalid",
                    "Scheduled task dependencies must match the plan and precede each dependent task.",
                )
        return None

    def _step(
        self,
        workflow_id: str,
        sequence: int,
        step_kind: str,
        state: WorkflowState,
        source_id: str,
    ) -> WorkflowStep:
        """Build one deterministic workflow progress record with no executable operation."""

        return WorkflowStep(
            workflow_step_id=stable_id("workflow_step", workflow_id, sequence, step_kind, source_id),
            step_kind=step_kind,
            sequence=sequence,
            state=state,
            source_id=source_id,
            metadata=sanitize_durable_mapping(
                {
                    "execution_performed": False,
                    "executor_invoked": False,
                }
            ),
        )

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        request_id: str = "",
        execution_plan_id: str = "",
    ) -> WorkflowResult:
        """Build one typed non-executing workflow rejection."""

        return WorkflowResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            request_id=compact_text(request_id, max_chars=120),
            execution_plan_id=compact_text(execution_plan_id, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.workflow_engine",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )


__all__ = [
    "WorkflowDefinition",
    "WorkflowEngineService",
    "WorkflowRequest",
    "WorkflowResult",
    "WorkflowState",
    "WorkflowStep",
]
