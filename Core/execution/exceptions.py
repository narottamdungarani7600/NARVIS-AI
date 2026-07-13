"""Exception hierarchy for trusted execution gateway services."""

from __future__ import annotations


class ExecutionGatewayError(Exception):
    """Base exception raised by trusted execution boundary components."""


class ExecutionValidationError(ExecutionGatewayError, ValueError):
    """Raised when an execution request violates the typed request contract."""


class PermissionConfigurationError(ExecutionGatewayError, ValueError):
    """Raised when a permission engine is configured with an invalid policy."""


class PermissionDeniedError(ExecutionGatewayError, PermissionError):
    """Raised by strict permission checks when a request is not permitted."""


class DispatcherUnavailableError(ExecutionGatewayError, RuntimeError):
    """Raised if dispatch is requested before a dispatcher is integrated."""


__all__ = [
    "DispatcherUnavailableError",
    "ExecutionGatewayError",
    "ExecutionValidationError",
    "PermissionConfigurationError",
    "PermissionDeniedError",
]
