"""Immutable typed models for execution dry runs and action previews."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from Core.execution.models import (
    ExecutionRequest,
    PermissionLevel,
    RiskLevel,
)
from Execution.session.models import (
    ApprovalStatus,
    immutable_mapping,
    new_id,
    utc_now,
)


class PreviewStatus(str, Enum):
    """Lifecycle states for a retained execution preview."""

    READY = "ready"
    UPDATED = "updated"
    CANCELLED = "cancelled"


class ExecutionReadiness(str, Enum):
    """Readiness outcomes reported by an execution summary."""

    READY = "ready"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


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


def _require_score(name: str, value: object) -> float:
    """Require a finite numeric score in the inclusive 0-100 range."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    score = float(value)
    if score < 0.0 or score > 100.0 or score != score:
        raise ValueError(f"{name} must be between 0 and 100")
    return score


@dataclass(slots=True, frozen=True)
class ActionPreview:
    """One ordered, inert action shown in a dry-run preview."""

    action: str
    order: int
    description: str = ""
    estimated_duration: timedelta = timedelta(seconds=1)
    required_permission: PermissionLevel = PermissionLevel.STANDARD
    rollback_available: bool = False
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        """Validate the action and recursively detach its data mappings."""

        _require_text("action_id", self.action_id, maximum=128)
        _require_text("action", self.action, maximum=256)
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise TypeError("order must be an integer")
        if self.order < 1:
            raise ValueError("order must be at least 1")
        if not isinstance(self.description, str) or len(self.description) > 2048:
            raise ValueError("description must be a string of at most 2048 characters")
        if not isinstance(self.estimated_duration, timedelta):
            raise TypeError("estimated_duration must be a timedelta")
        if self.estimated_duration < timedelta(0):
            raise ValueError("estimated_duration cannot be negative")
        if not isinstance(self.required_permission, PermissionLevel):
            raise TypeError("required_permission must be a PermissionLevel")
        if not isinstance(self.rollback_available, bool):
            raise TypeError("rollback_available must be a bool")
        object.__setattr__(self, "parameters", immutable_mapping(self.parameters))
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def estimated_duration_seconds(self) -> float:
        """Return the estimated duration in seconds."""

        return self.estimated_duration.total_seconds()


PreviewAction = ActionPreview


@dataclass(slots=True, frozen=True)
class RiskFactor:
    """One deterministic contribution to a preview risk score."""

    code: str
    score: float
    description: str
    level: RiskLevel

    def __post_init__(self) -> None:
        """Validate a bounded, explainable scoring factor."""

        _require_text("code", self.code, maximum=128)
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("description must be a non-empty string")
        if not isinstance(self.level, RiskLevel):
            raise TypeError("level must be a RiskLevel")
        object.__setattr__(self, "score", _require_score("score", self.score))


@dataclass(slots=True, frozen=True)
class PreviewRiskAnalysis:
    """Scoring-only risk analysis for one immutable preview."""

    preview_id: str
    request_id: str
    score: float
    level: RiskLevel
    factors: tuple[RiskFactor, ...] = ()
    analyzed_at: datetime = field(default_factory=utc_now)
    scoring_only: bool = True

    def __post_init__(self) -> None:
        """Validate scoring facts and prohibit operational outcomes."""

        _require_text("preview_id", self.preview_id, maximum=128)
        _require_text("request_id", self.request_id, maximum=128)
        if not isinstance(self.level, RiskLevel):
            raise TypeError("level must be a RiskLevel")
        object.__setattr__(self, "score", _require_score("score", self.score))
        expected_level = _risk_level_for_score(self.score)
        if self.level is not expected_level:
            raise ValueError("risk level must match the bounded risk score")
        factors = tuple(self.factors)
        if any(not isinstance(factor, RiskFactor) for factor in factors):
            raise TypeError("factors must contain RiskFactor instances")
        object.__setattr__(self, "factors", factors)
        _require_time("analyzed_at", self.analyzed_at)
        if self.scoring_only is not True:
            raise ValueError("preview risk analysis must remain scoring-only")

    @property
    def risk_level(self) -> RiskLevel:
        """Return the risk level using assessment terminology."""

        return self.level


RiskAnalysis = PreviewRiskAnalysis


