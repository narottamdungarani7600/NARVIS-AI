"""Execution preview summary generation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from Core.execution.models import PermissionLevel, RiskLevel
from Execution.session.models import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalToken,
    utc_now,
)

from .exceptions import SummaryValidationError
from .models import (
    ActionPreview,
    ExecutionReadiness,
    ExecutionSummary,
    PreviewRiskAnalysis,
)

ApprovalContext = (
    ApprovalRequest | ApprovalResponse | ApprovalStatus | ApprovalToken | None
)


class SummaryGenerator:
    """Generate immutable aggregate facts from actions and scoring results."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Initialize the replaceable clock dependency."""

        self._clock = clock

    def generate(
        self,
        actions: Sequence[ActionPreview],
        risk_analysis: PreviewRiskAnalysis,
        *,
        approval: ApprovalContext = None,
        cancelled: bool = False,
    ) -> ExecutionSummary:
        """Return action count, duration, approval, rollback, and readiness."""

        ordered = tuple(actions)
        if any(not isinstance(action, ActionPreview) for action in ordered):
            raise SummaryValidationError(
                "summary actions must contain ActionPreview instances"
            )
        if not isinstance(risk_analysis, PreviewRiskAnalysis):
            raise SummaryValidationError(
                "summary generation requires PreviewRiskAnalysis"
            )
        if not isinstance(cancelled, bool):
            raise SummaryValidationError("cancelled must be a bool")

        approval_status = self.approval_status(approval)
        terminal_denial = approval_status in {
            ApprovalStatus.DENIED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        }
        approved = approval_status is ApprovalStatus.APPROVED
        approval_required = (
            not cancelled
            and not approved
            and not terminal_denial
            and (
                approval_status is ApprovalStatus.PENDING
                or risk_analysis.level
                in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}
            )
        )

        if cancelled:
            readiness = ExecutionReadiness.CANCELLED
            approval_required = False
        elif risk_analysis.level is RiskLevel.CRITICAL or terminal_denial:
            readiness = ExecutionReadiness.BLOCKED
        elif approval_required:
            readiness = ExecutionReadiness.APPROVAL_REQUIRED
        else:
            readiness = ExecutionReadiness.READY

        permissions: list[PermissionLevel] = []
        for action in ordered:
            if action.required_permission not in permissions:
                permissions.append(action.required_permission)
        total_duration = sum(
            (action.estimated_duration for action in ordered),
            start=timedelta(0),
        )
        return ExecutionSummary(
            action_count=len(ordered),
            estimated_duration=total_duration,
            approval_required=approval_required,
            rollback_available=bool(ordered)
            and all(action.rollback_available for action in ordered),
            readiness=readiness,
            required_permissions=tuple(permissions),
            generated_at=self._now(),
        )

    def approval_status(self, approval: ApprovalContext) -> ApprovalStatus | None:
        """Resolve existing approval models to one typed lifecycle status."""

        if approval is None:
            return None
        if isinstance(approval, ApprovalStatus):
            return approval
        if isinstance(approval, ApprovalRequest):
            return approval.status
        if isinstance(approval, ApprovalResponse):
            return approval.status
        if isinstance(approval, ApprovalToken):
            if approval.is_expired(self._now()):
                return ApprovalStatus.EXPIRED
            return ApprovalStatus.APPROVED
        raise SummaryValidationError("unsupported approval context")

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SummaryValidationError("summary clock must return an aware datetime")
        return value


ExecutionSummaryGenerator = SummaryGenerator


__all__ = [
    "ApprovalContext",
    "ExecutionSummary",
    "ExecutionSummaryGenerator",
    "SummaryGenerator",
]
