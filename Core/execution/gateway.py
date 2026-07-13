"""Trusted, non-executing gateway for proposed computer actions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .approval import ApprovalManager, ApprovalProvider
from .exceptions import ExecutionValidationError
from .models import (
    ApprovalDecisionType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    PermissionLevel,
    RiskLevel,
)
from .permissions import PermissionChecker, PermissionEngine
from .policy import TrustPolicy
from .risk import RiskAnalyzer, RiskEvaluator


class EventPublisher(Protocol):
    """Minimal event-bus contract required by the gateway."""

    def publish(self, event: SystemEvent) -> None:
        """Publish one execution lifecycle event."""


class ExecutionDispatcher(Protocol):
    """Future extension contract for an approved execution dispatcher.

    This protocol defines a boundary so a later dispatcher can be injected
    without changing request or result models.  The gateway does not accept or
    invoke a dispatcher in the current phase.
    """

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Dispatch an already authorized request and return its outcome."""


class TrustedExecutionGateway:
    """Validate and authorize execution requests without executing actions.

    The gateway is fail closed: malformed requests, decision-service failures,
    approval requirements, and denials all become typed non-executing results.
    Every decision dependency is injected so the boundary remains testable and
    independent of runtime composition.
    """

    REQUEST_RECEIVED_EVENT = "execution.request.received"
    REQUEST_REJECTED_EVENT = "execution.request.rejected"
    PERMISSION_DENIED_EVENT = "execution.permission.denied"
    REQUEST_AUTHORIZED_EVENT = "execution.request.authorized"
    RISK_EVALUATED_EVENT = "execution.risk.evaluated"
    APPROVAL_REQUIRED_EVENT = "execution.approval.required"
    APPROVAL_GRANTED_EVENT = "execution.approval.granted"
    APPROVAL_DENIED_EVENT = "execution.approval.denied"

    def __init__(
        self,
        permission_engine: PermissionChecker | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
        risk_analyzer: RiskEvaluator | None = None,
        approval_manager: ApprovalManager | None = None,
        policies: Mapping[RiskLevel, TrustPolicy] | None = None,
        approval_providers: Iterable[ApprovalProvider] = (),
    ) -> None:
        """Initialize the trusted gateway with injected dependencies.

        Args:
            permission_engine: Permission service used to evaluate requests.
            logger: Core-compatible logger implementation.
            event_bus: Existing EventBus or compatible publisher used for
                execution lifecycle events.
            risk_analyzer: Replaceable risk service used by a default approval
                manager.
            approval_manager: Fully composed approval service.  When supplied,
                its permission and risk dependencies become gateway properties.
            policies: Risk-specific trust policy overrides used when the gateway
                creates its approval manager.
            approval_providers: Future provider adapters retained by the default
                approval manager but never invoked in Sprint 2.
        """

        self._logger = logger or NullLogger("narvis.execution.gateway")
        if approval_manager is None:
            resolved_permission_engine = permission_engine or PermissionEngine(
                logger=self._logger
            )
            resolved_risk_analyzer = risk_analyzer or RiskAnalyzer(logger=self._logger)
            approval_manager = ApprovalManager(
                resolved_permission_engine,
                resolved_risk_analyzer,
                policies=policies,
                providers=approval_providers,
                logger=self._logger,
            )
        self._approval_manager = approval_manager
        self._permission_engine = approval_manager.permission_engine
        self._risk_analyzer = approval_manager.risk_analyzer
        self._event_bus = event_bus

    @property
    def permission_engine(self) -> PermissionChecker:
        """Return the injected permission service."""

        return self._permission_engine

    @property
    def risk_analyzer(self) -> RiskEvaluator:
        """Return the risk service used for gateway decisions."""

        return self._risk_analyzer

    @property
    def approval_manager(self) -> ApprovalManager:
        """Return the composed approval decision service."""

        return self._approval_manager

    def validate_request(self, request: ExecutionRequest) -> None:
        """Validate the structural execution request contract.

        Args:
            request: Candidate request to validate.

        Raises:
            ExecutionValidationError: If any required field is malformed.
        """

        if not isinstance(request, ExecutionRequest):
            raise ExecutionValidationError(
                "trusted execution requires a typed ExecutionRequest"
            )
        if (
            not isinstance(request.request_id, str)
            or not request.request_id.strip()
            or request.request_id != request.request_id.strip()
            or len(request.request_id) > 128
        ):
            raise ExecutionValidationError(
                "request_id must be a normalized non-empty string of at most 128 characters"
            )
        if (
            not isinstance(request.action, str)
            or not request.action.strip()
            or request.action != request.action.strip()
            or len(request.action) > 256
        ):
            raise ExecutionValidationError(
                "action must be a normalized non-empty string of at most 256 characters"
            )

        if not isinstance(request.permission_level, PermissionLevel):
            raise ExecutionValidationError("permission_level must be a PermissionLevel")
        self._validate_mapping("parameters", request.parameters)
        self._validate_mapping("metadata", request.metadata)

    def authorize(self, request: ExecutionRequest) -> ExecutionResult:
        """Return a typed authorization decision without invoking an action."""

        context = self._request_context(request)
        self._log(LogLevel.DEBUG, "Execution request received", **context)
        self._publish(self.REQUEST_RECEIVED_EVENT, context)

        try:
            self.validate_request(request)
        except ExecutionValidationError as error:
            result = ExecutionResult(
                request_id=context["request_id"],
                action=context["action"],
                status=ExecutionStatus.REJECTED,
                message=str(error),
                reason_code="invalid_request",
            )
            self._log(
                LogLevel.WARNING,
                "Execution request rejected",
                **context,
                reason_code=result.reason_code,
            )
            self._publish_result(self.REQUEST_REJECTED_EVENT, result)
            return result

        try:
            approval = self._approval_manager.decide(request)
        except Exception as error:
            result = ExecutionResult(
                request_id=request.request_id,
                action=request.action,
                status=ExecutionStatus.DENIED,
                message="Approval evaluation failed closed.",
                permission_level=request.permission_level,
                reason_code="approval_check_failed",
                approval_decision=ApprovalDecisionType.DENIED,
            )
            self._log(
                LogLevel.ERROR,
                "Execution approval evaluation failed",
                **context,
                error_type=type(error).__name__,
            )
            self._publish_result(self.APPROVAL_DENIED_EVENT, result)
            return result

        risk_assessment = approval.risk_assessment
        if risk_assessment is not None:
            self._publish(
                self.RISK_EVALUATED_EVENT,
                {
                    "request_id": request.request_id,
                    "action": request.action,
                    "risk_level": risk_assessment.risk_level.value,
                    "reason_codes": risk_assessment.reason_codes,
                },
            )

        policy_decision = (
            approval.policy_decision.decision
            if approval.policy_decision is not None
            else None
        )
        if approval.approval_required:
            result = ExecutionResult(
                request_id=request.request_id,
                action=request.action,
                status=ExecutionStatus.PENDING,
                message=approval.message,
                permission_level=approval.required_permission_level,
                reason_code=approval.reason_code,
                risk_level=(
                    risk_assessment.risk_level if risk_assessment is not None else None
                ),
                approval_decision=approval.decision,
                policy_decision=policy_decision,
            )
            self._log(
                LogLevel.INFO,
                "Execution request requires user approval",
                **context,
                required_level=approval.required_permission_level.value,
                risk_level=(
                    risk_assessment.risk_level.value
                    if risk_assessment is not None
                    else ""
                ),
            )
            self._publish_result(self.APPROVAL_REQUIRED_EVENT, result)
            return result

        if approval.denied:
            result = ExecutionResult(
                request_id=request.request_id,
                action=request.action,
                status=ExecutionStatus.DENIED,
                message=approval.message,
                permission_level=approval.required_permission_level,
                reason_code=approval.reason_code,
                risk_level=(
                    risk_assessment.risk_level if risk_assessment is not None else None
                ),
                approval_decision=approval.decision,
                policy_decision=policy_decision,
            )
            self._log(
                (
                    LogLevel.WARNING
                    if approval.reason_code == "permission_denied"
                    else LogLevel.ERROR
                ),
                "Execution approval denied",
                **context,
                required_level=approval.required_permission_level.value,
                reason_code=approval.reason_code,
                failure_stage=approval.failure_stage,
            )
            self._publish_result(self.APPROVAL_DENIED_EVENT, result)
            if approval.failure_stage == "permission":
                self._publish_result(self.PERMISSION_DENIED_EVENT, result)
            return result

        result = ExecutionResult(
            request_id=request.request_id,
            action=request.action,
            status=ExecutionStatus.AUTHORIZED,
            message=(
                "The request is authorized. Dispatcher integration is not enabled, "
                "so no action was executed."
            ),
            permission_level=approval.required_permission_level,
            reason_code="execution_authorized",
            risk_level=(
                risk_assessment.risk_level if risk_assessment is not None else None
            ),
            approval_decision=approval.decision,
            policy_decision=policy_decision,
        )
        self._log(
            LogLevel.INFO,
            "Execution request authorized without dispatch",
            **context,
            required_level=approval.required_permission_level.value,
            risk_level=(
                risk_assessment.risk_level.value if risk_assessment is not None else ""
            ),
            executed=False,
            dispatcher_invoked=False,
        )
        self._publish_result(self.APPROVAL_GRANTED_EVENT, result)
        self._publish_result(self.REQUEST_AUTHORIZED_EVENT, result)
        return result

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Evaluate ``request`` without performing real execution.

        This method preserves a natural gateway entry point for callers while
        delegating to :meth:`authorize`.  It must not be confused with future
        dispatcher execution.
        """

        return self.authorize(request)

    @staticmethod
    def _validate_mapping(name: str, value: object) -> None:
        """Validate an inert string-keyed request mapping."""

        if not isinstance(value, Mapping):
            raise ExecutionValidationError(f"{name} must be a mapping")
        if any(not isinstance(key, str) for key in value):
            raise ExecutionValidationError(f"{name} keys must be strings")

    @staticmethod
    def _request_context(request: object) -> dict[str, str]:
        """Build safe correlation context without reading action parameters."""

        request_id = getattr(request, "request_id", "")
        action = getattr(request, "action", "")
        return {
            "request_id": request_id if isinstance(request_id, str) else "",
            "action": action if isinstance(action, str) else "",
        }

    def _publish_result(self, event_name: str, result: ExecutionResult) -> None:
        """Publish a non-sensitive event payload for a gateway result."""

        payload: dict[str, Any] = {
            "request_id": result.request_id,
            "action": result.action,
            "status": result.status.value,
            "reason_code": result.reason_code,
            "executed": result.executed,
            "dispatcher_invoked": result.dispatcher_invoked,
        }
        if result.permission_level is not None:
            payload["permission_level"] = result.permission_level.value
        if result.risk_level is not None:
            payload["risk_level"] = result.risk_level.value
        if result.approval_decision is not None:
            payload["approval_decision"] = result.approval_decision.value
        if result.policy_decision is not None:
            payload["policy_decision"] = result.policy_decision.value
        self._publish(event_name, payload)

    def _publish(self, event_name: str, payload: Mapping[str, Any]) -> None:
        """Publish an event without allowing subscriber failures to change a decision."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=dict(payload)))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish execution event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a Core logger entry without changing gateway control flow."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["EventPublisher", "ExecutionDispatcher", "TrustedExecutionGateway"]
