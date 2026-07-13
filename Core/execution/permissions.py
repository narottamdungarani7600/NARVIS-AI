"""Permission policy evaluation for the trusted execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger

from .exceptions import (
    ExecutionValidationError,
    PermissionConfigurationError,
    PermissionDeniedError,
)
from .models import ExecutionRequest, PermissionLevel


_PERMISSION_RANK: dict[PermissionLevel, int] = {
    PermissionLevel.NONE: 0,
    PermissionLevel.READ_ONLY: 1,
    PermissionLevel.STANDARD: 2,
    PermissionLevel.ELEVATED: 3,
    PermissionLevel.ADMINISTRATOR: 4,
}


class PermissionChecker(Protocol):
    """Contract consumed by :class:`TrustedExecutionGateway` permission checks."""

    def check_permission(self, request: ExecutionRequest) -> bool:
        """Return whether the supplied request is permitted."""

    def required_level_for(self, request: ExecutionRequest) -> PermissionLevel:
        """Return the effective permission required for the request."""


class PermissionEngine:
    """Evaluate requests against a maximum level and optional action policy.

    The request declares a minimum permission level.  An action-specific policy
    may increase that minimum but can never reduce it, preventing a caller from
    weakening a configured requirement.  The service performs no action and
    has no dependency on an execution dispatcher.
    """

    def __init__(
        self,
        maximum_level: PermissionLevel = PermissionLevel.STANDARD,
        *,
        action_permissions: Mapping[str, PermissionLevel] | None = None,
        logger: Logger | None = None,
    ) -> None:
        """Initialize the engine with an immutable permission policy.

        Args:
            maximum_level: Highest permission this engine may grant.
            action_permissions: Optional minimum levels keyed by exact action
                identifier.
            logger: Logger implementation supplied through dependency injection.

        Raises:
            PermissionConfigurationError: If a level or action policy is invalid.
        """

        if not isinstance(maximum_level, PermissionLevel):
            raise PermissionConfigurationError(
                "maximum_level must be a PermissionLevel"
            )

        normalized_permissions: dict[str, PermissionLevel] = {}
        for action, level in dict(action_permissions or {}).items():
            if (
                not isinstance(action, str)
                or not action.strip()
                or action != action.strip()
            ):
                raise PermissionConfigurationError(
                    "action permission keys must be non-empty normalized strings"
                )
            if not isinstance(level, PermissionLevel):
                raise PermissionConfigurationError(
                    "action permission values must be PermissionLevel members"
                )
            normalized_permissions[action] = level

        self._maximum_level = maximum_level
        self._action_permissions: Mapping[str, PermissionLevel] = MappingProxyType(
            normalized_permissions
        )
        self._logger = logger or NullLogger("narvis.execution.permissions")

    @property
    def maximum_level(self) -> PermissionLevel:
        """Return the highest permission level the engine can grant."""

        return self._maximum_level

    @property
    def action_permissions(self) -> Mapping[str, PermissionLevel]:
        """Return the immutable action-specific permission policy."""

        return self._action_permissions

    def required_level_for(self, request: ExecutionRequest) -> PermissionLevel:
        """Return the stricter of request and action-policy requirements.

        Args:
            request: Typed execution request to evaluate.

        Raises:
            ExecutionValidationError: If the request or its permission level is
                not typed correctly.
        """

        if not isinstance(request, ExecutionRequest):
            raise ExecutionValidationError(
                "permission checks require a typed ExecutionRequest"
            )
        if not isinstance(request.permission_level, PermissionLevel):
            raise ExecutionValidationError(
                "request permission_level must be a PermissionLevel"
            )

        configured_level = self._action_permissions.get(
            request.action,
            request.permission_level,
        )
        if (
            _PERMISSION_RANK[configured_level]
            > _PERMISSION_RANK[request.permission_level]
        ):
            return configured_level
        return request.permission_level

    def has_permission(self, required_level: PermissionLevel) -> bool:
        """Return whether the engine may grant ``required_level``."""

        if not isinstance(required_level, PermissionLevel):
            raise ExecutionValidationError("required_level must be a PermissionLevel")
        return _PERMISSION_RANK[self._maximum_level] >= _PERMISSION_RANK[required_level]

    def check_permission(self, request: ExecutionRequest) -> bool:
        """Return whether the configured policy permits ``request``."""

        required_level = self.required_level_for(request)
        allowed = self.has_permission(required_level)
        self._log(
            LogLevel.DEBUG if allowed else LogLevel.WARNING,
            "Execution permission evaluated",
            request_id=request.request_id,
            action=request.action,
            maximum_level=self._maximum_level.value,
            required_level=required_level.value,
            allowed=allowed,
        )
        return allowed

    def require_permission(self, request: ExecutionRequest) -> None:
        """Require permission for ``request`` or raise a typed denial error."""

        if self.check_permission(request):
            return
        required_level = self.required_level_for(request)
        raise PermissionDeniedError(
            f"{request.action!r} requires {required_level.value} permission"
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a log entry without allowing observability failures to alter policy."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["PermissionChecker", "PermissionEngine"]
