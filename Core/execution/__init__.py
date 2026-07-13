"""Trusted execution boundary primitives for NARVIS Core.

The package exposes the typed models, permission service, and inert gateway
used to validate future execution requests.  Sprint 1 deliberately performs
no host action and invokes no dispatcher.
"""

from .exceptions import (
    DispatcherUnavailableError,
    ExecutionGatewayError,
    ExecutionValidationError,
    PermissionConfigurationError,
    PermissionDeniedError,
)
from .gateway import EventPublisher, ExecutionDispatcher, TrustedExecutionGateway
from .models import ExecutionRequest, ExecutionResult, ExecutionStatus, PermissionLevel
from .permissions import PermissionChecker, PermissionEngine

__all__ = [
    "DispatcherUnavailableError",
    "EventPublisher",
    "ExecutionDispatcher",
    "ExecutionGatewayError",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionValidationError",
    "PermissionChecker",
    "PermissionConfigurationError",
    "PermissionDeniedError",
    "PermissionEngine",
    "PermissionLevel",
    "TrustedExecutionGateway",
]
