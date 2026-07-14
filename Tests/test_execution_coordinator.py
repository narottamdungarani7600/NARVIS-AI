"""Comprehensive tests for Phase 11 Safe Execution Layer Sprint 3."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.execution import ExecutionRequest
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Execution.coordinator import (
    CoordinationNotFoundError,
    CoordinatorState,
    CoordinatorValidationError,
    DuplicateCoordinationError,
    ExecutionCoordination,
    ExecutionReadinessEvaluator,
    ExecutionStateMachine,
    InvalidStateTransitionError,
    SafeExecutionCoordinator,
    StateTransition,
)
from Execution.coordinator.validator import CoordinatorValidator
from Execution.preview import (
    ActionPreview,
    ExecutionReadiness,
    PermissionLevel,
    PreviewPlanner,
    RiskLevel,
)
from Execution.session import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ExecutionSession,
    SessionStatus,
)


class _Clock:
    """Mutable aware clock for deterministic coordinator tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 14, 15, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _CapturingLogger:
    """Core-compatible structured logger double."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _FailingPreviewPlanner:
    """Planner double used to verify coordinator failure handling."""

    def generate(self, request: ExecutionRequest, **kwargs: object) -> object:
        raise RuntimeError("preview unavailable")


def _session(
    clock: _Clock,
    *,
    session_id: str = "session-001",
    status: SessionStatus = SessionStatus.ACTIVE,
    expires_in: timedelta = timedelta(minutes=10),
) -> ExecutionSession:
    return ExecutionSession(
        session_id=session_id,
        owner_id="operator",
        created_at=clock.now,
        expires_at=clock.now + expires_in,
        status=status,
        metadata={"channel": {"name": "test"}},
    )


def _request(
    *,
    action: str = "system.inspect_status",
    permission: PermissionLevel = PermissionLevel.READ_ONLY,
    rollback: bool = True,
) -> ExecutionRequest:
    return ExecutionRequest(
        action=action,
        permission_level=permission,
        metadata={
            "estimated_duration_seconds": 2,
            "rollback_available": rollback,
        },
    )


def _record(clock: _Clock) -> ExecutionCoordination:
    return ExecutionCoordination(
        coordination_id="coordination-001",
        state=CoordinatorState.CREATED,
        request=_request(),
        session=_session(clock),
        transitions=(
            StateTransition(
                from_state=None,
                to_state=CoordinatorState.CREATED,
                reason="created",
                transitioned_at=clock.now,
            ),
        ),
        created_at=clock.now,
        updated_at=clock.now,
    )


class CoordinatorStateMachineTests(unittest.TestCase):
    """Verify immutable valid and invalid coordinator state transitions."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.machine = ExecutionStateMachine()

    def test_supported_states_match_the_phase_contract(self) -> None:
        self.assertEqual(
            {state.name for state in CoordinatorState},
            {
                "CREATED",
                "VALIDATED",
                "PREVIEW_READY",
                "RISK_ANALYZED",
                "WAITING_FOR_APPROVAL",
                "APPROVED",
                "READY",
                "CANCELLED",
                "FAILED",
            },
        )

    def test_transition_returns_new_snapshot_and_retains_history(self) -> None:
        original = _record(self.clock)

        validated = self.machine.transition(
            original,
            CoordinatorState.VALIDATED,
            reason="validated",
            at=self.clock.now,
        )

        self.assertIs(original.state, CoordinatorState.CREATED)
        self.assertIs(validated.state, CoordinatorState.VALIDATED)
        self.assertEqual(len(original.transitions), 1)
        self.assertEqual(len(validated.transitions), 2)
        self.assertIs(
            validated.transitions[-1].from_state,
            CoordinatorState.CREATED,
        )
        with self.assertRaises(FrozenInstanceError):
            validated.state = CoordinatorState.READY  # type: ignore[misc]

    def test_invalid_skipped_and_terminal_transitions_are_rejected(self) -> None:
        record = _record(self.clock)
        with self.assertRaises(InvalidStateTransitionError):
            self.machine.transition(
                record,
                CoordinatorState.READY,
                reason="skip",
                at=self.clock.now,
            )
        failed = self.machine.transition(
            record,
            CoordinatorState.FAILED,
            reason="failed",
            at=self.clock.now,
        )
        with self.assertRaises(InvalidStateTransitionError):
            self.machine.transition(
                failed,
                CoordinatorState.CREATED,
                reason="restart",
                at=self.clock.now,
            )

    def test_waiting_may_approve_or_cancel_but_not_skip_backwards(self) -> None:
        record = _record(self.clock)
        for target in (
            CoordinatorState.VALIDATED,
            CoordinatorState.PREVIEW_READY,
            CoordinatorState.RISK_ANALYZED,
            CoordinatorState.WAITING_FOR_APPROVAL,
        ):
            record = self.machine.transition(
                record,
                target,
                reason=target.value,
                at=self.clock.now,
            )

        self.assertTrue(
            self.machine.can_transition(record.state, CoordinatorState.APPROVED)
        )
        self.assertTrue(
            self.machine.can_transition(record.state, CoordinatorState.CANCELLED)
        )
        self.assertFalse(
            self.machine.can_transition(record.state, CoordinatorState.VALIDATED)
        )


