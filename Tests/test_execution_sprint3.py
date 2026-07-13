"""Comprehensive tests for Phase 8 Sprint 3 trusted execution."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import unittest

from Core.execution import (
    AuditLogger,
    AuditStage,
    ExecutionDispatcher,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    PermissionEngine,
    PermissionLevel,
    RollbackAction,
    RollbackManager,
    RollbackStatus,
    TrustedExecutionGateway,
    VerificationEngine,
    VerificationStatus,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _CapturingLogger:
    """Retain structured logs for lifecycle assertions."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        """Capture one structured entry."""

        self.entries.append((level, message, context))


class _SimulatedInterface:
    """Dispatcher interface that returns inert, configured output."""

    def __init__(
        self,
        output: dict[str, object] | None = None,
        *,
        executed: bool = True,
    ) -> None:
        self.output = output or {"completed": True}
        self.executed = executed
        self.requests: list[ExecutionRequest] = []

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Return a simulated success without touching the computer."""

        self.requests.append(request)
        return ExecutionResult(
            request_id=request.request_id,
            action=request.action,
            status=ExecutionStatus.SUCCEEDED,
            message="Simulated interface completed.",
            reason_code="simulated_success",
            output=self.output,
            executed=self.executed,
        )


class _RaisingInterface:
    """Dispatcher interface that fails during routing."""

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Raise a simulated provider failure."""

        del request
        raise RuntimeError("provider unavailable")


class _UncorrelatedInterface:
    """Dispatcher interface returning a result for another request."""

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Return a deliberately uncorrelated result."""

        return ExecutionResult(
            request_id="another-request",
            action=request.action,
            status=ExecutionStatus.SUCCEEDED,
            message="Wrong request.",
            executed=True,
        )


class _RollbackProviderSpy:
    """Future real provider that must not be called in Sprint 3."""

    def __init__(self) -> None:
        self.called = False

    def rollback(self, action: RollbackAction) -> bool:
        """Record an unsafe provider invocation."""

        del action
        self.called = True
        return True


class _AuditBackend:
    """Persistence backend double."""

    def __init__(self) -> None:
        self.entries = []

    def append(self, entry) -> None:
        """Retain a persisted entry."""

        self.entries.append(entry)


class _FailingAuditBackend:
    """Backend proving in-memory audit retention is fail-safe."""

    def append(self, entry) -> None:
        """Raise a simulated persistence outage."""

        del entry
        raise RuntimeError("audit store unavailable")


class _AuditExporter:
    """Exporter double returning stable entry identifiers."""

    def export(self, entries) -> tuple[str, ...]:
        """Export entry identifiers."""

        return tuple(entry.entry_id for entry in entries)


class _FailingVerifier:
    """Verifier double that raises an internal error."""

    def verify(self, result, expected_outcome=None):
        """Raise a simulated verifier failure."""

        del result, expected_outcome
        raise RuntimeError("verification unavailable")


class ExecutionDispatcherTests(unittest.TestCase):
    """Verify routing extensibility and fail-safe dispatch behavior."""

    def test_routes_to_the_most_specific_registered_interface(self) -> None:
        namespace = _SimulatedInterface()
        specific = _SimulatedInterface({"installed": True})
        dispatcher = ExecutionDispatcher(
            {"plugin": namespace, "plugin.install": specific}
        )
        request = ExecutionRequest(action="plugin.install.local")

        result = dispatcher.dispatch(request)

        self.assertIs(result.status, ExecutionStatus.SUCCEEDED)
        self.assertTrue(result.dispatcher_invoked)
        self.assertEqual(specific.requests, [request])
        self.assertEqual(namespace.requests, [])

    def test_explicit_dispatch_target_selects_only_that_interface(self) -> None:
        computer = _SimulatedInterface()
        automation = _SimulatedInterface()
        dispatcher = ExecutionDispatcher(
            {"computer": computer, "automation": automation}
        )
        request = ExecutionRequest(
            action="task.run",
            metadata={"dispatch_target": "automation"},
        )

        dispatcher.dispatch(request)

        self.assertEqual(automation.requests, [request])
        self.assertFalse(computer.requests)

    def test_unavailable_exception_and_correlation_fail_safely(self) -> None:
        unavailable = ExecutionDispatcher().dispatch(
            ExecutionRequest(action="computer.open")
        )
        raised = ExecutionDispatcher({"computer": _RaisingInterface()}).dispatch(
            ExecutionRequest(action="computer.open")
        )
        mismatch = ExecutionDispatcher(
            {"computer": _UncorrelatedInterface()}
        ).dispatch(ExecutionRequest(action="computer.open"))

        self.assertEqual(unavailable.reason_code, "dispatcher_unavailable")
        self.assertEqual(raised.reason_code, "dispatch_failed")
        self.assertEqual(mismatch.reason_code, "dispatch_correlation_mismatch")
        for result in (unavailable, raised, mismatch):
            self.assertIs(result.status, ExecutionStatus.FAILED)
            self.assertFalse(result.executed)
            self.assertTrue(result.dispatcher_invoked)

    def test_registry_snapshot_is_read_only(self) -> None:
        dispatcher = ExecutionDispatcher({"computer": _SimulatedInterface()})

        with self.assertRaises(TypeError):
            dispatcher.interfaces["plugin"] = (  # type: ignore[index]
                _SimulatedInterface()
            )


