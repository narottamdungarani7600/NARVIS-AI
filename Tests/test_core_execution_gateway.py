"""Unit tests for the Phase 8 Sprint 1 trusted execution gateway."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Core.execution import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionValidationError,
    PermissionConfigurationError,
    PermissionDeniedError,
    PermissionEngine,
    PermissionLevel,
    TrustedExecutionGateway,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _CapturingLogger:
    """Logger double that retains structured entries for assertions."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        """Retain one structured log entry."""

        self.entries.append((level, message, context))


class _FailingPermissionChecker:
    """Permission checker double that simulates an internal policy failure."""

    def check_permission(self, request: ExecutionRequest) -> bool:
        """Raise an internal failure instead of returning a decision."""

        raise RuntimeError("policy service unavailable")

    def required_level_for(self, request: ExecutionRequest) -> PermissionLevel:
        """Return the request level when queried independently."""

        return request.permission_level


class ExecutionModelTests(unittest.TestCase):
    """Verify the immutable request and result contracts."""

    def test_request_defaults_are_independent_and_correlatable(self) -> None:
        first = ExecutionRequest(action="system.inspect_status")
        second = ExecutionRequest(action="system.inspect_status")

        self.assertNotEqual(first.request_id, second.request_id)
        self.assertEqual(first.permission_level, PermissionLevel.STANDARD)
        self.assertEqual(first.parameters, {})
        self.assertEqual(first.metadata, {})

    def test_authorized_result_is_not_reported_as_execution_success(self) -> None:
        result = ExecutionResult(
            request_id="request-001",
            action="system.inspect_status",
            status=ExecutionStatus.AUTHORIZED,
            message="Authorized only.",
        )

        self.assertTrue(result.authorized)
        self.assertFalse(result.successful)
        self.assertFalse(result.executed)
        self.assertFalse(result.dispatcher_invoked)


class PermissionEngineTests(unittest.TestCase):
    """Verify hierarchical and action-specific permission decisions."""

    def test_allows_a_request_within_the_maximum_level(self) -> None:
        engine = PermissionEngine(maximum_level=PermissionLevel.ELEVATED)
        request = ExecutionRequest(
            action="application.open",
            permission_level=PermissionLevel.STANDARD,
        )

        self.assertTrue(engine.check_permission(request))
        self.assertEqual(engine.required_level_for(request), PermissionLevel.STANDARD)

    def test_denies_a_request_above_the_maximum_level(self) -> None:
        engine = PermissionEngine(maximum_level=PermissionLevel.READ_ONLY)
        request = ExecutionRequest(
            action="application.open",
            permission_level=PermissionLevel.ELEVATED,
        )

        self.assertFalse(engine.check_permission(request))
        with self.assertRaises(PermissionDeniedError):
            engine.require_permission(request)

    def test_action_policy_can_increase_but_not_reduce_required_permission(
        self,
    ) -> None:
        engine = PermissionEngine(
            maximum_level=PermissionLevel.ELEVATED,
            action_permissions={
                "system.configure": PermissionLevel.ADMINISTRATOR,
                "file.read": PermissionLevel.READ_ONLY,
            },
        )
        configured = ExecutionRequest(
            action="system.configure",
            permission_level=PermissionLevel.STANDARD,
        )
        caller_stricter = ExecutionRequest(
            action="file.read",
            permission_level=PermissionLevel.ELEVATED,
        )

        self.assertFalse(engine.check_permission(configured))
        self.assertEqual(
            engine.required_level_for(configured),
            PermissionLevel.ADMINISTRATOR,
        )
        self.assertEqual(
            engine.required_level_for(caller_stricter),
            PermissionLevel.ELEVATED,
        )

    def test_action_policy_is_detached_and_read_only(self) -> None:
        policy = {"file.read": PermissionLevel.READ_ONLY}
        engine = PermissionEngine(action_permissions=policy)
        policy["file.read"] = PermissionLevel.ADMINISTRATOR

        self.assertEqual(
            engine.action_permissions["file.read"],
            PermissionLevel.READ_ONLY,
        )
        with self.assertRaises(TypeError):
            engine.action_permissions["file.read"] = PermissionLevel.STANDARD  # type: ignore[index]

    def test_rejects_invalid_permission_configuration(self) -> None:
        with self.assertRaises(PermissionConfigurationError):
            PermissionEngine(maximum_level="administrator")  # type: ignore[arg-type]
        with self.assertRaises(PermissionConfigurationError):
            PermissionEngine(
                action_permissions={" file.read": PermissionLevel.READ_ONLY}
            )

    def test_rejects_untyped_requests(self) -> None:
        engine = PermissionEngine()

        with self.assertRaises(ExecutionValidationError):
            engine.check_permission(object())  # type: ignore[arg-type]


class TrustedExecutionGatewayTests(unittest.TestCase):
    """Verify validation, permissions, observability, and non-execution safety."""

    def setUp(self) -> None:
        self.logger = _CapturingLogger()
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            TrustedExecutionGateway.REQUEST_RECEIVED_EVENT,
            TrustedExecutionGateway.REQUEST_REJECTED_EVENT,
            TrustedExecutionGateway.PERMISSION_DENIED_EVENT,
            TrustedExecutionGateway.REQUEST_AUTHORIZED_EVENT,
        ):
            self.event_bus.subscribe(event_name, self.events.append)

    def test_authorizes_valid_request_without_invoking_or_executing_any_action(
        self,
    ) -> None:
        request = ExecutionRequest(
            action="application.open",
            parameters={"application": "calculator"},
            metadata={"correlation_id": "conversation-001"},
        )
        gateway = TrustedExecutionGateway(
            logger=self.logger,
            event_bus=self.event_bus,
        )

        result = gateway.execute(request)

        self.assertIsInstance(result, ExecutionResult)
        self.assertIs(result.status, ExecutionStatus.AUTHORIZED)
        self.assertEqual(result.request_id, request.request_id)
        self.assertTrue(result.authorized)
        self.assertFalse(result.successful)
        self.assertFalse(result.executed)
        self.assertFalse(result.dispatcher_invoked)
        self.assertEqual(
            [event.name for event in self.events],
            [
                TrustedExecutionGateway.REQUEST_RECEIVED_EVENT,
                TrustedExecutionGateway.REQUEST_AUTHORIZED_EVENT,
            ],
        )
        self.assertTrue(
            any(
                level is LogLevel.INFO
                and message == "Execution request authorized without dispatch"
                for level, message, _ in self.logger.entries
            )
        )

    def test_permission_denial_returns_typed_result(self) -> None:
        request = ExecutionRequest(
            action="system.configure",
            permission_level=PermissionLevel.ADMINISTRATOR,
        )
        gateway = TrustedExecutionGateway(
            PermissionEngine(maximum_level=PermissionLevel.STANDARD),
            logger=self.logger,
            event_bus=self.event_bus,
        )

        result = gateway.authorize(request)

        self.assertIs(result.status, ExecutionStatus.DENIED)
        self.assertEqual(result.reason_code, "permission_denied")
        self.assertEqual(result.permission_level, PermissionLevel.ADMINISTRATOR)
        self.assertFalse(result.executed)
        self.assertEqual(
            self.events[-1].name,
            TrustedExecutionGateway.PERMISSION_DENIED_EVENT,
        )

    def test_invalid_request_returns_rejection_without_raising(self) -> None:
        request = replace(
            ExecutionRequest(action="application.open"),
            action="   ",
        )
        gateway = TrustedExecutionGateway(
            logger=self.logger,
            event_bus=self.event_bus,
        )

        result = gateway.execute(request)

        self.assertIs(result.status, ExecutionStatus.REJECTED)
        self.assertEqual(result.reason_code, "invalid_request")
        self.assertFalse(result.executed)
        self.assertEqual(
            self.events[-1].name,
            TrustedExecutionGateway.REQUEST_REJECTED_EVENT,
        )

    def test_untyped_request_fails_closed_as_a_typed_rejection(self) -> None:
        gateway = TrustedExecutionGateway(logger=self.logger)

        result = gateway.execute(object())  # type: ignore[arg-type]

        self.assertIsInstance(result, ExecutionResult)
        self.assertIs(result.status, ExecutionStatus.REJECTED)
        self.assertEqual(result.request_id, "")
        self.assertEqual(result.action, "")

    def test_non_mapping_parameters_and_non_string_keys_are_rejected(self) -> None:
        gateway = TrustedExecutionGateway()
        non_mapping = replace(
            ExecutionRequest(action="application.open"),
            parameters=[],  # type: ignore[arg-type]
        )
        non_string_key = ExecutionRequest(
            action="application.open",
            parameters={1: "calculator"},  # type: ignore[dict-item]
        )

        self.assertIs(
            gateway.execute(non_mapping).status,
            ExecutionStatus.REJECTED,
        )
        self.assertIs(
            gateway.execute(non_string_key).status,
            ExecutionStatus.REJECTED,
        )

    def test_permission_service_failure_is_denied_and_logged(self) -> None:
        gateway = TrustedExecutionGateway(
            _FailingPermissionChecker(),
            logger=self.logger,
            event_bus=self.event_bus,
        )

        result = gateway.execute(ExecutionRequest(action="application.open"))

        self.assertIs(result.status, ExecutionStatus.DENIED)
        self.assertEqual(result.reason_code, "permission_check_failed")
        self.assertFalse(result.executed)
        self.assertTrue(
            any(level is LogLevel.ERROR for level, _, _ in self.logger.entries)
        )

    def test_event_subscriber_failure_does_not_change_authorization(self) -> None:
        event_bus = EventBus()

        def fail_handler(event: SystemEvent) -> None:
            raise RuntimeError(f"subscriber failed for {event.name}")

        event_bus.subscribe(
            TrustedExecutionGateway.REQUEST_RECEIVED_EVENT,
            fail_handler,
        )
        gateway = TrustedExecutionGateway(logger=self.logger, event_bus=event_bus)

        result = gateway.execute(ExecutionRequest(action="system.inspect_status"))

        self.assertIs(result.status, ExecutionStatus.AUTHORIZED)
        self.assertTrue(
            any(
                message == "Unable to publish execution event"
                for _, message, _ in self.logger.entries
            )
        )

    def test_event_payload_does_not_expose_request_parameters(self) -> None:
        secret = "do-not-publish"
        gateway = TrustedExecutionGateway(event_bus=self.event_bus)

        gateway.execute(
            ExecutionRequest(
                action="application.open",
                parameters={"secret": secret},
            )
        )

        self.assertTrue(self.events)
        self.assertTrue(all(secret not in repr(event.payload) for event in self.events))


if __name__ == "__main__":
    unittest.main()
