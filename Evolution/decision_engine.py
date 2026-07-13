"""Standalone typed readiness decisions for Phase 9 workflow artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .models import MutationApproval, compact_text, sanitize_durable_mapping, stable_id, utc_now
from .risk_analyzer import RiskAnalysisResult, RiskLevel
from .workflow_engine import WorkflowDefinition, WorkflowResult, WorkflowState


class DecisionState(str, Enum):
    """The bounded readiness states emitted by the standalone decision engine."""

    READY = "READY"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


def _normalized_text(value: Any, *, max_chars: int) -> str:
    """Normalize one bounded text field without interpreting arbitrary values as commands."""

    return compact_text(value if isinstance(value, str) else "", max_chars=max_chars).strip()


def _normalized_timestamp(value: Any) -> datetime | None:
    """Normalize one evaluation timestamp to UTC without accepting arbitrary values."""

    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True, frozen=True)
class DecisionRequest:
    """One typed request to assess a workflow's readiness without running any task."""

    workflow_result: WorkflowResult
    risk_analysis: RiskAnalysisResult
    mutation_approval: MutationApproval | None = None
    request_id: str = ""
    actor: str = "narvis"
    evaluated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DecisionReason:
    """One typed reason explaining a deterministic readiness decision."""

    reason_id: str
    code: str
    state: DecisionState
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExecutionDecision:
    """One review-only readiness decision; it never enables runtime execution."""

    execution_decision_id: str
    decision_fingerprint: str
    state: DecisionState
    workflow_id: str
    workflow_fingerprint: str
    execution_plan_id: str
    plan_fingerprint: str
    approval_reference: str
    risk_level: RiskLevel
    reasons: tuple[DecisionReason, ...]
    mutation_approval_id: str = ""
    mutation_approval_fingerprint: str = ""
    requires_human_approval: bool = True
    execution_allowed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DecisionResult:
    """One typed result from readiness assessment that never represents task execution."""

    state: DecisionState
    reason_code: str
    reason: str
    request_id: str = ""
    execution_plan_id: str = ""
    execution_decision: ExecutionDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        """Return True only when a typed readiness decision was created."""

        return self.execution_decision is not None


