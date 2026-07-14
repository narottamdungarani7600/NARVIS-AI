"""Immutable models for the safe execution coordination lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from Core.execution.models import ExecutionRequest, PermissionLevel, RiskLevel
from Execution.preview.models import (
    ActionPreview,
    ExecutionPreview,
    ExecutionReadiness,
    PreviewRiskAnalysis,
)
from Execution.session.models import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalToken,
    ExecutionSession,
    immutable_mapping,
    new_id,
    utc_now,
)


class CoordinatorState(str, Enum):
    """Immutable states supported by the safe execution coordinator."""

    CREATED = "created"
    VALIDATED = "validated"
    PREVIEW_READY = "preview_ready"
    RISK_ANALYZED = "risk_analyzed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    APPROVED = "approved"
    READY = "ready"
    CANCELLED = "cancelled"
    FAILED = "failed"


ExecutionState = CoordinatorState


def _require_text(
    name: str,
    value: object,
    *,
    maximum: int = 256,
    allow_empty: bool = False,
) -> None:
    """Require normalized bounded text."""

    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        value != value.strip()
        or len(value) > maximum
        or (not value and not allow_empty)
    ):
        raise ValueError(
            f"{name} must be normalized text of at most {maximum} characters"
        )


def _require_time(name: str, value: object) -> None:
    """Require a timezone-aware timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


@dataclass(slots=True, frozen=True)
class StateTransition:
    """One immutable coordinator state transition."""

    to_state: CoordinatorState
    reason: str
    transitioned_at: datetime = field(default_factory=utc_now)
    from_state: CoordinatorState | None = None

    def __post_init__(self) -> None:
        """Validate typed states, reason, and timestamp."""

        if self.from_state is not None and not isinstance(
            self.from_state, CoordinatorState
        ):
            raise TypeError("from_state must be a CoordinatorState or None")
        if not isinstance(self.to_state, CoordinatorState):
            raise TypeError("to_state must be a CoordinatorState")
        _require_text("reason", self.reason, maximum=1024)
        _require_time("transitioned_at", self.transitioned_at)


@dataclass(slots=True, frozen=True)
class ValidationReport:
    """Immutable result of coordinator requirement validation."""

    valid: bool
    missing_requirements: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    validated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Validate report consistency and immutable sequences."""

        if not isinstance(self.valid, bool):
            raise TypeError("valid must be a bool")
        missing = tuple(self.missing_requirements)
        errors = tuple(self.errors)
        if any(not isinstance(item, str) or not item for item in (*missing, *errors)):
            raise ValueError("validation messages must be non-empty strings")
        if self.valid and (missing or errors):
            raise ValueError(
                "valid reports cannot contain missing requirements or errors"
            )
        if not self.valid and not (missing or errors):
            raise ValueError("invalid reports must explain the validation failure")
        object.__setattr__(self, "missing_requirements", missing)
        object.__setattr__(self, "errors", errors)
        _require_time("validated_at", self.validated_at)

    @property
    def successful(self) -> bool:
        """Return whether validation passed."""

        return self.valid


@dataclass(slots=True, frozen=True)
class ExecutionReadinessReport:
    """Complete readiness facts for one coordinated preview."""

    coordination_id: str
    missing_requirements: tuple[str, ...]
    approval_status: ApprovalStatus | None
    risk_level: RiskLevel | None
    estimated_duration: timedelta
    rollback_available: bool
    execution_readiness_score: float
    readiness: ExecutionReadiness
    required_permissions: tuple[PermissionLevel, ...] = ()
    generated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Validate immutable readiness facts and bounded scoring."""

        _require_text("coordination_id", self.coordination_id, maximum=128)
        missing = tuple(self.missing_requirements)
        if any(not isinstance(item, str) or not item for item in missing):
            raise ValueError("missing_requirements must contain non-empty strings")
        object.__setattr__(self, "missing_requirements", missing)
        if self.approval_status is not None and not isinstance(
            self.approval_status, ApprovalStatus
        ):
            raise TypeError("approval_status must be an ApprovalStatus or None")
        if self.risk_level is not None and not isinstance(self.risk_level, RiskLevel):
            raise TypeError("risk_level must be a RiskLevel or None")
        if not isinstance(self.estimated_duration, timedelta):
            raise TypeError("estimated_duration must be a timedelta")
        if self.estimated_duration < timedelta(0):
            raise ValueError("estimated_duration cannot be negative")
        if not isinstance(self.rollback_available, bool):
            raise TypeError("rollback_available must be a bool")
        if isinstance(self.execution_readiness_score, bool) or not isinstance(
            self.execution_readiness_score, (int, float)
        ):
            raise TypeError("execution_readiness_score must be numeric")
        score = float(self.execution_readiness_score)
        if score < 0 or score > 100 or score != score:
            raise ValueError("execution_readiness_score must be between 0 and 100")
        object.__setattr__(self, "execution_readiness_score", score)
        if not isinstance(self.readiness, ExecutionReadiness):
            raise TypeError("readiness must be an ExecutionReadiness")
        permissions = tuple(self.required_permissions)
        if any(not isinstance(item, PermissionLevel) for item in permissions):
            raise TypeError("required_permissions must contain PermissionLevel members")
        if len(set(permissions)) != len(permissions):
            raise ValueError("required_permissions cannot contain duplicates")
        object.__setattr__(self, "required_permissions", permissions)
        _require_time("generated_at", self.generated_at)

    @property
    def ready(self) -> bool:
        """Return whether no requirements remain and readiness is READY."""

        return (
            not self.missing_requirements and self.readiness is ExecutionReadiness.READY
        )

    @property
    def score(self) -> float:
        """Return the execution readiness score using concise terminology."""

        return self.execution_readiness_score


