"""Comprehensive tests for Phase 11 safe execution session Sprint 1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.execution import ExecutionRequest, ExecutionResult, ExecutionStatus
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Execution.session import (
    ApprovalDecision,
    ApprovalExpiredError,
    ApprovalManager,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    DuplicateApprovalError,
    DuplicateQueueItemError,
    DuplicateSessionError,
    ExecutionHistoryEntry,
    ExecutionQueue,
    ExecutionSessionManager,
    GatewayAuthorizationError,
    InvalidApprovalError,
    QueueEmptyError,
    QueueItemNotFoundError,
    SessionExpiredError,
    SessionStatus,
)


class _Clock:
    """Mutable aware clock for deterministic lifecycle tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _CapturingLogger:
    """Core logger test double."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _Gateway:
    """Authorization-only gateway double that fails if execution is attempted."""

    def __init__(
        self,
        status: ExecutionStatus = ExecutionStatus.PENDING,
        *,
        executed: bool = False,
        dispatcher_invoked: bool = False,
    ) -> None:
        self.status = status
        self.executed = executed
        self.dispatcher_invoked = dispatcher_invoked
        self.authorized: list[ExecutionRequest] = []
        self.execute_called = False

    def authorize(self, request: ExecutionRequest) -> ExecutionResult:
        self.authorized.append(request)
        return ExecutionResult(
            request_id=request.request_id,
            action=request.action,
            status=self.status,
            message="Planning decision only.",
            reason_code="approval_required",
            executed=self.executed,
            dispatcher_invoked=self.dispatcher_invoked,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.execute_called = True
        raise AssertionError("safe execution sessions must never execute")


class _FailingGateway:
    def authorize(self, request: ExecutionRequest) -> ExecutionResult:
        raise RuntimeError("gateway unavailable")


def _approval_request(
    clock: _Clock,
    *,
    request_id: str = "approval-001",
    session_id: str = "session-001",
) -> ApprovalRequest:
    return ApprovalRequest(
        execution_request=ExecutionRequest(
            action="application.open",
            parameters={"application": "calculator"},
        ),
        session_id=session_id,
        requested_by="planner",
        request_id=request_id,
        requested_at=clock.now,
        expires_at=clock.now + timedelta(minutes=5),
        metadata={"trace": {"steps": [1, 2]}},
    )


class ApprovalModelTests(unittest.TestCase):
    """Verify immutable, strongly typed planning models."""

    def setUp(self) -> None:
        self.clock = _Clock()

    def test_request_detaches_nested_metadata_and_execution_parameters(self) -> None:
        parameters = {"options": {"flags": ["safe"]}}
        metadata = {"trace": {"steps": [1]}}
        request = ApprovalRequest(
            execution_request=ExecutionRequest(
                action="system.inspect_status",
                parameters=parameters,
            ),
            session_id="session-001",
            requested_by="planner",
            metadata=metadata,
            requested_at=self.clock.now,
            expires_at=self.clock.now + timedelta(minutes=1),
        )
        parameters["options"]["flags"].append("unsafe")
        metadata["trace"]["steps"].append(2)

        self.assertEqual(
            request.execution_request.parameters["options"]["flags"], ("safe",)
        )
        self.assertEqual(request.metadata["trace"]["steps"], (1,))
        with self.assertRaises(TypeError):
            request.metadata["new"] = True  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            request.status = ApprovalStatus.APPROVED  # type: ignore[misc]

    def test_request_rejects_invalid_types_and_expiry(self) -> None:
        with self.assertRaises(TypeError):
            ApprovalRequest(  # type: ignore[arg-type]
                execution_request=object(),
                session_id="session-001",
                requested_by="planner",
            )
        with self.assertRaises(ValueError):
            replace(
                _approval_request(self.clock),
                expires_at=self.clock.now,
            )
        with self.assertRaises(ValueError):
            replace(
                _approval_request(self.clock),
                requested_at=datetime(2026, 7, 14, 9, 0),
            )

    def test_response_and_history_are_typed_and_never_executed(self) -> None:
        response = ApprovalResponse(
            request_id="approval-001",
            decision=ApprovalDecision.APPROVE,
            responded_by="operator",
            responded_at=self.clock.now,
        )

        self.assertTrue(response.approved)
        self.assertIs(response.status, ApprovalStatus.APPROVED)
        with self.assertRaises(TypeError):
            replace(response, decision="approve")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ExecutionHistoryEntry(
                request_id="approval-001",
                action="application.open",
                approval_status=ApprovalStatus.APPROVED,
                executed=True,
            )


class ExecutionQueueTests(unittest.TestCase):
    """Verify FIFO state, cancellation, status, events, and validation."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        self.bus.subscribe("queue.updated", self.events.append)
        self.bus.subscribe("execution.cancelled", self.events.append)
        self.queue = ExecutionQueue(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )

    def test_enqueue_peek_dequeue_and_status_are_fifo(self) -> None:
        first = _approval_request(self.clock, request_id="approval-001")
        second = _approval_request(self.clock, request_id="approval-002")

        self.queue.enqueue(first)
        self.queue.enqueue(second)

        self.assertEqual(self.queue.peek(), first)
        self.assertEqual(
            self.queue.status().request_ids,
            ("approval-001", "approval-002"),
        )
        self.assertEqual(self.queue.dequeue(), first)
        self.assertEqual(self.queue.peek(), second)
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(
            [event.payload["operation"] for event in self.events],
            ["enqueue", "enqueue", "dequeue"],
        )

    def test_empty_queue_operations_raise_typed_errors(self) -> None:
        with self.assertRaises(QueueEmptyError):
            self.queue.peek()
        with self.assertRaises(QueueEmptyError):
            self.queue.dequeue()
        with self.assertRaises(QueueItemNotFoundError):
            self.queue.cancel("missing")

    def test_duplicate_and_non_pending_requests_are_rejected(self) -> None:
        request = _approval_request(self.clock)
        self.queue.enqueue(request)
        with self.assertRaises(DuplicateQueueItemError):
            self.queue.enqueue(request)
        with self.assertRaises(ValueError):
            self.queue.enqueue(
                replace(request, request_id="other", status=ApprovalStatus.DENIED)
            )

    def test_cancel_publishes_event_and_logs_without_execution(self) -> None:
        request = _approval_request(self.clock)
        self.queue.enqueue(request)

        cancelled = self.queue.cancel(request.request_id)

        self.assertIs(cancelled.status, ApprovalStatus.CANCELLED)
        self.assertTrue(self.queue.status().empty)
        self.assertEqual(self.events[-2].name, "execution.cancelled")
        self.assertEqual(self.events[-1].name, "queue.updated")
        self.assertFalse(self.events[-2].payload["executed"])
        self.assertTrue(
            any("cancelled" in message for _, message, _ in self.logger.entries)
        )

    def test_clear_cancels_every_request_and_updates_queue_once(self) -> None:
        self.queue.enqueue(_approval_request(self.clock, request_id="approval-001"))
        self.queue.enqueue(_approval_request(self.clock, request_id="approval-002"))

        cancelled = self.queue.clear()

        self.assertEqual(len(cancelled), 2)
        self.assertTrue(
            all(item.status is ApprovalStatus.CANCELLED for item in cancelled)
        )
        self.assertEqual(
            [event.name for event in self.events].count("execution.cancelled"), 2
        )
        self.assertEqual(self.events[-1].payload["operation"], "clear")

    def test_event_subscriber_failure_does_not_change_queue_state(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "queue.updated", lambda event: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        queue = ExecutionQueue(event_bus=bus, logger=self.logger, clock=self.clock)

        queue.enqueue(_approval_request(self.clock))

        self.assertEqual(len(queue), 1)
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in self.logger.entries)
        )