class CoordinatorValidatorTests(unittest.TestCase):
    """Verify all required preview, risk, session, permission, and metadata checks."""

    def setUp(self) -> None:
        self.clock = _Clock()

    def test_initial_validation_accepts_active_typed_requirements(self) -> None:
        validator = CoordinatorValidator(
            available_permissions=(PermissionLevel.STANDARD,),
            clock=self.clock,
        )

        report = validator.validate_initial(
            _request(permission=PermissionLevel.READ_ONLY),
            _session(self.clock),
            {"trace": {"steps": [1, 2]}},
        )

        self.assertTrue(report.valid)
        self.assertEqual(report.missing_requirements, ())

    def test_full_validation_requires_preview_and_risk(self) -> None:
        validator = CoordinatorValidator(clock=self.clock)

        report = validator.validate(
            request=_request(),
            approval_session=_session(self.clock),
            metadata={},
        )

        self.assertFalse(report.valid)
        self.assertIn("preview", report.missing_requirements)
        self.assertIn("risk_analysis", report.missing_requirements)

    def test_inactive_or_expired_session_is_rejected(self) -> None:
        validator = CoordinatorValidator(clock=self.clock)
        inactive = _session(self.clock, status=SessionStatus.CLOSED)

        report = validator.validate_initial(_request(), inactive, {})

        self.assertFalse(report.valid)
        self.assertIn("active_session", report.missing_requirements)

    def test_higher_permission_satisfies_lower_and_missing_permission_is_reported(
        self,
    ) -> None:
        validator = CoordinatorValidator(
            available_permissions=(PermissionLevel.READ_ONLY,),
            clock=self.clock,
        )

        self.assertTrue(validator.permission_available(PermissionLevel.READ_ONLY))
        self.assertFalse(validator.permission_available(PermissionLevel.ELEVATED))
        report = validator.validate_initial(
            _request(permission=PermissionLevel.ELEVATED),
            _session(self.clock),
            {},
        )
        self.assertIn(
            "permission:elevated",
            report.missing_requirements,
        )

    def test_invalid_metadata_and_preview_session_binding_are_rejected(self) -> None:
        validator = CoordinatorValidator(clock=self.clock)
        session = _session(self.clock)
        request = _request()
        preview = PreviewPlanner(clock=self.clock).generate(
            request,
            session=session,
        )

        metadata_report = validator.validate_initial(
            request,
            session,
            {1: "invalid"},  # type: ignore[dict-item]
        )
        binding_report = validator.validate(
            request=request,
            preview=replace(preview, session_id="different-session"),
            risk_analysis=preview.risk_analysis,
            approval_session=session,
            metadata={},
        )

        self.assertIn("metadata", metadata_report.missing_requirements)
        self.assertFalse(binding_report.valid)
        self.assertTrue(
            any("another execution session" in error for error in binding_report.errors)
        )