@dataclass(slots=True, frozen=True)
class ExecutionSummary:
    """Aggregate action, duration, approval, rollback, and readiness facts."""

    action_count: int
    estimated_duration: timedelta
    approval_required: bool
    rollback_available: bool
    readiness: ExecutionReadiness
    required_permissions: tuple[PermissionLevel, ...] = ()
    generated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Validate immutable summary facts."""

        if isinstance(self.action_count, bool) or not isinstance(
            self.action_count, int
        ):
            raise TypeError("action_count must be an integer")
        if self.action_count < 0:
            raise ValueError("action_count cannot be negative")
        if not isinstance(self.estimated_duration, timedelta):
            raise TypeError("estimated_duration must be a timedelta")
        if self.estimated_duration < timedelta(0):
            raise ValueError("estimated_duration cannot be negative")
        if not isinstance(self.approval_required, bool):
            raise TypeError("approval_required must be a bool")
        if not isinstance(self.rollback_available, bool):
            raise TypeError("rollback_available must be a bool")
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
    def estimated_duration_seconds(self) -> float:
        """Return the total duration estimate in seconds."""

        return self.estimated_duration.total_seconds()

    @property
    def execution_readiness(self) -> ExecutionReadiness:
        """Return readiness using explicit summary terminology."""

        return self.readiness

    @property
    def execution_ready(self) -> bool:
        """Return whether the preview is ready without further approval."""

        return self.readiness is ExecutionReadiness.READY


@dataclass(slots=True, frozen=True)
class ExecutionPreview:
    """Complete immutable dry-run representation of an execution request."""

    execution_request: ExecutionRequest
    actions: tuple[ActionPreview, ...]
    summary: ExecutionSummary
    risk_analysis: PreviewRiskAnalysis
    preview_id: str = field(default_factory=new_id)
    session_id: str = ""
    approval_status: ApprovalStatus | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    status: PreviewStatus = PreviewStatus.READY
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    executed: bool = False
    dispatcher_invoked: bool = False

    def __post_init__(self) -> None:
        """Validate exact bindings, ordering, and the no-execution invariant."""

        if not isinstance(self.execution_request, ExecutionRequest):
            raise TypeError("execution_request must be an ExecutionRequest")
        _require_text("preview_id", self.preview_id, maximum=128)
        _require_text(
            "session_id",
            self.session_id,
            maximum=128,
            allow_empty=True,
        )
        actions = tuple(self.actions)
        if not actions:
            raise ValueError("execution previews require at least one action")
        if any(not isinstance(action, ActionPreview) for action in actions):
            raise TypeError("actions must contain ActionPreview instances")
        if tuple(action.order for action in actions) != tuple(
            range(1, len(actions) + 1)
        ):
            raise ValueError("actions must be ordered contiguously starting at 1")
        action_ids = tuple(action.action_id for action in actions)
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action identifiers must be unique")
        if not isinstance(self.summary, ExecutionSummary):
            raise TypeError("summary must be an ExecutionSummary")
        if not isinstance(self.risk_analysis, PreviewRiskAnalysis):
            raise TypeError("risk_analysis must be a PreviewRiskAnalysis")
        if self.summary.action_count != len(actions):
            raise ValueError("summary action_count must match the ordered actions")
        total_duration = sum(
            (action.estimated_duration for action in actions),
            start=timedelta(0),
        )
        if self.summary.estimated_duration != total_duration:
            raise ValueError("summary duration must match the ordered actions")
        permissions: list[PermissionLevel] = []
        for action in actions:
            if action.required_permission not in permissions:
                permissions.append(action.required_permission)
        if self.summary.required_permissions != tuple(permissions):
            raise ValueError("summary permissions must match the ordered actions")
        rollback_available = all(action.rollback_available for action in actions)
        if self.summary.rollback_available is not rollback_available:
            raise ValueError("summary rollback availability must match the actions")
        if self.risk_analysis.preview_id != self.preview_id:
            raise ValueError("risk analysis must be bound to the preview")
        if self.risk_analysis.request_id != self.execution_request.request_id:
            raise ValueError("risk analysis must be bound to the execution request")
        if self.approval_status is not None and not isinstance(
            self.approval_status, ApprovalStatus
        ):
            raise TypeError("approval_status must be an ApprovalStatus or None")
        if not isinstance(self.status, PreviewStatus):
            raise TypeError("status must be a PreviewStatus")
        if (
            self.status is PreviewStatus.CANCELLED
            and self.summary.readiness is not ExecutionReadiness.CANCELLED
        ):
            raise ValueError("cancelled previews require cancelled readiness")
        _require_time("created_at", self.created_at)
        _require_time("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.dry_run is not True:
            raise ValueError("execution previews must remain in dry-run mode")
        if self.executed is not False or self.dispatcher_invoked is not False:
            raise ValueError("execution previews cannot report execution or dispatch")

        request = replace(
            self.execution_request,
            parameters=immutable_mapping(self.execution_request.parameters),
            metadata=immutable_mapping(self.execution_request.metadata),
        )
        object.__setattr__(self, "execution_request", request)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def request_id(self) -> str:
        """Return the source execution request identifier."""

        return self.execution_request.request_id

    @property
    def ordered_actions(self) -> tuple[ActionPreview, ...]:
        """Return actions in their validated preview order."""

        return self.actions

    @property
    def execution_summary(self) -> ExecutionSummary:
        """Return the generated summary."""

        return self.summary

    @property
    def estimated_duration(self) -> timedelta:
        """Return the aggregate duration estimate."""

        return self.summary.estimated_duration

    @property
    def required_permissions(self) -> tuple[PermissionLevel, ...]:
        """Return all distinct required permissions in action order."""

        return self.summary.required_permissions

    @property
    def cancelled(self) -> bool:
        """Return whether the preview lifecycle was cancelled."""

        return self.status is PreviewStatus.CANCELLED


def _risk_level_for_score(score: float) -> RiskLevel:
    """Return the required risk level for one validated score."""

    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


__all__ = [
    "ActionPreview",
    "ExecutionPreview",
    "ExecutionReadiness",
    "ExecutionSummary",
    "PermissionLevel",
    "PreviewAction",
    "PreviewRiskAnalysis",
    "PreviewStatus",
    "RiskAnalysis",
    "RiskFactor",
    "RiskLevel",
]