ReadinessReport = ExecutionReadinessReport


@dataclass(slots=True, frozen=True)
class SafeExecutionPlan:
    """Immutable planning artifact produced only after readiness passes."""

    coordination_id: str
    request_id: str
    preview_id: str
    session_id: str
    actions: tuple[ActionPreview, ...]
    required_permissions: tuple[PermissionLevel, ...]
    estimated_duration: timedelta
    rollback_available: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)
    plan_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)
    dry_run: bool = True
    ready: bool = True
    executed: bool = False
    dispatcher_invoked: bool = False

    def __post_init__(self) -> None:
        """Validate plan bindings and prohibit execution claims."""

        for name, value in (
            ("coordination_id", self.coordination_id),
            ("request_id", self.request_id),
            ("preview_id", self.preview_id),
            ("session_id", self.session_id),
            ("plan_id", self.plan_id),
        ):
            _require_text(name, value, maximum=128)
        actions = tuple(self.actions)
        if not actions or any(not isinstance(item, ActionPreview) for item in actions):
            raise ValueError("execution plans require ActionPreview instances")
        if tuple(action.order for action in actions) != tuple(
            range(1, len(actions) + 1)
        ):
            raise ValueError("plan actions must remain contiguously ordered")
        object.__setattr__(self, "actions", actions)
        permissions = tuple(self.required_permissions)
        if any(not isinstance(item, PermissionLevel) for item in permissions):
            raise TypeError("required_permissions must contain PermissionLevel members")
        object.__setattr__(self, "required_permissions", permissions)
        if not isinstance(self.estimated_duration, timedelta):
            raise TypeError("estimated_duration must be a timedelta")
        if self.estimated_duration < timedelta(0):
            raise ValueError("estimated_duration cannot be negative")
        total_duration = sum(
            (action.estimated_duration for action in actions),
            start=timedelta(0),
        )
        if self.estimated_duration != total_duration:
            raise ValueError("plan duration must match the ordered actions")
        action_permissions: list[PermissionLevel] = []
        for action in actions:
            if action.required_permission not in action_permissions:
                action_permissions.append(action.required_permission)
        if permissions != tuple(action_permissions):
            raise ValueError("plan permissions must match the ordered actions")
        if not isinstance(self.rollback_available, bool):
            raise TypeError("rollback_available must be a bool")
        if self.rollback_available is not all(
            action.rollback_available for action in actions
        ):
            raise ValueError("plan rollback availability must match the actions")
        _require_time("created_at", self.created_at)
        if self.dry_run is not True or self.ready is not True:
            raise ValueError("safe execution plans must be ready dry runs")
        if self.executed is not False or self.dispatcher_invoked is not False:
            raise ValueError("safe execution plans cannot claim execution or dispatch")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def ordered_actions(self) -> tuple[ActionPreview, ...]:
        """Return plan actions in validated order."""

        return self.actions


ExecutionPlan = SafeExecutionPlan


ApprovalRecord = ApprovalRequest | ApprovalResponse | ApprovalStatus | ApprovalToken