class CoordinatorReadinessTests(unittest.TestCase):
    """Verify readiness facts, scoring, approval, risk, and missing requirements."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.validator = CoordinatorValidator(clock=self.clock)
        self.evaluator = ExecutionReadinessEvaluator(
            self.validator,
            clock=self.clock,
        )

    def test_waiting_report_contains_all_requested_summary_facts(self) -> None:
        coordinator = SafeExecutionCoordinator(clock=self.clock)
        result = coordinator.coordinate(
            _request(
                action="application.open",
                permission=PermissionLevel.STANDARD,
                rollback=False,
            ),
            session=_session(self.clock),
        )

        report = result.readiness_report

        self.assertTrue(result.waiting_for_approval)
        self.assertIn("approval_required", report.missing_requirements)
        self.assertIsNone(report.approval_status)
        self.assertIs(report.risk_level, RiskLevel.MEDIUM)
        self.assertEqual(report.estimated_duration, timedelta(seconds=2))
        self.assertFalse(report.rollback_available)
        self.assertGreaterEqual(report.execution_readiness_score, 0)
        self.assertLessEqual(report.execution_readiness_score, 100)

    def test_approved_report_is_ready(self) -> None:
        coordinator = SafeExecutionCoordinator(clock=self.clock)
        result = coordinator.coordinate(
            _request(
                action="application.open",
                permission=PermissionLevel.STANDARD,
                rollback=False,
            ),
            session=_session(self.clock),
            approval=ApprovalStatus.APPROVED,
        )

        self.assertTrue(result.readiness_report.ready)
        self.assertIs(
            result.readiness_report.approval_status,
            ApprovalStatus.APPROVED,
        )

    def test_missing_preview_and_risk_are_exposed(self) -> None:
        record = _record(self.clock)

        report = self.evaluator.generate(record)

        self.assertIs(report.readiness, ExecutionReadiness.BLOCKED)
        self.assertIn("preview", report.missing_requirements)
        self.assertIn("risk_analysis", report.missing_requirements)

    def test_denied_approval_is_blocked(self) -> None:
        coordinator = SafeExecutionCoordinator(clock=self.clock)
        waiting = coordinator.coordinate(
            _request(
                action="application.open",
                permission=PermissionLevel.STANDARD,
                rollback=False,
            ),
            session=_session(self.clock),
        )
        denied = coordinator.provide_approval(
            waiting.coordination_id,
            ApprovalStatus.DENIED,
        )

        self.assertTrue(denied.cancelled)
        self.assertIs(
            denied.readiness_report.readiness,
            ExecutionReadiness.BLOCKED,
        )

    def test_critical_risk_reduces_score_and_blocks_readiness(self) -> None:
        coordinator = SafeExecutionCoordinator(clock=self.clock)

        result = coordinator.coordinate(
            _request(
                action="system.shutdown",
                permission=PermissionLevel.STANDARD,
            ),
            session=_session(self.clock),
            approval=ApprovalStatus.APPROVED,
        )

        self.assertTrue(result.failed)
        self.assertIs(
            result.readiness_report.risk_level,
            RiskLevel.CRITICAL,
        )
        self.assertIn(
            "critical_risk",
            result.readiness_report.missing_requirements,
        )


class SafeExecutionCoordinatorLifecycleTests(unittest.TestCase):
    """Verify complete lifecycle, failures, events, logs, and no-execution safety."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "execution.created",
            "execution.validated",
            "execution.ready",
            "execution.cancelled",
            "execution.failed",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.coordinator = SafeExecutionCoordinator(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )

    def test_low_risk_lifecycle_reaches_ready_with_inert_plan(self) -> None:
        result = self.coordinator.coordinate(
            _request(),
            session=_session(self.clock),
            metadata={"correlation": "conversation-001"},
        )

        self.assertTrue(result.ready)
        self.assertEqual(
            [transition.to_state for transition in result.transitions],
            [
                CoordinatorState.CREATED,
                CoordinatorState.VALIDATED,
                CoordinatorState.PREVIEW_READY,
                CoordinatorState.RISK_ANALYZED,
                CoordinatorState.READY,
            ],
        )
        self.assertTrue(result.plan.dry_run)
        self.assertTrue(result.plan.ready)
        self.assertFalse(result.plan.executed)
        self.assertFalse(result.plan.dispatcher_invoked)
        self.assertEqual(result.plan.actions, result.preview.actions)
        self.assertFalse(hasattr(self.coordinator, "execute"))

    def test_medium_risk_pauses_then_approval_resumes_to_ready(self) -> None:
        request = _request(
            action="application.open",
            permission=PermissionLevel.STANDARD,
            rollback=False,
        )
        session = _session(self.clock)
        approval_request = ApprovalRequest(
            execution_request=request,
            session_id=session.session_id,
            requested_by="planner",
            requested_at=self.clock.now,
            expires_at=self.clock.now + timedelta(minutes=5),
        )
        waiting = self.coordinator.coordinate(
            request,
            session=session,
            approval=approval_request,
        )

        approved = self.coordinator.provide_approval(
            waiting.coordination_id,
            ApprovalResponse(
                request_id=approval_request.request_id,
                decision=ApprovalDecision.APPROVE,
                responded_by="operator",
                responded_at=self.clock.now,
            ),
        )

        self.assertTrue(waiting.waiting_for_approval)
        self.assertTrue(approved.ready)
        self.assertIn(
            CoordinatorState.APPROVED,
            [transition.to_state for transition in approved.transitions],
        )
        self.assertEqual(
            self.coordinator.get(waiting.coordination_id),
            approved,
        )

    def test_denied_approval_cancels_coordination(self) -> None:
        waiting = self.coordinator.coordinate(
            _request(
                action="application.open",
                permission=PermissionLevel.STANDARD,
                rollback=False,
            ),
            session=_session(self.clock),
        )

        cancelled = self.coordinator.provide_approval(
            waiting.coordination_id,
            ApprovalStatus.DENIED,
        )

        self.assertTrue(cancelled.cancelled)
        self.assertIn("execution.cancelled", [event.name for event in self.events])
        self.assertIsNone(cancelled.plan)

    def test_explicit_cancel_works_before_or_after_ready(self) -> None:
        ready = self.coordinator.coordinate(
            _request(),
            session=_session(self.clock),
        )

        cancelled = self.coordinator.cancel(
            ready.coordination_id,
            reason="operator_cancelled",
        )

        self.assertTrue(cancelled.cancelled)
        self.assertIsNotNone(cancelled.plan)
        with self.assertRaises(InvalidStateTransitionError):
            self.coordinator.cancel(cancelled.coordination_id)

    def test_invalid_request_metadata_and_session_fail_closed(self) -> None:
        invalid_request = self.coordinator.coordinate(
            object(),
            session=_session(self.clock),
        )
        invalid_metadata = self.coordinator.coordinate(
            _request(),
            session=_session(self.clock, session_id="session-002"),
            metadata=[],
        )
        expired_session = self.coordinator.coordinate(
            _request(),
            session=_session(
                self.clock,
                session_id="session-003",
                status=SessionStatus.EXPIRED,
            ),
        )

        self.assertTrue(invalid_request.failed)
        self.assertTrue(invalid_metadata.failed)
        self.assertTrue(expired_session.failed)
        self.assertEqual(
            [event.name for event in self.events].count("execution.failed"),
            3,
        )

    def test_missing_permission_fails_validation(self) -> None:
        coordinator = SafeExecutionCoordinator(
            available_permissions=(PermissionLevel.READ_ONLY,),
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )

        result = coordinator.coordinate(
            _request(permission=PermissionLevel.ELEVATED),
            session=_session(self.clock),
        )

        self.assertTrue(result.failed)
        self.assertIn(
            "permission:elevated",
            result.validation_report.missing_requirements,
        )

    def test_preview_failure_transitions_to_failed_and_logs_error(self) -> None:
        coordinator = SafeExecutionCoordinator(
            preview_planner=_FailingPreviewPlanner(),  # type: ignore[arg-type]
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )

        result = coordinator.coordinate(
            _request(),
            session=_session(self.clock),
        )

        self.assertTrue(result.failed)
        self.assertEqual(result.failure_reason, "preview generation failed")
        self.assertTrue(
            any(level is LogLevel.ERROR for level, _, _ in self.logger.entries)
        )

    def test_events_are_ordered_safe_and_do_not_expose_parameters(self) -> None:
        secret = "do-not-publish"
        request = _request()
        request = replace(request, parameters={"secret": secret})

        result = self.coordinator.coordinate(
            request,
            session=_session(self.clock),
        )

        self.assertTrue(result.ready)
        self.assertEqual(
            [event.name for event in self.events],
            ["execution.created", "execution.validated", "execution.ready"],
        )
        self.assertTrue(all(not event.payload["executed"] for event in self.events))
        self.assertTrue(all(secret not in repr(event.payload) for event in self.events))

    def test_structured_lifecycle_logging_covers_created_transitions_and_ready(
        self,
    ) -> None:
        result = self.coordinator.coordinate(
            _request(),
            session=_session(self.clock),
        )

        messages = [message for _, message, _ in self.logger.entries]
        self.assertIn("Safe execution coordination created", messages)
        self.assertIn("Safe execution coordination state_transition", messages)
        self.assertIn("Safe execution coordination ready", messages)
        coordinator_entries = [
            context
            for _, message, context in self.logger.entries
            if message.startswith("Safe execution coordination")
        ]
        self.assertTrue(
            all(context["executed"] is False for context in coordinator_entries)
        )
        self.assertEqual(
            coordinator_entries[-1]["coordination_id"],
            result.coordination_id,
        )

    def test_mismatched_approval_and_invalid_resume_state_are_rejected(self) -> None:
        request = _request(
            action="application.open",
            permission=PermissionLevel.STANDARD,
        )
        session = _session(self.clock)
        approval_request = ApprovalRequest(
            execution_request=request,
            session_id=session.session_id,
            requested_by="planner",
            requested_at=self.clock.now,
            expires_at=self.clock.now + timedelta(minutes=5),
        )
        waiting = self.coordinator.coordinate(
            request,
            session=session,
            approval=approval_request,
        )

        with self.assertRaises(CoordinatorValidationError):
            self.coordinator.provide_approval(
                waiting.coordination_id,
                ApprovalResponse(
                    request_id="different-approval",
                    decision=ApprovalDecision.APPROVE,
                    responded_by="operator",
                    responded_at=self.clock.now,
                ),
            )
        approved = self.coordinator.approve(waiting.coordination_id)
        with self.assertRaises(InvalidStateTransitionError):
            self.coordinator.approve(approved.coordination_id)

    def test_duplicate_lookup_and_list_operations_are_typed(self) -> None:
        first = self.coordinator.coordinate(
            _request(),
            session=_session(self.clock),
            coordination_id="coordination-001",
        )

        with self.assertRaises(DuplicateCoordinationError):
            self.coordinator.coordinate(
                _request(),
                session=_session(self.clock, session_id="session-002"),
                coordination_id="coordination-001",
            )
        with self.assertRaises(CoordinationNotFoundError):
            self.coordinator.get_coordination("missing")
        self.assertEqual(self.coordinator.list_coordinations(), (first,))

    def test_event_subscriber_failure_does_not_change_ready_state(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "execution.ready",
            lambda event: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        coordinator = SafeExecutionCoordinator(
            event_bus=bus,
            logger=self.logger,
            clock=self.clock,
        )

        result = coordinator.coordinate(
            _request(),
            session=_session(self.clock),
        )

        self.assertTrue(result.ready)
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in self.logger.entries)
        )


if __name__ == "__main__":
    unittest.main()
