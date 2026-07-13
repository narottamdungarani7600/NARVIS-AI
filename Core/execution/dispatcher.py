"""Extensible, fail-safe routing for validated execution requests.

The dispatcher owns no computer, automation, or plugin implementation.  It
only selects an injected interface and returns the interface's typed result.
This keeps Core free of host-action code while providing stable integration
points for future modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger

from .models import ExecutionRequest, ExecutionResult, ExecutionStatus


@runtime_checkable
class DispatcherInterface(Protocol):
    """Contract implemented by a future execution-specific adapter."""

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Handle a validated request and return a typed execution result."""


class ExecutionDispatcher:
    """Route validated requests to explicitly registered interfaces only.

    Routes may be complete action names (``plugin.install``) or action
    namespaces (``plugin``).  A request can explicitly select a registered
    route through ``metadata['dispatcher']`` or ``metadata['dispatch_target']``;
    otherwise the most specific matching action route is used.
    """

    def __init__(
        self,
        interfaces: Mapping[str, DispatcherInterface] | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        """Initialize the router without installing any action provider."""

        self._interfaces: dict[str, DispatcherInterface] = {}
        self._logger = logger or NullLogger("narvis.execution.dispatcher")
        for route, interface in (interfaces or {}).items():
            self.register(route, interface)

    @property
    def interfaces(self) -> Mapping[str, DispatcherInterface]:
        """Return a detached, read-only snapshot of registered interfaces."""

        return MappingProxyType(dict(self._interfaces))

    @property
    def routes(self) -> tuple[str, ...]:
        """Return registered route names in deterministic order."""

        return tuple(sorted(self._interfaces))

    def register(self, route: str, interface: DispatcherInterface) -> None:
        """Register or replace an interface for a normalized route."""

        normalized_route = self._validate_route(route)
        if not isinstance(interface, DispatcherInterface):
            raise TypeError("dispatcher interfaces must implement dispatch(request)")
        self._interfaces[normalized_route] = interface
        self._log(
            LogLevel.DEBUG,
            "Execution dispatcher interface registered",
            route=normalized_route,
            interface_type=type(interface).__name__,
        )

    def register_interface(
        self,
        route: str,
        interface: DispatcherInterface,
    ) -> None:
        """Register an interface using explicit integration terminology."""

        self.register(route, interface)

    def register_dispatcher(
        self,
        route: str,
        interface: DispatcherInterface,
    ) -> None:
        """Register an interface using dispatcher registry terminology."""

        self.register(route, interface)

    def unregister(self, route: str) -> bool:
        """Remove a route and return whether an interface was registered."""

        normalized_route = self._validate_route(route)
        return self._interfaces.pop(normalized_route, None) is not None

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        """Route a validated request without directly performing any action.

        Malformed input, unavailable routes, interface exceptions, and invalid
        interface results are converted into typed failures so this boundary
        always fails safely.
        """

        if not self._is_valid_request(request):
            return self._failure(
                request,
                reason_code="invalid_dispatch_request",
                message="Execution dispatch requires a validated ExecutionRequest.",
            )

        route = self._resolve_route(request)
        if route is None:
            self._log(
                LogLevel.WARNING,
                "No execution dispatcher interface is available",
                request_id=request.request_id,
                action=request.action,
            )
            return self._failure(
                request,
                reason_code="dispatcher_unavailable",
                message="No dispatcher interface is registered for this action.",
            )

        interface = self._interfaces[route]
        self._log(
            LogLevel.INFO,
            "Execution request routed to dispatcher interface",
            request_id=request.request_id,
            action=request.action,
            route=route,
            interface_type=type(interface).__name__,
        )
        try:
            result = interface.dispatch(request)
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Execution dispatcher interface failed",
                request_id=request.request_id,
                action=request.action,
                route=route,
                error_type=type(error).__name__,
            )
            return self._failure(
                request,
                reason_code="dispatch_failed",
                message="The dispatcher interface failed safely.",
            )

        if not isinstance(result, ExecutionResult):
            return self._failure(
                request,
                reason_code="invalid_dispatch_result",
                message="The dispatcher interface returned an invalid result.",
            )
        if result.request_id != request.request_id or result.action != request.action:
            return self._failure(
                request,
                reason_code="dispatch_correlation_mismatch",
                message="The dispatcher result did not match the request.",
            )

        return replace(result, dispatcher_invoked=True)

    @staticmethod
    def _validate_route(route: object) -> str:
        """Return a normalized route or raise a configuration error."""

        if (
            not isinstance(route, str)
            or not route.strip()
            or route != route.strip()
            or len(route) > 256
        ):
            raise ValueError(
                "dispatcher routes must be normalized non-empty strings "
                "of at most 256 characters"
            )
        return route

    @staticmethod
    def _is_valid_request(request: object) -> bool:
        """Check the structural facts required for safe direct dispatch."""

        return (
            isinstance(request, ExecutionRequest)
            and isinstance(request.request_id, str)
            and bool(request.request_id.strip())
            and request.request_id == request.request_id.strip()
            and isinstance(request.action, str)
            and bool(request.action.strip())
            and request.action == request.action.strip()
            and isinstance(request.parameters, Mapping)
            and isinstance(request.metadata, Mapping)
        )

    def _resolve_route(self, request: ExecutionRequest) -> str | None:
        """Resolve an explicit target or the most specific action prefix."""

        explicit_route = request.metadata.get(
            "dispatcher",
            request.metadata.get("dispatch_target"),
        )
        if isinstance(explicit_route, str):
            return explicit_route if explicit_route in self._interfaces else None

        candidates = (
            route
            for route in self._interfaces
            if request.action == route
            or request.action.startswith(f"{route}.")
            or request.action.startswith(f"{route}:")
        )
        return max(candidates, key=len, default=None)

    @staticmethod
    def _failure(
        request: object,
        *,
        reason_code: str,
        message: str,
    ) -> ExecutionResult:
        """Build a correlated typed dispatch failure."""

        request_id = getattr(request, "request_id", "")
        action = getattr(request, "action", "")
        return ExecutionResult(
            request_id=request_id if isinstance(request_id, str) else "",
            action=action if isinstance(action, str) else "",
            status=ExecutionStatus.FAILED,
            message=message,
            reason_code=reason_code,
            executed=False,
            dispatcher_invoked=True,
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a structured log without changing dispatch control flow."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["DispatcherInterface", "ExecutionDispatcher"]
