"""Planning-only orchestration for the complete safe execution lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Any

from Core.execution.models import ExecutionRequest, PermissionLevel, RiskLevel
from Core.logger import LogLevel, Logger, NullLogger
from Execution.preview.models import ActionPreview, ExecutionReadiness
from Execution.preview.planner import PreviewPlanner
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
from Execution.session.queue import EventPublisher

from .events import (
    EXECUTION_CANCELLED_EVENT,
    EXECUTION_CREATED_EVENT,
    EXECUTION_FAILED_EVENT,
    EXECUTION_READY_EVENT,
    EXECUTION_VALIDATED_EVENT,
    CoordinatorEvents,
    LifecycleEventSink,
)
from .exceptions import (
    CoordinationNotFoundError,
    CoordinatorValidationError,
    DuplicateCoordinationError,
    InvalidStateTransitionError,
    PlanCreationError,
)
from .models import (
    ApprovalRecord,
    CoordinatorState,
    ExecutionCoordination,
    SafeExecutionPlan,
    StateTransition,
    ValidationReport,
)
from .readiness import ExecutionReadinessEvaluator
from .state_machine import ExecutionStateMachine
from .validator import CoordinatorValidator


class SafeExecutionCoordinator:
    """Coordinate validation, preview, risk, approval, readiness, and planning.

    This service has no dispatcher or execution-provider dependency.  Reaching
    :class:`CoordinatorState.READY` produces an immutable dry-run plan only.
    """

    def __init__(
        self,
        preview_planner: PreviewPlanner | None = None,
        state_machine: ExecutionStateMachine | None = None,
        validator: CoordinatorValidator | None = None,
        readiness_evaluator: ExecutionReadinessEvaluator | None = None,
        *,
        events: LifecycleEventSink | None = None,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
        available_permissions: Iterable[PermissionLevel] | None = None,
    ) -> None:
        """Initialize every collaborator through dependency injection."""

        self._logger = logger or NullLogger("narvis.execution.coordinator")
        self._clock = clock
        self._id_factory = id_factory
        self._state_machine = state_machine or ExecutionStateMachine()
        if validator is None:
            validator = CoordinatorValidator(
                available_permissions=(
                    tuple(available_permissions)
                    if available_permissions is not None
                    else tuple(PermissionLevel)
                ),
                clock=clock,
            )
        self._validator = validator
        self._available_permissions = (
            tuple(available_permissions)
            if available_permissions is not None
            else validator.available_permissions
        )
        if any(
            not isinstance(permission, PermissionLevel)
            for permission in self._available_permissions
        ):
            raise TypeError(
                "available_permissions must contain PermissionLevel members"
            )
        self._preview_planner = preview_planner or PreviewPlanner(
            event_bus=event_bus,
            logger=self._logger,
            clock=clock,
            id_factory=id_factory,
        )
        self._readiness_evaluator = readiness_evaluator or ExecutionReadinessEvaluator(
            validator,
            clock=clock,
        )
        self._events = events or CoordinatorEvents(
            event_bus,
            logger=self._logger,
        )
        self._coordinations: dict[str, ExecutionCoordination] = {}
        self._lock = RLock()

    @property
    def preview_planner(self) -> PreviewPlanner:
        """Return the injected preview planner."""

        return self._preview_planner

    @property
    def validator(self) -> CoordinatorValidator:
        """Return the injected coordinator validator."""

        return self._validator

    @property
    def readiness_evaluator(self) -> ExecutionReadinessEvaluator:
        """Return the injected readiness evaluator."""

        return self._readiness_evaluator

    @property
    def state_machine(self) -> ExecutionStateMachine:
        """Return the immutable lifecycle state machine."""

        return self._state_machine

    def coordinate(
        self,
        request: object,
        *,
        session: object,
        approval: ApprovalRecord | None = None,
        actions: Sequence[ActionPreview] | None = None,
        metadata: object = None,
        coordination_id: str | None = None,
    ) -> ExecutionCoordination:
        """Coordinate a request as far as validation and approval permit."""

        now = self._now()
        resolved_id = coordination_id or self._make_id()
        safe_metadata = self._safe_metadata(metadata)
        record = ExecutionCoordination(
            coordination_id=resolved_id,
            state=CoordinatorState.CREATED,
            request=request if isinstance(request, ExecutionRequest) else None,
            session=session if isinstance(session, ExecutionSession) else None,
            approval=approval if self._is_approval(approval) else None,
            metadata=safe_metadata,
            transitions=(
                StateTransition(
                    from_state=None,
                    to_state=CoordinatorState.CREATED,
                    reason="coordination_created",
                    transitioned_at=now,
                ),
            ),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            if resolved_id in self._coordinations:
                raise DuplicateCoordinationError(
                    f"execution coordination '{resolved_id}' already exists"
                )
            self._coordinations[resolved_id] = record
        self._log_lifecycle(record, "created")
        self._events.publish(EXECUTION_CREATED_EVENT, record)

        initial_validation = self._validator.validate_initial(
            request,
            session,
            metadata if metadata is not None else {},
            available_permissions=self._available_permissions,
        )
        record = self._store(replace(record, validation_report=initial_validation))
        if not initial_validation.valid:
            return self._fail(
                record,
                "initial coordinator validation failed",
                validation=initial_validation,
            )
        if approval is not None and not self._is_approval(approval):
            return self._fail(record, "unsupported approval model")

        record = self._transition(
            record,
            CoordinatorState.VALIDATED,
            reason="initial_validation_passed",
        )
        self._events.publish(
            EXECUTION_VALIDATED_EVENT,
            record,
            missing_requirements=(),
        )

        try:
            preview = self._preview_planner.generate(
                record.request,
                session=record.session,
                actions=actions,
                approval=approval,
                metadata=record.metadata,
            )
        except Exception as error:
            return self._fail(
                record,
                "preview generation failed",
                error_type=type(error).__name__,
            )

        record = self._store(
            replace(
                record,
                preview=preview,
                risk_analysis=preview.risk_analysis,
                approval=approval,
            )
        )
        record = self._transition(
            record,
            CoordinatorState.PREVIEW_READY,
            reason="execution_preview_created",
        )
        record = self._transition(
            record,
            CoordinatorState.RISK_ANALYZED,
            reason="preview_risk_analysis_available",
        )

        full_validation = self._validator.validate(
            record,
            available_permissions=self._available_permissions,
        )
        record = self._store(replace(record, validation_report=full_validation))
        if not full_validation.valid:
            return self._fail(
                record,
                "coordinator requirement validation failed",
                validation=full_validation,
            )
        return self._advance_readiness(record)

    def create(
        self,
        request: object,
        **kwargs: Any,
    ) -> ExecutionCoordination:
        """Return :meth:`coordinate` for concise callers."""

        return self.coordinate(request, **kwargs)

    def provide_approval(
        self,
        coordination_id: str,
        approval: ApprovalRecord,
    ) -> ExecutionCoordination:
        """Resume a waiting coordination with an existing approval model."""

        if not self._is_approval(approval):
            raise CoordinatorValidationError(
                "approval must use an existing approval model"
            )
        with self._lock:
            record = self._require_coordination(coordination_id)
            if record.state is not CoordinatorState.WAITING_FOR_APPROVAL:
                raise InvalidStateTransitionError(
                    "approval can be provided only while waiting for approval"
                )
            self._validate_approval_binding(record, approval)
            try:
                preview = self._preview_planner.revise(
                    record.preview,
                    approval=approval,
                )
            except Exception as error:
                return self._fail(
                    record,
                    "approval preview update failed",
                    error_type=type(error).__name__,
                )
            record = self._store(
                replace(
                    record,
                    preview=preview,
                    risk_analysis=preview.risk_analysis,
                    approval=approval,
                )
            )
            validation = self._validator.validate(
                record,
                available_permissions=self._available_permissions,
            )
            record = self._store(replace(record, validation_report=validation))
            if not validation.valid:
                return self._fail(
                    record,
                    "approval coordination validation failed",
                    validation=validation,
                )
            return self._advance_readiness(record)

    def resume(
        self,
        coordination_id: str,
        approval: ApprovalRecord,
    ) -> ExecutionCoordination:
        """Return :meth:`provide_approval` for resume-oriented callers."""

        return self.provide_approval(coordination_id, approval)

    def approve(
        self,
        coordination_id: str,
        approval: ApprovalRecord = ApprovalStatus.APPROVED,
    ) -> ExecutionCoordination:
        """Resume using an explicit approved model or status."""

        return self.provide_approval(coordination_id, approval)

    def cancel(
        self,
        coordination_id: str,
        *,
        reason: str = "coordination_cancelled",
    ) -> ExecutionCoordination:
        """Cancel a non-terminal coordination without executing its plan."""

        with self._lock:
            record = self._require_coordination(coordination_id)
            return self._cancel_record(record, reason=reason)

    def build_plan(
        self,
        coordination: ExecutionCoordination,
    ) -> SafeExecutionPlan:
        """Build an immutable dry-run plan from a ready coordination snapshot."""

        if not isinstance(coordination, ExecutionCoordination):
            raise TypeError("build_plan requires an ExecutionCoordination")
        report = coordination.readiness_report
        preview = coordination.preview
        session = coordination.session
        if report is None or not report.ready or preview is None or session is None:
            raise PlanCreationError(
                "a complete ready preview and active session are required"
            )
        return SafeExecutionPlan(
            coordination_id=coordination.coordination_id,
            request_id=coordination.request_id,
            preview_id=preview.preview_id,
            session_id=session.session_id,
            actions=preview.actions,
            required_permissions=preview.required_permissions,
            estimated_duration=preview.estimated_duration,
            rollback_available=preview.summary.rollback_available,
            metadata=coordination.metadata,
            plan_id=self._make_id(),
            created_at=self._now(),
        )

    def get_coordination(self, coordination_id: str) -> ExecutionCoordination:
        """Return one retained immutable coordination snapshot."""

        with self._lock:
            return self._require_coordination(coordination_id)

    def get(self, coordination_id: str) -> ExecutionCoordination:
        """Return :meth:`get_coordination` for concise callers."""

        return self.get_coordination(coordination_id)

    def list_coordinations(self) -> tuple[ExecutionCoordination, ...]:
        """Return retained coordination snapshots in creation order."""

        with self._lock:
            return tuple(self._coordinations.values())

    def _advance_readiness(
        self,
        record: ExecutionCoordination,
    ) -> ExecutionCoordination:
        """Advance from risk or approval state to waiting, cancelled, failed, or ready."""

        try:
            report = self._readiness_evaluator.generate(
                record,
                validation_report=record.validation_report,
                available_permissions=self._available_permissions,
            )
        except Exception as error:
            return self._fail(
                record,
                "readiness generation failed",
                error_type=type(error).__name__,
            )
        record = self._store(replace(record, readiness_report=report))

        if report.approval_status in {
            ApprovalStatus.DENIED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        }:
            return self._cancel_record(
                record,
                reason=f"approval_{report.approval_status.value}",
            )
        if report.risk_level is RiskLevel.CRITICAL:
            return self._fail(record, "critical risk blocks execution readiness")
        if report.readiness is ExecutionReadiness.APPROVAL_REQUIRED:
            if record.state is CoordinatorState.WAITING_FOR_APPROVAL:
                return record
            return self._transition(
                record,
                CoordinatorState.WAITING_FOR_APPROVAL,
                reason="approval_required",
            )
        if not report.ready:
            return self._fail(record, "execution readiness requirements are missing")

        if report.approval_status is ApprovalStatus.APPROVED and record.state in {
            CoordinatorState.RISK_ANALYZED,
            CoordinatorState.WAITING_FOR_APPROVAL,
        }:
            record = self._transition(
                record,
                CoordinatorState.APPROVED,
                reason="approval_confirmed",
            )
        try:
            plan = self.build_plan(record)
        except Exception as error:
            return self._fail(
                record,
                "execution plan creation failed",
                error_type=type(error).__name__,
            )
        record = self._transition(
            record,
            CoordinatorState.READY,
            reason="execution_plan_ready",
        )
        record = self._store(replace(record, plan=plan))
        self._events.publish(
            EXECUTION_READY_EVENT,
            record,
            readiness_score=report.execution_readiness_score,
            action_count=len(plan.actions),
        )
        self._log_lifecycle(record, "ready")
        return record

    def _transition(
        self,
        record: ExecutionCoordination,
        target: CoordinatorState,
        *,
        reason: str,
    ) -> ExecutionCoordination:
        """Apply, retain, and log one immutable state transition."""

        transitioned = self._state_machine.transition(
            record,
            target,
            reason=reason,
            at=self._now(),
        )
        transitioned = self._store(transitioned)
        self._log_lifecycle(
            transitioned,
            "state_transition",
            previous_state=record.state.value,
            reason=reason,
        )
        return transitioned

    def _fail(
        self,
        record: ExecutionCoordination,
        reason: str,
        *,
        validation: ValidationReport | None = None,
        **context: object,
    ) -> ExecutionCoordination:
        """Transition to FAILED and publish a safe failure event."""

        if record.state is CoordinatorState.FAILED:
            return record
        failed = self._transition(
            record,
            CoordinatorState.FAILED,
            reason=reason,
        )
        failed = self._store(
            replace(
                failed,
                failure_reason=reason,
                validation_report=validation or failed.validation_report,
            )
        )
        self._log_lifecycle(
            failed,
            "failed",
            level=LogLevel.ERROR,
            reason=reason,
            **context,
        )
        self._events.publish(
            EXECUTION_FAILED_EVENT,
            failed,
            reason=reason,
            **context,
        )
        return failed

    def _cancel_record(
        self,
        record: ExecutionCoordination,
        *,
        reason: str,
    ) -> ExecutionCoordination:
        """Transition a non-terminal record to CANCELLED."""

        if record.state in {CoordinatorState.CANCELLED, CoordinatorState.FAILED}:
            raise InvalidStateTransitionError(
                f"cannot cancel coordination in {record.state.value} state"
            )
        cancelled = self._transition(
            record,
            CoordinatorState.CANCELLED,
            reason=reason,
        )
        self._events.publish(
            EXECUTION_CANCELLED_EVENT,
            cancelled,
            reason=reason,
        )
        self._log_lifecycle(cancelled, "cancelled", reason=reason)
        return cancelled

    def _validate_approval_binding(
        self,
        record: ExecutionCoordination,
        approval: ApprovalRecord,
    ) -> None:
        """Require all available request and session approval bindings to match."""

        original = record.approval
        expected_approval_id = (
            original.request_id
            if isinstance(original, (ApprovalRequest, ApprovalResponse, ApprovalToken))
            else ""
        )
        supplied_id = (
            approval.request_id
            if isinstance(approval, (ApprovalRequest, ApprovalResponse, ApprovalToken))
            else ""
        )
        if expected_approval_id and supplied_id and supplied_id != expected_approval_id:
            raise CoordinatorValidationError(
                "approval belongs to another approval request"
            )
        if isinstance(approval, ApprovalRequest):
            if approval.execution_request_id != record.request_id:
                raise CoordinatorValidationError(
                    "approval belongs to another execution request"
                )
            if approval.session_id != record.session_id:
                raise CoordinatorValidationError(
                    "approval belongs to another execution session"
                )
        token = (
            approval.token
            if isinstance(approval, ApprovalResponse)
            else approval if isinstance(approval, ApprovalToken) else None
        )
        if token is not None and token.session_id != record.session_id:
            raise CoordinatorValidationError(
                "approval token belongs to another execution session"
            )

    def _require_coordination(self, coordination_id: str) -> ExecutionCoordination:
        """Return one retained record or raise a typed lookup error."""

        if not isinstance(coordination_id, str) or not coordination_id:
            raise CoordinationNotFoundError("a non-empty coordination_id is required")
        try:
            return self._coordinations[coordination_id]
        except KeyError as error:
            raise CoordinationNotFoundError(
                f"execution coordination '{coordination_id}' was not found"
            ) from error

    def _store(self, record: ExecutionCoordination) -> ExecutionCoordination:
        """Retain one immutable snapshot under its stable identifier."""

        with self._lock:
            self._coordinations[record.coordination_id] = record
        return record

    @staticmethod
    def _safe_metadata(metadata: object) -> Mapping[str, Any]:
        """Return detached valid metadata or an empty mapping for failed records."""

        if metadata is None:
            return {}
        if not isinstance(metadata, Mapping):
            return {}
        try:
            return immutable_mapping(metadata)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _is_approval(value: object) -> bool:
        """Return whether a value is one of the existing approval models."""

        return isinstance(
            value,
            (ApprovalRequest, ApprovalResponse, ApprovalStatus, ApprovalToken),
        )

    def _log_lifecycle(
        self,
        record: ExecutionCoordination,
        outcome: str,
        *,
        level: LogLevel = LogLevel.INFO,
        **context: object,
    ) -> None:
        """Write one structured coordinator lifecycle log entry."""

        self._log(
            level,
            f"Safe execution coordination {outcome}",
            coordination_id=record.coordination_id,
            request_id=record.request_id,
            session_id=record.session_id,
            state=record.state.value,
            dry_run=True,
            executed=False,
            dispatcher_invoked=False,
            **context,
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failure to alter coordination."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise CoordinatorValidationError(
                "coordinator clock must return an aware datetime"
            )
        return value

    def _make_id(self) -> str:
        """Return and validate an injected opaque identifier."""

        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise CoordinatorValidationError(
                "id_factory must return normalized non-empty text"
            )
        return value


ExecutionCoordinator = SafeExecutionCoordinator
Coordinator = SafeExecutionCoordinator


__all__ = [
    "Coordinator",
    "ExecutionCoordinator",
    "SafeExecutionCoordinator",
]