class ApprovalLifecycleTests(unittest.TestCase):
    """Verify gateway-bound request, response, expiry, and token behavior."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.gateway = _Gateway()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "execution.requested",
            "execution.approved",
            "execution.denied",
            "execution.cancelled",
            "queue.updated",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.manager = ApprovalManager(
            self.gateway,
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )
        self.execution_request = ExecutionRequest(action="application.open")

    def _request(self, **kwargs: object) -> ApprovalRequest:
        values: dict[str, object] = {
            "session_id": "session-001",
            "requested_by": "planner",
        }
        values.update(kwargs)
        return self.manager.create_request(  # type: ignore[arg-type]
            self.execution_request,
            **values,
        )

    def test_request_uses_authorize_only_and_emits_requested_event(self) -> None:
        request = self._request()

        self.assertEqual(self.gateway.authorized, [self.execution_request])
        self.assertFalse(self.gateway.execute_called)
        self.assertIs(request.gateway_status, ExecutionStatus.PENDING)
        self.assertEqual(self.manager.queue.peek(), request)
        self.assertIn("execution.requested", [event.name for event in self.events])
        self.assertTrue(
            any(
                message == "Execution approval requested"
                for _, message, _ in self.logger.entries
            )
        )

    def test_approve_issues_bound_token_and_emits_approved(self) -> None:
        request = self._request()

        response = self.manager.approve(request.request_id, responded_by="operator")

        self.assertTrue(response.approved)
        self.assertIsNotNone(response.token)
        self.assertTrue(self.manager.validate_token(response))
        self.assertTrue(
            self.manager.validate_token(
                response.token,
                request_id=request.request_id,
                session_id=request.session_id,
            )
        )
        self.assertIs(self.manager.status(request.request_id), ApprovalStatus.APPROVED)
        self.assertEqual(len(self.manager.queue), 0)
        approved_event = next(
            event for event in self.events if event.name == "execution.approved"
        )
        self.assertFalse(approved_event.payload["executed"])
        self.assertNotIn("token_id", approved_event.payload)

    def test_deny_is_terminal_and_never_issues_token(self) -> None:
        request = self._request()

        response = self.manager.deny(
            request.request_id,
            responded_by="operator",
            reason="Not authorized for this plan.",
        )

        self.assertFalse(response.approved)
        self.assertIsNone(response.token)
        self.assertIs(self.manager.status(request.request_id), ApprovalStatus.DENIED)
        self.assertIn("execution.denied", [event.name for event in self.events])

    def test_duplicate_responses_fail_closed_and_are_logged(self) -> None:
        request = self._request()
        self.manager.approve(request.request_id, responded_by="operator")

        with self.assertRaises(DuplicateApprovalError):
            self.manager.deny(request.request_id, responded_by="operator")

        self.assertTrue(
            any(
                message == "Invalid execution approval event rejected"
                for _, message, _ in self.logger.entries
            )
        )

    def test_missing_and_invalid_responses_fail_closed(self) -> None:
        with self.assertRaises(ApprovalNotFoundError):
            self.manager.approve("missing", responded_by="operator")
        request = self._request()
        with self.assertRaises(InvalidApprovalError):
            self.manager.approve(
                request.request_id,
                responded_by="operator",
                responded_at=self.clock.now + timedelta(seconds=1),
            )

    def test_expired_request_is_cancelled_and_cannot_be_approved(self) -> None:
        request = self._request(ttl=timedelta(seconds=10))
        self.clock.advance(seconds=10)

        with self.assertRaises(ApprovalExpiredError):
            self.manager.approve(request.request_id, responded_by="operator")

        self.assertIs(self.manager.status(request.request_id), ApprovalStatus.EXPIRED)
        event = next(
            event
            for event in reversed(self.events)
            if event.name == "execution.cancelled"
        )
        self.assertEqual(event.payload["reason"], "approval_expired")

    def test_cancel_is_terminal_and_publishes_cancelled(self) -> None:
        request = self._request()

        cancelled = self.manager.cancel(request.request_id, reason="plan withdrawn")

        self.assertIs(cancelled.status, ApprovalStatus.CANCELLED)
        self.assertIn("execution.cancelled", [event.name for event in self.events])
        with self.assertRaises(DuplicateApprovalError):
            self.manager.cancel(request.request_id)

    def test_tokens_expire_and_are_bound_to_exact_request_and_session(self) -> None:
        request = self._request(ttl=timedelta(seconds=30))
        response = self.manager.approve(request.request_id, responded_by="operator")

        self.assertFalse(self.manager.validate_token(response, session_id="other"))
        forged = replace(response.token, token_id="forged")
        self.assertFalse(self.manager.validate_token(forged))
        self.clock.advance(seconds=30)
        self.assertFalse(self.manager.validate_token(response))
        with self.assertRaises(ApprovalExpiredError):
            self.manager.require_valid_token(response)

    def test_denied_rejected_or_unsafe_gateway_results_are_rejected(self) -> None:
        for gateway in (
            _Gateway(ExecutionStatus.DENIED),
            _Gateway(ExecutionStatus.REJECTED),
            _Gateway(ExecutionStatus.PENDING, executed=True),
            _Gateway(ExecutionStatus.PENDING, dispatcher_invoked=True),
        ):
            manager = ApprovalManager(gateway, clock=self.clock)
            with self.assertRaises(GatewayAuthorizationError):
                manager.create_request(
                    self.execution_request,
                    session_id="session-001",
                    requested_by="planner",
                )

    def test_gateway_failure_is_converted_to_fail_closed_error(self) -> None:
        manager = ApprovalManager(
            _FailingGateway(), logger=self.logger, clock=self.clock
        )

        with self.assertRaises(GatewayAuthorizationError):
            manager.create_request(
                self.execution_request,
                session_id="session-001",
                requested_by="planner",
            )

        self.assertTrue(
            any(level is LogLevel.ERROR for level, _, _ in self.logger.entries)
        )

    def test_duplicate_submission_is_rejected(self) -> None:
        request = _approval_request(self.clock)
        self.manager.submit(request)

        with self.assertRaises(DuplicateApprovalError):
            self.manager.submit(request)


class ExecutionSessionTests(unittest.TestCase):
    """Verify session creation, expiry, approval tracking, and history."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.gateway = _Gateway()
        self.approvals = ApprovalManager(
            self.gateway,
            logger=self.logger,
            clock=self.clock,
        )
        self.manager = ExecutionSessionManager(
            self.approvals,
            logger=self.logger,
            clock=self.clock,
            default_ttl=timedelta(minutes=10),
        )

    def test_create_session_detaches_metadata_and_rejects_duplicate_id(self) -> None:
        metadata = {"conversation": {"tags": ["safe"]}}
        session = self.manager.create_session(
            session_id="session-001",
            owner_id="operator",
            metadata=metadata,
        )
        metadata["conversation"]["tags"].append("changed")

        self.assertTrue(session.active)
        self.assertEqual(session.metadata["conversation"]["tags"], ("safe",))
        with self.assertRaises(DuplicateSessionError):
            self.manager.create_session(
                session_id="session-001",
                owner_id="operator",
            )

    def test_session_expires_at_deadline_and_rejects_active_operations(self) -> None:
        session = self.manager.create_session(
            session_id="session-001",
            owner_id="operator",
            ttl=timedelta(seconds=10),
        )
        self.clock.advance(seconds=10)

        expired = self.manager.get_session(session.session_id)

        self.assertIs(expired.status, SessionStatus.EXPIRED)
        self.assertTrue(self.manager.is_expired(session.session_id))
        with self.assertRaises(SessionExpiredError):
            self.manager.update_metadata(session.session_id, {"late": True})

    def test_session_cannot_be_expired_before_deadline(self) -> None:
        session = self.manager.create_session(owner_id="operator")

        with self.assertRaises(SessionExpiredError):
            self.manager.expire_session(session.session_id)

    def test_track_approval_rejects_mismatch_and_duplicate(self) -> None:
        session = self.manager.create_session(
            session_id="session-001",
            owner_id="operator",
        )
        request = _approval_request(self.clock, session_id="session-001")

        tracked = self.manager.track_approval(session.session_id, request)

        self.assertEqual(tracked.approvals, (request.request_id,))
        with self.assertRaises(DuplicateApprovalError):
            self.manager.track_approval(session.session_id, request)
        with self.assertRaises(ValueError):
            self.manager.track_approval(
                session.session_id,
                replace(request, request_id="other", session_id="different"),
            )

    def test_integrated_approval_lifecycle_records_non_execution_history(self) -> None:
        session = self.manager.create_session(
            session_id="session-001",
            owner_id="operator",
        )
        request = self.manager.request_approval(
            session.session_id,
            ExecutionRequest(action="application.open"),
            requested_by="planner",
        )

        response = self.manager.respond_to_approval(
            ApprovalResponse(
                request_id=request.request_id,
                decision=ApprovalDecision.APPROVE,
                responded_by="operator",
                responded_at=self.clock.now,
            )
        )

        updated = self.manager.get_session(session.session_id)
        self.assertTrue(response.approved)
        self.assertEqual(updated.approvals, (request.request_id,))
        self.assertEqual(
            [entry.status for entry in updated.execution_history],
            [ApprovalStatus.PENDING, ApprovalStatus.APPROVED],
        )
        self.assertTrue(all(entry.executed is False for entry in updated.history))
        self.assertFalse(self.gateway.execute_called)

    def test_metadata_updates_and_typed_history_preserve_old_snapshot(self) -> None:
        original = self.manager.create_session(
            session_id="session-001",
            owner_id="operator",
            metadata={"source": "planner"},
        )
        updated = self.manager.update_metadata(
            original.session_id,
            {"correlation": "conversation-001"},
        )
        entry = ExecutionHistoryEntry(
            request_id="approval-001",
            action="system.inspect_status",
            approval_status=ApprovalStatus.PENDING,
            recorded_at=self.clock.now,
        )
        with_history = self.manager.record_history(original.session_id, entry)

        self.assertNotIn("correlation", original.metadata)
        self.assertEqual(updated.metadata["source"], "planner")
        self.assertEqual(with_history.history, (entry,))

    def test_session_expiration_cancels_pending_tracked_approval(self) -> None:
        session = self.manager.create_session(
            session_id="session-001",
            owner_id="operator",
            ttl=timedelta(seconds=10),
        )
        request = self.manager.request_approval(
            session.session_id,
            ExecutionRequest(action="application.open"),
            requested_by="planner",
        )
        self.clock.advance(seconds=10)

        self.manager.get_session(session.session_id)

        self.assertIs(
            self.approvals.status(request.request_id), ApprovalStatus.CANCELLED
        )
        self.assertEqual(len(self.approvals.queue), 0)


if __name__ == "__main__":
    unittest.main()