class VerificationEngineTests(unittest.TestCase):
    """Verify completion, outcome, reports, and async compatibility."""

    def _result(self, **overrides: object) -> ExecutionResult:
        values = {
            "request_id": "request-001",
            "action": "computer.inspect",
            "status": ExecutionStatus.SUCCEEDED,
            "message": "Completed.",
            "output": {"state": "ready", "count": 2},
            "executed": True,
            "dispatcher_invoked": True,
        }
        values.update(overrides)
        return ExecutionResult(**values)

    def test_verifies_completion_and_expected_outcome_subset(self) -> None:
        report = VerificationEngine().verify(
            self._result(),
            {"state": "ready"},
        )

        self.assertIs(report.status, VerificationStatus.PASSED)
        self.assertTrue(report.completion_verified)
        self.assertTrue(report.outcome_verified)
        self.assertTrue(report.passed)

    def test_reports_outcome_mismatch_and_incomplete_execution(self) -> None:
        mismatch = VerificationEngine().verify(
            self._result(),
            {"state": "stopped"},
        )
        incomplete = VerificationEngine().verify(
            self._result(executed=False),
        )

        self.assertEqual(mismatch.reason_code, "expected_outcome_mismatch")
        self.assertTrue(mismatch.requires_rollback)
        self.assertEqual(incomplete.reason_code, "execution_not_completed")
        self.assertFalse(incomplete.completion_verified)

    def test_invalid_result_and_expected_outcome_fail_closed(self) -> None:
        invalid_result = VerificationEngine().verify(object())  # type: ignore[arg-type]
        invalid_expectation = VerificationEngine().verify(
            self._result(),
            ["ready"],  # type: ignore[arg-type]
        )

        self.assertEqual(invalid_result.reason_code, "invalid_execution_result")
        self.assertEqual(
            invalid_expectation.reason_code,
            "invalid_expected_outcome",
        )

    def test_async_verification_returns_the_same_structured_outcome(self) -> None:
        report = asyncio.run(
            VerificationEngine().verify_async(
                self._result(),
                {"state": "ready"},
            )
        )

        self.assertTrue(report.passed)


class RollbackManagerTests(unittest.TestCase):
    """Verify inert planning, registration, history, and provider isolation."""

    def test_builds_and_simulates_plan_without_invoking_provider(self) -> None:
        provider = _RollbackProviderSpy()
        manager = RollbackManager({"computer": provider})
        request = ExecutionRequest(action="computer.configure")
        action = RollbackAction(
            action_id="restore-settings",
            description="Restore captured settings.",
            provider="computer",
            parameters={"snapshot": "settings-001"},
        )
        manager.register_action(request.request_id, action)

        plan = manager.build_plan(request)
        result = manager.execute(plan)

        self.assertEqual(plan.actions, (action,))
        self.assertIs(plan.status, RollbackStatus.PLANNED)
        self.assertIs(result.status, RollbackStatus.SIMULATED)
        self.assertTrue(result.successful)
        self.assertTrue(result.simulated)
        self.assertEqual(result.actions_executed, ("restore-settings",))
        self.assertFalse(provider.called)
        self.assertEqual(manager.history, (result,))
        self.assertEqual(manager.plans, (plan,))

    def test_plans_actions_and_history_are_immutable_snapshots(self) -> None:
        manager = RollbackManager()
        request = ExecutionRequest(action="plugin.install")
        plan = manager.build_plan(request)
        history_before = manager.history

        with self.assertRaises(FrozenInstanceError):
            plan.status = RollbackStatus.FAILED  # type: ignore[misc]
        manager.execute(plan)

        self.assertEqual(history_before, ())
        self.assertEqual(len(manager.history), 1)

    def test_invalid_plan_returns_a_typed_simulated_failure(self) -> None:
        result = RollbackManager().execute(object())  # type: ignore[arg-type]

        self.assertIs(result.status, RollbackStatus.FAILED)
        self.assertFalse(result.successful)
        self.assertTrue(result.simulated)