class DecisionEngineService:
    """Evaluate workflow readiness without execution, runtime access, or approval mutation."""

    def list_decision_states(self) -> tuple[DecisionState, ...]:
        """Return all bounded decision states in deterministic order."""

        return tuple(DecisionState)

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Produce one typed readiness decision from existing workflow and risk artifacts."""

        if not isinstance(request, DecisionRequest):
            return self._reject(
                reason_code="invalid_decision_request",
                reason="Readiness evaluation requires one typed DecisionRequest.",
            )
        if not isinstance(request.workflow_result, WorkflowResult):
            return self._reject(
                reason_code="invalid_workflow_result",
                reason="Readiness evaluation requires one typed WorkflowResult.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )
        if not isinstance(request.risk_analysis, RiskAnalysisResult):
            return self._reject(
                reason_code="invalid_risk_analysis_result",
                reason="Readiness evaluation requires one typed RiskAnalysisResult.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )
        if request.mutation_approval is not None and not isinstance(request.mutation_approval, MutationApproval):
            return self._reject(
                reason_code="invalid_mutation_approval",
                reason="Readiness evaluation accepts only a typed MutationApproval when approval is supplied.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )

        evaluated_at = self._evaluation_time(request.evaluated_at)
        if evaluated_at is None:
            return self._reject(
                reason_code="invalid_evaluation_timestamp",
                reason="Readiness evaluation accepts only an aware or naive datetime evaluation timestamp.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )

        workflow, validation_error = self._validate_workflow_and_risk(
            request.workflow_result,
            request.risk_analysis,
        )
        if validation_error is not None:
            reason_code, reason = validation_error
            return self._reject(
                reason_code=reason_code,
                reason=reason,
                request_id=_normalized_text(request.request_id, max_chars=120),
                execution_plan_id=workflow.execution_plan_id if workflow is not None else "",
            )
        assert workflow is not None

        request_id = _normalized_text(request.request_id, max_chars=120) or stable_id(
            "decision_request",
            workflow.workflow_id,
            workflow.workflow_fingerprint,
            request.risk_analysis.request_id,
            self._approval_identity(request.mutation_approval),
        )
        state, reason_code, reason = self._decision_state(
            workflow,
            request.risk_analysis,
            request.mutation_approval,
            evaluated_at,
        )
        return self._result(
            state=state,
            reason_code=reason_code,
            reason=reason,
            request_id=request_id,
            workflow=workflow,
            mutation_approval=request.mutation_approval,
            request_metadata=request.metadata,
        )

    def _evaluation_time(self, value: datetime | None) -> datetime | None:
        """Return the supplied normalized time or the current UTC time for expiry evaluation."""

        if value is None:
            return utc_now()
        return _normalized_timestamp(value)

    def _validate_workflow_and_risk(
        self,
        workflow_result: WorkflowResult,
        risk_analysis: RiskAnalysisResult,
    ) -> tuple[WorkflowDefinition | None, tuple[str, str] | None]:
        """Validate exact workflow and analysis bindings before evaluating approval readiness."""

        if not workflow_result.orchestrated or not isinstance(workflow_result.workflow_definition, WorkflowDefinition):
            return None, (
                "workflow_not_orchestrated",
                "Readiness evaluation requires one completed typed workflow result.",
            )
        workflow = workflow_result.workflow_definition
        if (
            not _normalized_text(workflow.workflow_id, max_chars=120)
            or not _normalized_text(workflow.workflow_fingerprint, max_chars=120)
            or not _normalized_text(workflow.execution_plan_id, max_chars=120)
            or not _normalized_text(workflow.plan_fingerprint, max_chars=120)
            or workflow_result.execution_plan_id != workflow.execution_plan_id
        ):
            return workflow, (
                "workflow_binding_invalid",
                "The workflow result must preserve complete workflow and execution-plan bindings.",
            )
        if (
            not isinstance(workflow.state, WorkflowState)
            or not isinstance(workflow.risk_level, RiskLevel)
            or not isinstance(workflow.state_transitions, tuple)
            or not workflow.state_transitions
            or workflow.state_transitions[-1] is not workflow.state
            or workflow.completed_step_count != len(workflow.steps)
            or workflow.total_step_count != len(workflow.steps)
        ):
            return workflow, (
                "workflow_state_invalid",
                "The workflow must contain one complete, internally consistent typed progress state.",
            )
        if not risk_analysis.analyzed or not isinstance(risk_analysis.risk_level, RiskLevel):
            return workflow, (
                "risk_analysis_not_completed",
                "Readiness evaluation requires one completed typed risk analysis result.",
            )
        if (
            risk_analysis.execution_plan_id != workflow.execution_plan_id
            or risk_analysis.request_id != workflow.risk_analysis_request_id
            or risk_analysis.risk_level is not workflow.risk_level
        ):
            return workflow, (
                "risk_analysis_workflow_binding_mismatch",
                "The risk analysis result must exactly match the workflow plan, analysis request, and risk level.",
            )
        return workflow, None

    def _decision_state(
        self,
        workflow: WorkflowDefinition,
        risk_analysis: RiskAnalysisResult,
        mutation_approval: MutationApproval | None,
        evaluated_at: datetime,
    ) -> tuple[DecisionState, str, str]:
        """Apply the bounded readiness policy without authorizing or executing any task."""

        if workflow.state is WorkflowState.BLOCKED or risk_analysis.risk_level is RiskLevel.CRITICAL:
            return (
                DecisionState.BLOCKED,
                "workflow_or_risk_blocked",
                "The workflow remains blocked by its deterministic workflow state or critical risk assessment.",
            )
        if workflow.state is not WorkflowState.READY_FOR_HUMAN_REVIEW:
            return (
                DecisionState.REJECTED,
                "workflow_not_ready_for_human_review",
                "Only workflows in the ready-for-human-review state can receive a readiness decision.",
            )
        if mutation_approval is None:
            return (
                DecisionState.WAITING_FOR_APPROVAL,
                "mutation_approval_required",
                "A matching explicit human MutationApproval is required before readiness can be recorded.",
            )

        approval_error = self._validate_mutation_approval(mutation_approval, workflow, evaluated_at)
        if approval_error is None:
            return (
                DecisionState.READY,
                "matching_mutation_approval_recorded",
                "A current matching human MutationApproval is present; this remains a non-executing readiness record.",
            )
        state, reason_code, reason = approval_error
        return state, reason_code, reason

    def _validate_mutation_approval(
        self,
        approval: MutationApproval,
        workflow: WorkflowDefinition,
        evaluated_at: datetime,
    ) -> tuple[DecisionState, str, str] | None:
        """Validate only immutable approval facts needed for workflow readiness, without changing approvals."""

        decision = _normalized_text(approval.decision, max_chars=80).lower()
        if decision in {"", "pending"}:
            return (
                DecisionState.WAITING_FOR_APPROVAL,
                "mutation_approval_pending",
                "The supplied MutationApproval is still pending explicit human approval.",
            )
        if decision != "approved":
            return (
                DecisionState.REJECTED,
                "mutation_approval_not_approved",
                "The supplied MutationApproval does not record an explicit approved decision.",
            )
        if _normalized_text(approval.mode, max_chars=80).lower() != "apply":
            return (
                DecisionState.REJECTED,
                "mutation_approval_mode_mismatch",
                "Readiness decisions require one explicit apply-mode MutationApproval.",
            )
        if (
            not _normalized_text(approval.mutation_approval_id, max_chars=120)
            or not _normalized_text(approval.mutation_approval_fingerprint, max_chars=120)
            or not _normalized_text(approval.approval_decision_id, max_chars=120)
            or not _normalized_text(approval.proposal_id, max_chars=120)
            or not approval.mutation_target_ids
        ):
            return (
                DecisionState.REJECTED,
                "mutation_approval_binding_invalid",
                "The supplied MutationApproval must contain complete immutable approval bindings.",
            )
        if workflow.approval_reference:
            if approval.mutation_approval_id != workflow.approval_reference:
                return (
                    DecisionState.REJECTED,
                    "mutation_approval_workflow_binding_mismatch",
                    "The MutationApproval must match the workflow's exact approval-reference binding.",
                )
        elif approval.plan_id != workflow.execution_plan_id or approval.plan_fingerprint != workflow.plan_fingerprint:
            return (
                DecisionState.REJECTED,
                "mutation_approval_plan_binding_mismatch",
                "The MutationApproval must bind to the exact workflow execution-plan identifier and fingerprint.",
            )
        expires_at = _normalized_timestamp(approval.expires_at)
        if expires_at is None:
            return (
                DecisionState.REJECTED,
                "mutation_approval_expiry_invalid",
                "The MutationApproval must contain one valid expiry timestamp.",
            )
        if expires_at <= evaluated_at:
            return (
                DecisionState.WAITING_FOR_APPROVAL,
                "mutation_approval_expired",
                "The supplied MutationApproval has expired and requires a fresh explicit human approval.",
            )
        return None

    def _result(
        self,
        *,
        state: DecisionState,
        reason_code: str,
        reason: str,
        request_id: str,
        workflow: WorkflowDefinition,
        mutation_approval: MutationApproval | None,
        request_metadata: dict[str, Any],
    ) -> DecisionResult:
        """Build one deterministic typed decision that remains incapable of execution."""

        reason_record = DecisionReason(
            reason_id=stable_id("decision_reason", workflow.workflow_fingerprint, state.value, reason_code),
            code=reason_code,
            state=state,
            description=reason,
            metadata=sanitize_durable_mapping(
                {
                    "execution_performed": False,
                    "executor_invoked": False,
                }
            ),
        )
        approval_id = mutation_approval.mutation_approval_id if mutation_approval is not None else ""
        approval_fingerprint = (
            mutation_approval.mutation_approval_fingerprint if mutation_approval is not None else ""
        )
        decision_fingerprint = stable_id(
            "execution_decision_fingerprint",
            {
                "workflow_id": workflow.workflow_id,
                "workflow_fingerprint": workflow.workflow_fingerprint,
                "execution_plan_id": workflow.execution_plan_id,
                "plan_fingerprint": workflow.plan_fingerprint,
                "risk_level": workflow.risk_level.value,
                "state": state.value,
                "reason_code": reason_code,
                "mutation_approval_id": approval_id,
                "mutation_approval_fingerprint": approval_fingerprint,
            },
        )
        execution_decision = ExecutionDecision(
            execution_decision_id=stable_id("execution_decision", decision_fingerprint),
            decision_fingerprint=decision_fingerprint,
            state=state,
            workflow_id=workflow.workflow_id,
            workflow_fingerprint=workflow.workflow_fingerprint,
            execution_plan_id=workflow.execution_plan_id,
            plan_fingerprint=workflow.plan_fingerprint,
            approval_reference=workflow.approval_reference,
            risk_level=workflow.risk_level,
            reasons=(reason_record,),
            mutation_approval_id=approval_id,
            mutation_approval_fingerprint=approval_fingerprint,
            requires_human_approval=state is not DecisionState.READY,
            execution_allowed=False,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.decision_engine",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )
        return DecisionResult(
            state=state,
            reason_code=reason_code,
            reason=reason,
            request_id=request_id,
            execution_plan_id=workflow.execution_plan_id,
            execution_decision=execution_decision,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.decision_engine",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                    "request_metadata": request_metadata if isinstance(request_metadata, dict) else {},
                }
            ),
        )

    def _approval_identity(self, approval: MutationApproval | None) -> tuple[str, str]:
        """Return the immutable approval identity used for deterministic request identity."""

        if approval is None:
            return ("", "")
        return (approval.mutation_approval_id, approval.mutation_approval_fingerprint)

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        request_id: str = "",
        execution_plan_id: str = "",
    ) -> DecisionResult:
        """Build one typed fail-closed decision rejection without task execution."""

        return DecisionResult(
            state=DecisionState.REJECTED,
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            request_id=compact_text(request_id, max_chars=120),
            execution_plan_id=compact_text(execution_plan_id, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.decision_engine",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )


__all__ = [
    "DecisionEngineService",
    "DecisionReason",
    "DecisionRequest",
    "DecisionResult",
    "DecisionState",
    "ExecutionDecision",
]
