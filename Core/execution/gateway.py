"""Trusted authorization and execution lifecycle gateway."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .approval import ApprovalManager, ApprovalProvider
from .audit import AuditLogger, AuditRecorder
from .dispatcher import DispatcherInterface, ExecutionDispatcher
from .exceptions import ExecutionValidationError
from .models import (
    AuditStage,
    ApprovalDecisionType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    PermissionLevel,
    RiskLevel,
    RollbackResult,
    RollbackStatus,
    VerificationReport,
    VerificationStatus,
)
from .permissions import PermissionChecker, PermissionEngine
from .policy import TrustPolicy
from .risk import RiskAnalyzer, RiskEvaluator
from .rollback import RollbackManager, RollbackService
from .verifier import VerificationEngine, VerificationService


class EventPublisher(Protocol):
    """Minimal event-bus contract required by the gateway."""

    def publish(self, event: SystemEvent) -> None:
        """Publish one execution lifecycle event."""


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
    EXECUTION_STARTED_EVENT = "execution.started"
    EXECUTION_DISPATCHED_EVENT = "execution.dispatched"
    EXECUTION_VERIFIED_EVENT = "execution.verified"
    EXECUTION_ROLLBACK_EVENT = "execution.rollback"
    EXECUTION_COMPLETED_EVENT = "execution.completed"
    EXECUTION_FAILED_EVENT = "execution.failed"
    STARTED_EVENT = EXECUTION_STARTED_EVENT
    DISPATCHED_EVENT = EXECUTION_DISPATCHED_EVENT
    VERIFIED_EVENT = EXECUTION_VERIFIED_EVENT
    ROLLBACK_EVENT = EXECUTION_ROLLBACK_EVENT
    COMPLETED_EVENT = EXECUTION_COMPLETED_EVENT
    FAILED_EVENT = EXECUTION_FAILED_EVENT

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
        dispatcher: DispatcherInterface | None = None,
        verification_engine: VerificationService | None = None,
        rollback_manager: RollbackService | None = None,
        audit_logger: AuditRecorder | None = None,
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
            dispatcher: Optional routing boundary.  Omitting it preserves the
                authorization-only behavior of Sprints 1 and 2.
            verification_engine: Result verifier used after dispatch.
            rollback_manager: Simulation-only rollback service used after a
                failed verification when an action may have run.
            audit_logger: Append-only execution lifecycle recorder.
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
        self._dispatcher = dispatcher
        self._verification_engine = verification_engine or VerificationEngine(
            logger=self._logger
        )
        self._rollback_manager = rollback_manager or RollbackManager(
            logger=self._logger
        )
        self._audit_logger = audit_logger or AuditLogger(logger=self._logger)

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

    @property
    def dispatcher(self) -> DispatcherInterface | None:
        """Return the injected execution router, if enabled."""

        return self._dispatcher

    @property
    def verification_engine(self) -> VerificationService:
        """Return the configured verification service."""

        return self._verification_engine

    @property
    def rollback_manager(self) -> RollbackService:
        """Return the configured simulation-only rollback manager."""

        return self._rollback_manager

    @property
    def audit_logger(self) -> AuditRecorder:
        """Return the append-only audit logger."""

        return self._audit_logger

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
        self._audit(
            request,
            AuditStage.REQUEST_RECEIVED,
            "received",
        )

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
            self._audit(
                request,
                AuditStage.VALIDATED,
                "rejected",
                reason_code=result.reason_code,
            )
            return result

        self._log(LogLevel.DEBUG, "Execution request validated", **context)
        self._audit(request, AuditStage.VALIDATED, "passed")

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
            self._audit(
                request,
                AuditStage.APPROVAL_EVALUATED,
                "failed",
                reason_code=result.reason_code,
                error_type=type(error).__name__,
            )
            return result

        risk_assessment = approval.risk_assessment
        self._audit(
            request,
            AuditStage.PERMISSION_EVALUATED,
            "granted" if approval.permission_granted else "denied",
            required_permission_level=approval.required_permission_level.value,
        )
        if risk_assessment is not None:
            self._audit(
                request,
                AuditStage.RISK_EVALUATED,
                risk_assessment.risk_level.value,
                reason_codes=risk_assessment.reason_codes,
            )
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
        if approval.policy_decision is not None:
            self._audit(
                request,
                AuditStage.POLICY_EVALUATED,
                approval.policy_decision.decision.value,
                policy_name=approval.policy_decision.policy_name,
                reason_code=approval.policy_decision.reason_code,
            )
        self._audit(
            request,
            AuditStage.APPROVAL_EVALUATED,
            approval.decision.value,
            reason_code=approval.reason_code,
            failure_stage=approval.failure_stage,
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
        """Authorize and, when configured, run the trusted execution lifecycle.

        Omitting a dispatcher preserves the authorization-only behavior of the
        previous sprints.  An injected dispatcher activates routing,
        verification, simulated rollback when required, auditing, lifecycle
        events, and a final typed result.
        """

        authorization = self.authorize(request)
        if self._dispatcher is None:
            return authorization

        if not authorization.authorized:
            self._log(
                LogLevel.WARNING,
                "Execution failed before dispatch",
                request_id=authorization.request_id,
                action=authorization.action,
                status=authorization.status.value,
                reason_code=authorization.reason_code,
            )
            self._audit(
                request,
                AuditStage.FAILED,
                authorization.status.value,
                reason_code=authorization.reason_code,
                failure_stage="authorization",
            )
            failed_authorization = self._attach_audit_entries(authorization)
            self._publish_result(
                self.EXECUTION_FAILED_EVENT,
                failed_authorization,
            )
            return failed_authorization

        self._log(
            LogLevel.INFO,
            "Execution lifecycle started",
            request_id=request.request_id,
            action=request.action,
        )
        self._audit(request, AuditStage.STARTED, "started")
        self._publish_result(self.EXECUTION_STARTED_EVENT, authorization)

        dispatched = self._dispatch_safely(request, authorization)
        dispatch_level = (
            LogLevel.INFO
            if dispatched.status is not ExecutionStatus.FAILED
            else LogLevel.ERROR
        )
        self._log(
            dispatch_level,
            "Execution dispatch stage completed",
            request_id=request.request_id,
            action=request.action,
            status=dispatched.status.value,
            reason_code=dispatched.reason_code,
            executed=dispatched.executed,
        )
        self._audit(
            request,
            AuditStage.DISPATCHED,
            dispatched.status.value,
            reason_code=dispatched.reason_code,
            executed=dispatched.executed,
        )
        self._publish_result(self.EXECUTION_DISPATCHED_EVENT, dispatched)

        expected_outcome: Any = request.metadata.get("expected_outcome")
        verification = self._verify_safely(dispatched, expected_outcome)
        self._log(
            LogLevel.INFO if verification.passed else LogLevel.WARNING,
            "Execution verification stage completed",
            request_id=request.request_id,
            action=request.action,
            verification_status=verification.status.value,
            reason_code=verification.reason_code,
        )
        verified_result = replace(
            dispatched,
            verification_report=verification,
        )
        self._audit(
            request,
            AuditStage.VERIFIED,
            verification.status.value,
            reason_code=verification.reason_code,
            completion_verified=verification.completion_verified,
            outcome_verified=verification.outcome_verified,
        )
        self._publish_result(self.EXECUTION_VERIFIED_EVENT, verified_result)

        rollback_result: RollbackResult | None = None
        rollback_required = verification.requires_rollback and (
            dispatched.executed or request.metadata.get("rollback_required") is True
        )
        if rollback_required:
            rollback_result = self._rollback_safely(request)
            verified_result = replace(
                verified_result,
                rollback_result=rollback_result,
            )
            self._log(
                (
                    LogLevel.INFO
                    if rollback_result.successful
                    else LogLevel.ERROR
                ),
                "Execution rollback stage completed",
                request_id=request.request_id,
                action=request.action,
                rollback_status=rollback_result.status.value,
                simulated=rollback_result.simulated,
            )
            self._audit(
                request,
                AuditStage.ROLLBACK,
                rollback_result.status.value,
                plan_id=rollback_result.plan_id,
                successful=rollback_result.successful,
                simulated=rollback_result.simulated,
            )
            self._publish_result(
                self.EXECUTION_ROLLBACK_EVENT,
                verified_result,
            )

        if verification.passed:
            final_result = replace(
                verified_result,
                status=ExecutionStatus.SUCCEEDED,
                reason_code=verified_result.reason_code or "execution_completed",
            )
            final_stage = AuditStage.COMPLETED
            final_event = self.EXECUTION_COMPLETED_EVENT
            final_level = LogLevel.INFO
        else:
            dispatch_failed = dispatched.status is ExecutionStatus.FAILED
            final_result = replace(
                verified_result,
                status=ExecutionStatus.FAILED,
                message=(
                    dispatched.message if dispatch_failed else verification.message
                ),
                reason_code=(
                    dispatched.reason_code
                    if dispatch_failed and dispatched.reason_code
                    else verification.reason_code
                ),
            )
            final_stage = AuditStage.FAILED
            final_event = self.EXECUTION_FAILED_EVENT
            final_level = LogLevel.ERROR

        self._audit(
            request,
            final_stage,
            final_result.status.value,
            reason_code=final_result.reason_code,
            verified=verification.passed,
            rollback_simulated=(
                rollback_result.simulated if rollback_result is not None else False
            ),
        )
        final_result = self._attach_audit_entries(final_result)
        self._log(
            final_level,
            (
                "Execution lifecycle completed"
                if verification.passed
                else "Execution lifecycle failed"
            ),
            request_id=request.request_id,
            action=request.action,
            status=final_result.status.value,
            reason_code=final_result.reason_code,
        )
        self._publish_result(final_event, final_result)
        return final_result

    def _dispatch_safely(
        self,
        request: ExecutionRequest,
        authorization: ExecutionResult,
    ) -> ExecutionResult:
        """Invoke only the injected dispatcher and normalize its result."""

        assert self._dispatcher is not None
        try:
            result = self._dispatcher.dispatch(request)
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Execution dispatcher failed",
                request_id=request.request_id,
                action=request.action,
                error_type=type(error).__name__,
            )
            return self._dispatch_failure(
                request,
                authorization,
                reason_code="dispatch_failed",
                message="Execution dispatch failed safely.",
            )

        if not isinstance(result, ExecutionResult):
            return self._dispatch_failure(
                request,
                authorization,
                reason_code="invalid_dispatch_result",
                message="Execution dispatcher returned an invalid result.",
            )
        if result.request_id != request.request_id or result.action != request.action:
            return self._dispatch_failure(
                request,
                authorization,
                reason_code="dispatch_correlation_mismatch",
                message="Execution dispatcher returned an uncorrelated result.",
            )

        return replace(
            result,
            permission_level=result.permission_level or authorization.permission_level,
            dispatcher_invoked=True,
            risk_level=result.risk_level or authorization.risk_level,
            approval_decision=(
                result.approval_decision or authorization.approval_decision
            ),
            policy_decision=result.policy_decision or authorization.policy_decision,
        )

    @staticmethod
    def _dispatch_failure(
        request: ExecutionRequest,
        authorization: ExecutionResult,
        *,
        reason_code: str,
        message: str,
    ) -> ExecutionResult:
        """Build a typed failure retaining all authorization facts."""

        return ExecutionResult(
            request_id=request.request_id,
            action=request.action,
            status=ExecutionStatus.FAILED,
            message=message,
            permission_level=authorization.permission_level,
            reason_code=reason_code,
            executed=False,
            dispatcher_invoked=True,
            risk_level=authorization.risk_level,
            approval_decision=authorization.approval_decision,
            policy_decision=authorization.policy_decision,
        )

    def _verify_safely(
        self,
        result: ExecutionResult,
        expected_outcome: Any,
    ) -> VerificationReport:
        """Verify a result and convert verifier failures into a report."""

        try:
            report = self._verification_engine.verify(result, expected_outcome)
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Execution verification engine failed",
                request_id=result.request_id,
                action=result.action,
                error_type=type(error).__name__,
            )
            return VerificationReport(
                request_id=result.request_id,
                action=result.action,
                status=VerificationStatus.FAILED,
                completion_verified=False,
                outcome_verified=False,
                reason_code="verification_failed",
                message="Execution verification failed safely.",
                actual_outcome=(
                    result.output if isinstance(result.output, Mapping) else {}
                ),
            )

        if (
            not isinstance(report, VerificationReport)
            or report.request_id != result.request_id
            or report.action != result.action
        ):
            return VerificationReport(
                request_id=result.request_id,
                action=result.action,
                status=VerificationStatus.FAILED,
                completion_verified=False,
                outcome_verified=False,
                reason_code="invalid_verification_report",
                message="Verification engine returned an invalid report.",
                actual_outcome=(
                    result.output if isinstance(result.output, Mapping) else {}
                ),
            )
        return report

    def _rollback_safely(self, request: ExecutionRequest) -> RollbackResult:
        """Build and simulate rollback without allowing failures to escape."""

        plan_id = ""
        try:
            plan = self._rollback_manager.build_plan(request)
            plan_id = plan.plan_id
            result = self._rollback_manager.execute(plan)
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Execution rollback manager failed",
                request_id=request.request_id,
                action=request.action,
                error_type=type(error).__name__,
            )
            return RollbackResult(
                request_id=request.request_id,
                plan_id=plan_id,
                status=RollbackStatus.FAILED,
                successful=False,
                simulated=True,
                message="Rollback simulation failed safely.",
            )

        if (
            not isinstance(result, RollbackResult)
            or result.request_id != request.request_id
        ):
            return RollbackResult(
                request_id=request.request_id,
                plan_id=plan_id,
                status=RollbackStatus.FAILED,
                successful=False,
                simulated=True,
                message="Rollback manager returned an invalid result.",
            )
        return result

    def _audit(
        self,
        request: object,
        stage: AuditStage,
        outcome: str,
        **details: Any,
    ) -> None:
        """Record a lifecycle stage without changing gateway control flow."""

        context = self._request_context(request)
        try:
            self._audit_logger.record(
                request_id=context["request_id"],
                action=context["action"],
                stage=stage,
                outcome=outcome,
                details=details,
            )
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to record execution audit entry",
                **context,
                stage=stage.value,
                error_type=type(error).__name__,
            )

    def _attach_audit_entries(self, result: ExecutionResult) -> ExecutionResult:
        """Attach identifiers for all retained entries correlated to a result."""

        try:
            entry_ids = tuple(
                entry.entry_id
                for entry in self._audit_logger.for_request(result.request_id)
            )
        except Exception:
            return result
        return replace(result, audit_entry_ids=entry_ids)

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
        if result.verification_report is not None:
            payload["verification_status"] = (
                result.verification_report.status.value
            )
            payload["verification_reason_code"] = (
                result.verification_report.reason_code
            )
        if result.rollback_result is not None:
            payload["rollback_status"] = result.rollback_result.status.value
            payload["rollback_simulated"] = result.rollback_result.simulated
        if result.audit_entry_ids:
            payload["audit_entry_count"] = len(result.audit_entry_ids)
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


__all__ = [
    "DispatcherInterface",
    "EventPublisher",
    "ExecutionDispatcher",
    "TrustedExecutionGateway",
]
