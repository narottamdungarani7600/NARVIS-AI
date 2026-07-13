"""Trusted, non-executing gateway for proposed computer actions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import ExecutionValidationError
from .models import ExecutionRequest, ExecutionResult, ExecutionStatus, PermissionLevel
from .permissions import PermissionChecker, PermissionEngine


class EventPublisher(Protocol):
    """Minimal event-bus contract required by the gateway."""

    def publish(self, event: SystemEvent) -> None:
        """Publish one execution lifecycle event."""


class ExecutionDispatcher(Protocol):
    """Future extension contract for an approved execution dispatcher.

    Sprint 1 defines this boundary so a later dispatcher can be injected
    without changing request or result models.  The gateway does not accept or
    invoke a dispatcher in the current phase.
    """

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Dispatch an already authorized request and return its outcome."""


class TrustedExecutionGateway:
    """Validate and authorize execution requests without executing actions.

    The gateway is fail closed: malformed requests, permission denials, and
    permission-service failures all become typed non-executing results.  Logger,
    event bus, and permission service dependencies are injected so the boundary
    remains testable and independent of runtime composition.
    """

    REQUEST_RECEIVED_EVENT = "execution.request.received"
    REQUEST_REJECTED_EVENT = "execution.request.rejected"
    PERMISSION_DENIED_EVENT = "execution.permission.denied"
    REQUEST_AUTHORIZED_EVENT = "execution.request.authorized"

    def __init__(
        self,
        permission_engine: PermissionChecker | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        """Initialize the trusted gateway with injected dependencies.

        Args:
            permission_engine: Permission service used to evaluate requests.
            logger: Core-compatible logger implementation.
            event_bus: Existing EventBus or compatible publisher used for
                execution lifecycle events.
        """

        self._logger = logger or NullLogger("narvis.execution.gateway")
        self._permission_engine = permission_engine or PermissionEngine(
            logger=self._logger
        )
        self._event_bus = event_bus

    @property
    def permission_engine(self) -> PermissionChecker:
        """Return the injected permission service."""

        return self._permission_engine

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
            allowed = self._permission_engine.check_permission(request) is True
            required_level = self._permission_engine.required_level_for(request)
        except Exception as error:
            result = ExecutionResult(
                request_id=request.request_id,
                action=request.action,
                status=ExecutionStatus.DENIED,
                message="Permission evaluation failed closed.",
                permission_level=request.permission_level,
                reason_code="permission_check_failed",
            )
            self._log(
                LogLevel.ERROR,
                "Execution permission evaluation failed",
                **context,
                error_type=type(error).__name__,
            )
            self._publish_result(self.PERMISSION_DENIED_EVENT, result)
            return result

        if not allowed:
            result = ExecutionResult(
                request_id=request.request_id,
                action=request.action,
                status=ExecutionStatus.DENIED,
                message="The request does not have the required permission.",
                permission_level=required_level,
                reason_code="permission_denied",
            )
            self._log(
                LogLevel.WARNING,
                "Execution permission denied",
                **context,
                required_level=required_level.value,
            )
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
            permission_level=required_level,
            reason_code="execution_authorized",
        )
        self._log(
            LogLevel.INFO,
            "Execution request authorized without dispatch",
            **context,
            required_level=required_level.value,
            executed=False,
            dispatcher_invoked=False,
        )
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