@dataclass(slots=True, frozen=True)
class ExecutionCoordination:
    """Immutable snapshot of the complete safe coordination lifecycle."""

    coordination_id: str
    state: CoordinatorState
    request: ExecutionRequest | None
    session: ExecutionSession | None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    preview: ExecutionPreview | None = None
    risk_analysis: PreviewRiskAnalysis | None = None
    approval: ApprovalRecord | None = None
    validation_report: ValidationReport | None = None
    readiness_report: ExecutionReadinessReport | None = None
    plan: SafeExecutionPlan | None = None
    transitions: tuple[StateTransition, ...] = ()
    failure_reason: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    dry_run: bool = True
    executed: bool = False
    dispatcher_invoked: bool = False

    def __post_init__(self) -> None:
        """Validate all optional typed lifecycle bindings."""

        _require_text("coordination_id", self.coordination_id, maximum=128)
        if not isinstance(self.state, CoordinatorState):
            raise TypeError("state must be a CoordinatorState")
        if self.request is not None and not isinstance(self.request, ExecutionRequest):
            raise TypeError("request must be an ExecutionRequest or None")
        if self.session is not None and not isinstance(self.session, ExecutionSession):
            raise TypeError("session must be an ExecutionSession or None")
        if self.preview is not None and not isinstance(self.preview, ExecutionPreview):
            raise TypeError("preview must be an ExecutionPreview or None")
        if self.risk_analysis is not None and not isinstance(
            self.risk_analysis, PreviewRiskAnalysis
        ):
            raise TypeError("risk_analysis must be PreviewRiskAnalysis or None")
        if self.approval is not None and not isinstance(
            self.approval,
            (ApprovalRequest, ApprovalResponse, ApprovalStatus, ApprovalToken),
        ):
            raise TypeError("approval must use an existing approval model")
        if self.validation_report is not None and not isinstance(
            self.validation_report, ValidationReport
        ):
            raise TypeError("validation_report must be ValidationReport or None")
        if self.readiness_report is not None and not isinstance(
            self.readiness_report, ExecutionReadinessReport
        ):
            raise TypeError("readiness_report must be ExecutionReadinessReport or None")
        if self.plan is not None and not isinstance(self.plan, SafeExecutionPlan):
            raise TypeError("plan must be SafeExecutionPlan or None")
        transitions = tuple(self.transitions)
        if any(not isinstance(item, StateTransition) for item in transitions):
            raise TypeError("transitions must contain StateTransition instances")
        object.__setattr__(self, "transitions", transitions)
        if not isinstance(self.failure_reason, str) or len(self.failure_reason) > 2048:
            raise ValueError(
                "failure_reason must be a string of at most 2048 characters"
            )
        _require_time("created_at", self.created_at)
        _require_time("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.dry_run is not True:
            raise ValueError("execution coordination must remain a dry run")
        if self.executed is not False or self.dispatcher_invoked is not False:
            raise ValueError(
                "execution coordination cannot claim execution or dispatch"
            )
        if self.preview is not None and self.request is not None:
            if self.preview.request_id != self.request.request_id:
                raise ValueError("preview must be bound to the coordination request")
        if self.risk_analysis is not None and self.preview is not None:
            if self.risk_analysis.preview_id != self.preview.preview_id:
                raise ValueError(
                    "risk analysis must be bound to the coordination preview"
                )
        if self.plan is not None and self.state not in {
            CoordinatorState.READY,
            CoordinatorState.CANCELLED,
        }:
            raise ValueError(
                "only READY or subsequently CANCELLED records may contain a plan"
            )
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def request_id(self) -> str:
        """Return the execution request identifier when available."""

        return self.request.request_id if self.request is not None else ""

    @property
    def session_id(self) -> str:
        """Return the execution session identifier when available."""

        return self.session.session_id if self.session is not None else ""

    @property
    def ready(self) -> bool:
        """Return whether coordination reached READY with a safe plan."""

        return self.state is CoordinatorState.READY and self.plan is not None

    @property
    def waiting_for_approval(self) -> bool:
        """Return whether coordination paused for an approval decision."""

        return self.state is CoordinatorState.WAITING_FOR_APPROVAL

    @property
    def cancelled(self) -> bool:
        """Return whether coordination was cancelled."""

        return self.state is CoordinatorState.CANCELLED

    @property
    def failed(self) -> bool:
        """Return whether coordination failed closed."""

        return self.state is CoordinatorState.FAILED


CoordinatorResult = ExecutionCoordination
CoordinationRecord = ExecutionCoordination


__all__ = [
    "ApprovalRecord",
    "CoordinationRecord",
    "CoordinatorResult",
    "CoordinatorState",
    "ExecutionCoordination",
    "ExecutionPlan",
    "ExecutionReadinessReport",
    "ExecutionState",
    "ReadinessReport",
    "SafeExecutionPlan",
    "StateTransition",
    "ValidationReport",
]
