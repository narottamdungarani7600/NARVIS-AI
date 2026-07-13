"""Approval decision coordination for trusted execution requests.

The manager combines permission, risk, and trust-policy facts.  It never opens
an interface or waits for a user; future dashboard, voice, and mobile adapters
can implement :class:`ApprovalProvider` around its structured decisions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger

from .models import (
    ApprovalDecision,
    ApprovalDecisionType,
    ExecutionRequest,
    PermissionLevel,
    PolicyDecision,
    PolicyDecisionType,
    RiskAssessment,
    RiskLevel,
    TrustPolicyContext,
)
from .permissions import PermissionChecker, PermissionEngine
from .policy import AllowPolicy, ApprovalRequiredPolicy, DenyPolicy, TrustPolicy
from .risk import RiskAnalyzer, RiskEvaluator


class ApprovalProvider(Protocol):
    """Future adapter contract for dashboard, voice, or mobile approvals.

    Sprint 2 stores providers for future composition but deliberately never
    invokes them.  This keeps all current decisions non-interactive.
    """

    @property
    def name(self) -> str:
        """Return a stable provider name."""

    def request_approval(
        self,
        request: ExecutionRequest,
        decision: ApprovalDecision,
    ) -> ApprovalDecisionType:
        """Request a future external decision for an approval-required result."""


class ApprovalManager:
    """Produce fail-closed approval decisions without interacting with a UI."""

    def __init__(
        self,
        permission_engine: PermissionChecker | None = None,
        risk_analyzer: RiskEvaluator | None = None,
        *,
        policies: Mapping[RiskLevel, TrustPolicy] | None = None,
        providers: Iterable[ApprovalProvider] = (),
        logger: Logger | None = None,
    ) -> None:
        """Initialize approval coordination dependencies.

        Args:
            permission_engine: Permission service used for effective-level and
                grant evaluation.
            risk_analyzer: Replaceable rule-based or future AI-based analyzer.
            policies: Optional policies overriding defaults for individual risk
                levels.  Low risk is allowed, medium and high require approval,
                and critical risk is denied by default.
            providers: Future approval provider adapters retained for later use.
                Sprint 2 never invokes them.
            logger: Core-compatible structured logger.
        """

        self._logger = logger or NullLogger("narvis.execution.approval")
        self._permission_engine = permission_engine or PermissionEngine(
            logger=self._logger
        )
        self._risk_analyzer = risk_analyzer or RiskAnalyzer(logger=self._logger)

        configured_policies: dict[RiskLevel, TrustPolicy] = {
            RiskLevel.LOW: AllowPolicy(),
            RiskLevel.MEDIUM: ApprovalRequiredPolicy(),
            RiskLevel.HIGH: ApprovalRequiredPolicy(),
            RiskLevel.CRITICAL: DenyPolicy(
                name="critical_risk_deny",
                reason_code="critical_risk_denied",
                message="Critical-risk requests are denied by trust policy.",
            ),
        }
        for risk_level, policy in dict(policies or {}).items():
            if not isinstance(risk_level, RiskLevel):
                raise ValueError("approval policy keys must be RiskLevel members")
            if not callable(getattr(policy, "evaluate", None)):
                raise ValueError("approval policies must implement evaluate()")
            configured_policies[risk_level] = policy

        self._policies: Mapping[RiskLevel, TrustPolicy] = MappingProxyType(
            configured_policies
        )
        self._providers = tuple(providers)

    @property
    def permission_engine(self) -> PermissionChecker:
        """Return the permission service used by this manager."""

        return self._permission_engine

    @property
    def risk_analyzer(self) -> RiskEvaluator:
        """Return the risk analyzer used by this manager."""

        return self._risk_analyzer

    @property
    def policies(self) -> Mapping[RiskLevel, TrustPolicy]:
        """Return the immutable risk-to-policy mapping."""

        return self._policies

    @property
    def providers(self) -> tuple[ApprovalProvider, ...]:
        """Return future providers without invoking them."""

        return self._providers

    def decide(self, request: ExecutionRequest) -> ApprovalDecision:
        """Evaluate permission, risk, and trust policy for ``request``.

        Every dependency failure produces a typed denial.  The method never
        calls a provider or performs the proposed action.
        """

        if not isinstance(request, ExecutionRequest):
            return self._failure_decision(
                request_id="",
                required_level=PermissionLevel.NONE,
                reason_code="invalid_request",
                message="Approval decisions require a typed ExecutionRequest.",
                failure_stage="validation",
            )

        try:
            required_level = self._permission_engine.required_level_for(request)
            if not isinstance(required_level, PermissionLevel):
                raise TypeError("permission engine returned an invalid level")
        except Exception as error:
            self._log_failure("permission", request, error)
            return self._failure_decision(
                request_id=request.request_id,
                required_level=request.permission_level,
                reason_code="permission_check_failed",
                message="Permission evaluation failed closed.",
                failure_stage="permission",
            )

        try:
            risk_assessment = self._risk_analyzer.analyze(request, required_level)
            if not isinstance(risk_assessment, RiskAssessment):
                raise TypeError("risk analyzer returned an invalid assessment")
            if not isinstance(risk_assessment.risk_level, RiskLevel):
                raise TypeError("risk analyzer returned an invalid risk level")
        except Exception as error:
            self._log_failure("risk", request, error)
            return self._failure_decision(
                request_id=request.request_id,
                required_level=required_level,
                reason_code="risk_analysis_failed",
                message="Risk analysis failed closed.",
                failure_stage="risk",
            )

        self._log(
            LogLevel.INFO,
            "Approval manager received risk assessment",
            request_id=request.request_id,
            action=request.action,
            risk_level=risk_assessment.risk_level.value,
        )

        try:
            permission_granted = (
                self._permission_engine.check_permission(request) is True
            )
        except Exception as error:
            self._log_failure("permission", request, error)
            return self._failure_decision(
                request_id=request.request_id,
                required_level=required_level,
                reason_code="permission_check_failed",
                message="Permission evaluation failed closed.",
                failure_stage="permission",
                risk_assessment=risk_assessment,
            )

        self._log(
            LogLevel.DEBUG if permission_granted else LogLevel.WARNING,
            "Approval permission stage evaluated",
            request_id=request.request_id,
            action=request.action,
            required_level=required_level.value,
            permission_granted=permission_granted,
        )
        if not permission_granted:
            return ApprovalDecision(
                request_id=request.request_id,
                decision=ApprovalDecisionType.DENIED,
                permission_granted=False,
                required_permission_level=required_level,
                reason_code="permission_denied",
                message="The request does not have the required permission.",
                risk_assessment=risk_assessment,
                failure_stage="permission",
            )

        context = TrustPolicyContext(
            request=request,
            risk_assessment=risk_assessment,
            permission_granted=True,
            required_permission_level=required_level,
        )
        policy = self._policies[risk_assessment.risk_level]
        try:
            policy_decision = policy.evaluate(context)
            if not isinstance(policy_decision, PolicyDecision):
                raise TypeError("trust policy returned an invalid decision")
            if not isinstance(policy_decision.decision, PolicyDecisionType):
                raise TypeError("trust policy returned an invalid decision type")
        except Exception as error:
            self._log_failure("policy", request, error)
            return self._failure_decision(
                request_id=request.request_id,
                required_level=required_level,
                reason_code="policy_evaluation_failed",
                message="Trust policy evaluation failed closed.",
                failure_stage="policy",
                risk_assessment=risk_assessment,
                permission_granted=True,
            )

        decision_type = self._approval_type_for(policy_decision.decision)
        decision = ApprovalDecision(
            request_id=request.request_id,
            decision=decision_type,
            permission_granted=True,
            required_permission_level=required_level,
            reason_code=policy_decision.reason_code,
            message=policy_decision.message,
            risk_assessment=risk_assessment,
            policy_decision=policy_decision,
        )
        self._log(
            (
                LogLevel.WARNING
                if decision_type is ApprovalDecisionType.DENIED
                else LogLevel.INFO
            ),
            "Trust policy evaluated for approval",
            request_id=request.request_id,
            action=request.action,
            policy_name=policy_decision.policy_name,
            policy_decision=policy_decision.decision.value,
            approval_decision=decision_type.value,
        )
        return decision

    def evaluate(self, request: ExecutionRequest) -> ApprovalDecision:
        """Return :meth:`decide` for callers using evaluation terminology."""

        return self.decide(request)

    def requires_approval(self, request: ExecutionRequest) -> bool:
        """Return whether evaluating ``request`` produces a pending decision."""

        return self.decide(request).approval_required

    @staticmethod
    def _approval_type_for(
        policy_decision: PolicyDecisionType,
    ) -> ApprovalDecisionType:
        """Translate an independent policy outcome into approval terminology."""

        if policy_decision is PolicyDecisionType.ALLOW:
            return ApprovalDecisionType.GRANTED
        if policy_decision is PolicyDecisionType.APPROVAL_REQUIRED:
            return ApprovalDecisionType.REQUIRED
        return ApprovalDecisionType.DENIED

    def _failure_decision(
        self,
        *,
        request_id: str,
        required_level: PermissionLevel,
        reason_code: str,
        message: str,
        failure_stage: str,
        risk_assessment: RiskAssessment | None = None,
        permission_granted: bool = False,
    ) -> ApprovalDecision:
        """Build one consistent fail-closed approval decision."""

        return ApprovalDecision(
            request_id=request_id,
            decision=ApprovalDecisionType.DENIED,
            permission_granted=permission_granted,
            required_permission_level=required_level,
            reason_code=reason_code,
            message=message,
            risk_assessment=risk_assessment,
            failure_stage=failure_stage,
        )

    def _log_failure(
        self,
        stage: str,
        request: ExecutionRequest,
        error: Exception,
    ) -> None:
        """Log a dependency failure without including request data mappings."""

        self._log(
            LogLevel.ERROR,
            "Approval decision stage failed",
            request_id=request.request_id,
            action=request.action,
            failure_stage=stage,
            error_type=type(error).__name__,
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit an entry without allowing logger failures to change policy."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "ApprovalDecision",
    "ApprovalDecisionType",
    "ApprovalManager",
    "ApprovalProvider",
]