class AuditLoggerTests(unittest.TestCase):
    """Verify immutable timestamps, persistence extension, and export."""

    def test_records_timestamped_immutable_entries_and_exports_snapshot(self) -> None:
        timestamp = datetime(2026, 7, 13, 12, 30, tzinfo=timezone.utc)
        backend = _AuditBackend()
        audit = AuditLogger(backend, clock=lambda: timestamp)

        entry = audit.record(
            request_id="request-001",
            action="computer.inspect",
            stage=AuditStage.STARTED,
            outcome="started",
            details={"correlation": "test-001"},
        )

        self.assertEqual(entry.timestamp, timestamp)
        self.assertEqual(audit.entries, (entry,))
        self.assertEqual(backend.entries, [entry])
        self.assertEqual(audit.for_request("request-001"), (entry,))
        self.assertEqual(audit.export(), (entry,))
        self.assertEqual(audit.export(_AuditExporter()), (entry.entry_id,))
        with self.assertRaises(FrozenInstanceError):
            entry.outcome = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            entry.details["correlation"] = "changed"  # type: ignore[index]

    def test_backend_failure_does_not_lose_in_memory_entry(self) -> None:
        logger = _CapturingLogger()
        audit = AuditLogger(_FailingAuditBackend(), logger=logger)

        entry = audit.record(
            request_id="request-001",
            action="computer.inspect",
            stage=AuditStage.STARTED,
            outcome="started",
        )

        self.assertEqual(audit.entries, (entry,))
        self.assertTrue(
            any(
                message == "Unable to persist execution audit entry"
                for _, message, _ in logger.entries
            )
        )


