"""Deterministic scoring-only risk analysis for execution previews."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from Core.execution.models import ExecutionRequest, PermissionLevel, RiskLevel
from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent
from Execution.session.models import new_id, utc_now
from Execution.session.queue import EventPublisher

from .exceptions import RiskAnalysisError
from .models import ActionPreview, PreviewRiskAnalysis, RiskFactor

_PERMISSION_SCORES: dict[PermissionLevel, float] = {
    PermissionLevel.NONE: 0.0,
    PermissionLevel.READ_ONLY: 8.0,
    PermissionLevel.STANDARD: 20.0,
    PermissionLevel.ELEVATED: 50.0,
    PermissionLevel.ADMINISTRATOR: 75.0,
}

_HIGH_RISK_TERMS = frozenset(
    {
        "configure",
        "install",
        "modify",
        "move",
        "restart",
        "write",
    }
)
_CRITICAL_RISK_TERMS = frozenset(
    {
        "delete",
        "disable",
        "erase",
        "format",
        "kill",
        "remove",
        "shutdown",
        "terminate",
    }
)


class PreviewRiskAnalyzer:
    """Assign explainable risk scores without authorizing or executing actions."""

    RISK_ANALYZED_EVENT = "execution.risk.analyzed"

    def __init__(
        self,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Initialize observability and clock dependencies."""

        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.execution.preview.risk")
        self._clock = clock

    def analyze(
        self,
        request: ExecutionRequest,
        actions: Sequence[ActionPreview],
        *,
        preview_id: str | None = None,
    ) -> PreviewRiskAnalysis:
        """Return a deterministic score and level for an ordered action plan."""

        if not isinstance(request, ExecutionRequest):
            raise RiskAnalysisError("risk analysis requires an ExecutionRequest")
        ordered = tuple(actions)
        if not ordered or any(not isinstance(item, ActionPreview) for item in ordered):
            raise RiskAnalysisError("risk analysis requires at least one ActionPreview")
        if not isinstance(request.permission_level, PermissionLevel) or any(
            not isinstance(action.required_permission, PermissionLevel)
            for action in ordered
        ):
            raise RiskAnalysisError("risk analysis requires typed permission levels")

        permissions = (request.permission_level,) + tuple(
            action.required_permission for action in ordered
        )
        highest_permission = max(
            permissions,
            key=lambda permission: _PERMISSION_SCORES[permission],
        )
        permission_score = _PERMISSION_SCORES[highest_permission]
        factors = [
            RiskFactor(
                code="permission_baseline",
                score=permission_score,
                description=(
                    "Risk baseline derived from the highest required permission."
                ),
                level=self.level_for_score(permission_score),
            )
        ]

        action_terms = {
            term
            for action in ordered
            for term in action.action.lower()
            .replace("-", ".")
            .replace("_", ".")
            .split(".")
        }
        critical_matches = sorted(action_terms & _CRITICAL_RISK_TERMS)
        high_matches = sorted(action_terms & _HIGH_RISK_TERMS)
        if critical_matches:
            factors.append(
                RiskFactor(
                    code="critical_action_term",
                    score=60.0,
                    description=(
                        "Critical-risk action terms: " + ", ".join(critical_matches)
                    ),
                    level=RiskLevel.CRITICAL,
                )
            )
        elif high_matches:
            factors.append(
                RiskFactor(
                    code="mutating_action_term",
                    score=25.0,
                    description=(
                        "Potentially mutating action terms: " + ", ".join(high_matches)
                    ),
                    level=RiskLevel.HIGH,
                )
            )

        if len(ordered) > 1:
            action_count_score = min(15.0, float((len(ordered) - 1) * 3))
            factors.append(
                RiskFactor(
                    code="multi_action_plan",
                    score=action_count_score,
                    description="Additional score for a multi-action preview.",
                    level=self.level_for_score(action_count_score),
                )
            )

        without_rollback = sum(1 for action in ordered if not action.rollback_available)
        if without_rollback:
            rollback_score = min(15.0, float(without_rollback * 5))
            factors.append(
                RiskFactor(
                    code="rollback_unavailable",
                    score=rollback_score,
                    description=(
                        "Some preview actions do not declare rollback availability."
                    ),
                    level=self.level_for_score(rollback_score),
                )
            )

        score = min(100.0, sum(factor.score for factor in factors))
        analysis = PreviewRiskAnalysis(
            preview_id=preview_id or new_id(),
            request_id=request.request_id,
            score=score,
            level=self.level_for_score(score),
            factors=tuple(factors),
            analyzed_at=self._now(),
        )
        self._log(
            LogLevel.INFO,
            "Execution preview risk analyzed",
            preview_id=analysis.preview_id,
            request_id=analysis.request_id,
            risk_level=analysis.level.value,
            risk_score=analysis.score,
            scoring_only=True,
            executed=False,
        )
        self._publish(
            analysis,
            action_count=len(ordered),
        )
        return analysis

    def score(
        self,
        request: ExecutionRequest,
        actions: Sequence[ActionPreview],
        *,
        preview_id: str | None = None,
    ) -> PreviewRiskAnalysis:
        """Return :meth:`analyze` for score-oriented callers."""

        return self.analyze(request, actions, preview_id=preview_id)

    @staticmethod
    def level_for_score(score: float) -> RiskLevel:
        """Map a bounded score to LOW, MEDIUM, HIGH, or CRITICAL."""

        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RiskAnalysisError("risk score must be numeric")
        if score < 0 or score > 100 or score != score:
            raise RiskAnalysisError("risk score must be between 0 and 100")
        if score >= 75:
            return RiskLevel.CRITICAL
        if score >= 50:
            return RiskLevel.HIGH
        if score >= 25:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _publish(
        self,
        analysis: PreviewRiskAnalysis,
        *,
        action_count: int,
    ) -> None:
        """Publish non-sensitive scoring facts."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.RISK_ANALYZED_EVENT,
                    payload={
                        "preview_id": analysis.preview_id,
                        "request_id": analysis.request_id,
                        "risk_level": analysis.level.value,
                        "risk_score": analysis.score,
                        "factor_count": len(analysis.factors),
                        "action_count": action_count,
                        "scoring_only": True,
                        "executed": False,
                    },
                )
            )
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish execution risk event",
                event_name=self.RISK_ANALYZED_EVENT,
                error_type=type(error).__name__,
            )

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RiskAnalysisError("risk analyzer clock must return an aware datetime")
        return value

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failures to alter scoring."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


RiskAnalyzer = PreviewRiskAnalyzer


__all__ = [
    "PreviewRiskAnalyzer",
    "RiskAnalyzer",
    "RiskFactor",
    "RiskLevel",
]
