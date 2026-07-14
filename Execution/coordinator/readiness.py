"""Readiness report generation for safe execution coordination."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from Core.execution.models import PermissionLevel, RiskLevel
from Execution.preview.models import ExecutionReadiness
from Execution.preview.summary import SummaryGenerator
from Execution.session.models import ApprovalStatus, utc_now

from .exceptions import ReadinessError
from .models import ExecutionCoordination, ExecutionReadinessReport, ValidationReport
from .validator import CoordinatorValidator


class ExecutionReadinessEvaluator:
    """Generate explainable readiness without granting execution authority."""

    def __init__(
        self,
        validator: CoordinatorValidator | None = None,
        *,
        summary_generator: SummaryGenerator | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Initialize validation, approval, and clock dependencies."""

        self._validator = validator or CoordinatorValidator(clock=clock)
        self._summary_generator = summary_generator or SummaryGenerator(clock=clock)
        self._clock = clock

    def generate(
        self,
        coordination: ExecutionCoordination,
        *,
        validation_report: ValidationReport | None = None,
        available_permissions: Iterable[PermissionLevel] | None = None,
    ) -> ExecutionReadinessReport:
        """Return all missing requirements and a bounded readiness score."""

        if not isinstance(coordination, ExecutionCoordination):
            raise ReadinessError(
                "readiness generation requires an ExecutionCoordination"
            )
        validation = validation_report or self._validator.validate(
            coordination,
            available_permissions=available_permissions,
        )
        if not isinstance(validation, ValidationReport):
            raise ReadinessError("validation_report must be a ValidationReport")

        missing = list(validation.missing_requirements)
        preview = coordination.preview
        risk = coordination.risk_analysis
        approval_status = self._approval_status(coordination)

        if preview is not None and preview.cancelled:
            missing.append("preview_cancelled")
        terminal_approval = approval_status in {
            ApprovalStatus.DENIED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        }
        if terminal_approval:
            missing.append(f"approval_{approval_status.value}")
        approval_required = bool(
            preview is not None
            and preview.summary.approval_required
            and approval_status is not ApprovalStatus.APPROVED
            and not terminal_approval
        )
        if approval_required:
            missing.append("approval_required")
        if risk is not None and risk.level is RiskLevel.CRITICAL:
            missing.append("critical_risk")

        unique_missing = tuple(dict.fromkeys(missing))
        risk_level = risk.level if risk is not None else None
        estimated_duration = (
            preview.estimated_duration if preview is not None else timedelta(0)
        )
        rollback_available = bool(
            preview is not None and preview.summary.rollback_available
        )
        required_permissions = (
            preview.required_permissions if preview is not None else ()
        )

        if preview is not None and preview.cancelled:
            readiness = ExecutionReadiness.CANCELLED
        elif terminal_approval or risk_level is RiskLevel.CRITICAL:
            readiness = ExecutionReadiness.BLOCKED
        elif validation.missing_requirements or validation.errors:
            readiness = ExecutionReadiness.BLOCKED
        elif approval_required:
            readiness = ExecutionReadiness.APPROVAL_REQUIRED
        else:
            readiness = ExecutionReadiness.READY

        score = self._score(
            missing=unique_missing,
            risk_level=risk_level,
            rollback_available=rollback_available,
            approval_required=approval_required,
            terminal_approval=terminal_approval,
        )
        return ExecutionReadinessReport(
            coordination_id=coordination.coordination_id,
            missing_requirements=unique_missing,
            approval_status=approval_status,
            risk_level=risk_level,
            estimated_duration=estimated_duration,
            rollback_available=rollback_available,
            execution_readiness_score=score,
            readiness=readiness,
            required_permissions=required_permissions,
            generated_at=self._now(),
        )

    def evaluate(
        self,
        coordination: ExecutionCoordination,
        **kwargs: object,
    ) -> ExecutionReadinessReport:
        """Return :meth:`generate` for evaluator-oriented callers."""

        return self.generate(coordination, **kwargs)

    def _approval_status(
        self,
        coordination: ExecutionCoordination,
    ) -> ApprovalStatus | None:
        """Resolve the existing approval model retained by coordination."""

        try:
            return self._summary_generator.approval_status(coordination.approval)
        except Exception as error:
            raise ReadinessError("unable to resolve approval status") from error

    @staticmethod
    def _score(
        *,
        missing: tuple[str, ...],
        risk_level: RiskLevel | None,
        rollback_available: bool,
        approval_required: bool,
        terminal_approval: bool,
    ) -> float:
        """Calculate one transparent bounded readiness score."""

        score = 100.0 - min(48.0, float(len(missing) * 12))
        risk_penalty = {
            None: 20.0,
            RiskLevel.LOW: 0.0,
            RiskLevel.MEDIUM: 10.0,
            RiskLevel.HIGH: 25.0,
            RiskLevel.CRITICAL: 50.0,
        }[risk_level]
        score -= risk_penalty
        if not rollback_available:
            score -= 10.0
        if approval_required:
            score -= 20.0
        if terminal_approval:
            score -= 40.0
        return max(0.0, min(100.0, score))

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ReadinessError("readiness clock must return an aware datetime")
        return value


ReadinessEvaluator = ExecutionReadinessEvaluator


__all__ = [
    "ExecutionReadinessEvaluator",
    "ReadinessEvaluator",
]