class GatewaySprint3Tests(unittest.TestCase):
    """Verify the complete trusted lifecycle, events, logs, and failures."""

    _LIFECYCLE_EVENTS = (
        TrustedExecutionGateway.EXECUTION_STARTED_EVENT,
        TrustedExecutionGateway.EXECUTION_DISPATCHED_EVENT,
        TrustedExecutionGateway.EXECUTION_VERIFIED_EVENT,
        TrustedExecutionGateway.EXECUTION_ROLLBACK_EVENT,
        TrustedExecutionGateway.EXECUTION_COMPLETED_EVENT,
        TrustedExecutionGateway.EXECUTION_FAILED_EVENT,
    )

    def _capturing_bus(self) -> tuple[EventBus, list[SystemEvent]]:
        event_bus = EventBus()
        events: list[SystemEvent] = []
        for event_name in self._LIFECYCLE_EVENTS:
            event_bus.subscribe(event_name, events.append)
        return event_bus, events

    def test_successful_full_lifecycle_publishes_events_logs_and_audit(self) -> None:
        event_bus, events = self._capturing_bus()
        logger = _CapturingLogger()
        interface = _SimulatedInterface({"state": "ready", "detail": "safe"})
        gateway = TrustedExecutionGateway(
            dispatcher=ExecutionDispatcher({"computer": interface}, logger=logger),
            event_bus=event_bus,
            logger=logger,
        )
        request = ExecutionRequest(
            action="computer.inspect",
            metadata={"expected_outcome": {"state": "ready"}},
        )

        result = gateway.execute(request)

        self.assertIs(result.status, ExecutionStatus.SUCCEEDED)
        self.assertTrue(result.successful)
        self.assertTrue(result.verified)
        self.assertTrue(result.dispatcher_invoked)
        self.assertIsNone(result.rollback_result)
        self.assertEqual(interface.requests, [request])
        self.assertEqual(
            [event.name for event in events],
            [
                TrustedExecutionGateway.EXECUTION_STARTED_EVENT,
                TrustedExecutionGateway.EXECUTION_DISPATCHED_EVENT,
                TrustedExecutionGateway.EXECUTION_VERIFIED_EVENT,
                TrustedExecutionGateway.EXECUTION_COMPLETED_EVENT,
            ],
        )
        audit_stages = tuple(
            entry.stage
            for entry in gateway.audit_logger.for_request(request.request_id)
        )
        self.assertEqual(
            audit_stages,
            (
                AuditStage.REQUEST_RECEIVED,
                AuditStage.VALIDATED,
                AuditStage.PERMISSION_EVALUATED,
                AuditStage.RISK_EVALUATED,
                AuditStage.POLICY_EVALUATED,
                AuditStage.APPROVAL_EVALUATED,
                AuditStage.STARTED,
                AuditStage.DISPATCHED,
                AuditStage.VERIFIED,
                AuditStage.COMPLETED,
            ),
        )
        self.assertEqual(len(result.audit_entry_ids), len(audit_stages))
        messages = {message for _, message, _ in logger.entries}
        self.assertIn("Execution lifecycle started", messages)
        self.assertIn("Execution dispatch stage completed", messages)
        self.assertIn("Execution verification stage completed", messages)
        self.assertIn("Execution lifecycle completed", messages)

    def test_verification_failure_simulates_rollback_and_fails_result(self) -> None:
        event_bus, events = self._capturing_bus()
        request = ExecutionRequest(
            action="plugin.inspect",
            metadata={"expected_outcome": {"version": 2}},
        )
        rollback = RollbackManager()
        rollback.register_action(
            request.request_id,
            RollbackAction(
                action_id="restore-plugin",
                description="Restore prior plugin state.",
            ),
        )
        gateway = TrustedExecutionGateway(
            dispatcher=ExecutionDispatcher(
                {"plugin": _SimulatedInterface({"version": 1})}
            ),
            rollback_manager=rollback,
            event_bus=event_bus,
        )

        result = gateway.execute(request)

        self.assertIs(result.status, ExecutionStatus.FAILED)
        self.assertEqual(result.reason_code, "expected_outcome_mismatch")
        self.assertIsNotNone(result.rollback_result)
        assert result.rollback_result is not None
        self.assertIs(result.rollback_result.status, RollbackStatus.SIMULATED)
        self.assertEqual(
            result.rollback_result.actions_executed,
            ("restore-plugin",),
        )
        self.assertEqual(
            [event.name for event in events],
            [
                TrustedExecutionGateway.EXECUTION_STARTED_EVENT,
                TrustedExecutionGateway.EXECUTION_DISPATCHED_EVENT,
                TrustedExecutionGateway.EXECUTION_VERIFIED_EVENT,
                TrustedExecutionGateway.EXECUTION_ROLLBACK_EVENT,
                TrustedExecutionGateway.EXECUTION_FAILED_EVENT,
            ],
        )

    def test_dispatch_failure_is_verified_and_fails_without_rollback(self) -> None:
        event_bus, events = self._capturing_bus()
        gateway = TrustedExecutionGateway(
            dispatcher=ExecutionDispatcher({"computer": _RaisingInterface()}),
            event_bus=event_bus,
        )

        result = gateway.execute(ExecutionRequest(action="computer.inspect"))

        self.assertIs(result.status, ExecutionStatus.FAILED)
        self.assertEqual(result.reason_code, "dispatch_failed")
        self.assertIsNone(result.rollback_result)
        self.assertFalse(result.executed)
        self.assertEqual(
            [event.name for event in events],
            [
                TrustedExecutionGateway.EXECUTION_STARTED_EVENT,
                TrustedExecutionGateway.EXECUTION_DISPATCHED_EVENT,
                TrustedExecutionGateway.EXECUTION_VERIFIED_EVENT,
                TrustedExecutionGateway.EXECUTION_FAILED_EVENT,
            ],
        )

    def test_verifier_exception_fails_closed_and_simulates_rollback(self) -> None:
        request = ExecutionRequest(action="computer.inspect")
        gateway = TrustedExecutionGateway(
            dispatcher=ExecutionDispatcher(
                {"computer": _SimulatedInterface()}
            ),
            verification_engine=_FailingVerifier(),  # type: ignore[arg-type]
        )

        result = gateway.execute(request)

        self.assertEqual(result.reason_code, "verification_failed")
        self.assertIsNotNone(result.rollback_result)
        self.assertTrue(result.rollback_result.simulated)  # type: ignore[union-attr]

    def test_authorization_failure_never_invokes_dispatcher(self) -> None:
        event_bus, events = self._capturing_bus()
        interface = _SimulatedInterface()
        gateway = TrustedExecutionGateway(
            PermissionEngine(maximum_level=PermissionLevel.STANDARD),
            dispatcher=ExecutionDispatcher({"computer": interface}),
            event_bus=event_bus,
        )

        result = gateway.execute(
            ExecutionRequest(
                action="computer.configure",
                permission_level=PermissionLevel.ADMINISTRATOR,
            )
        )

        self.assertIs(result.status, ExecutionStatus.DENIED)
        self.assertFalse(interface.requests)
        self.assertEqual(
            [event.name for event in events],
            [TrustedExecutionGateway.EXECUTION_FAILED_EVENT],
        )

    def test_lifecycle_subscriber_failure_does_not_change_success(self) -> None:
        event_bus = EventBus()
        logger = _CapturingLogger()

        def fail_handler(event: SystemEvent) -> None:
            raise RuntimeError(f"subscriber failed for {event.name}")

        event_bus.subscribe(
            TrustedExecutionGateway.EXECUTION_STARTED_EVENT,
            fail_handler,
        )
        gateway = TrustedExecutionGateway(
            dispatcher=ExecutionDispatcher(
                {"computer": _SimulatedInterface()}
            ),
            event_bus=event_bus,
            logger=logger,
        )

        result = gateway.execute(ExecutionRequest(action="computer.inspect"))

        self.assertIs(result.status, ExecutionStatus.SUCCEEDED)
        self.assertTrue(
            any(
                message == "Unable to publish execution event"
                for _, message, _ in logger.entries
            )
        )


if __name__ == "__main__":
    unittest.main()
