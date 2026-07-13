"""Typed models shared by the trusted execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class ExecutionStatus(str, Enum):
    """Lifecycle states available to execution gateway results.

    Sprint 1 emits only :attr:`AUTHORIZED`, :attr:`DENIED`, and
    :attr:`REJECTED`.  The remaining states define the result contract that a
    future dispatcher may use without changing callers of the gateway.
    """

    PENDING = "pending"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PermissionLevel(str, Enum):
    """Ordered permission levels recognized by the execution boundary."""

    NONE = "none"
    READ_ONLY = "read_only"
    STANDARD = "standard"
    ELEVATED = "elevated"
    ADMINISTRATOR = "administrator"


def _new_request_id() -> str:
    """Return an opaque identifier for a newly constructed request."""

    return uuid4().hex


@dataclass(slots=True, frozen=True)
class ExecutionRequest:
    """Describe one proposed action before any execution is attempted.

    Attributes:
        action: Stable action identifier understood by a future dispatcher.
        permission_level: Minimum permission declared for the action.
        parameters: Action-specific input retained as inert data in Sprint 1.
        metadata: Non-executable correlation and observability information.
        request_id: Opaque identifier used to correlate logs, events, and the
            resulting decision.
    """

    action: str
    permission_level: PermissionLevel = PermissionLevel.STANDARD
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=_new_request_id)


@dataclass(slots=True, frozen=True)
class ExecutionResult:
    """Represent the gateway outcome for one execution request.

    ``executed`` and ``dispatcher_invoked`` are explicit safety facts.  They
    remain ``False`` for every result produced by the Sprint 1 gateway.

    Attributes:
        request_id: Identifier copied from the evaluated request when valid.
        action: Action identifier copied from the evaluated request when valid.
        status: Typed gateway outcome.
        message: Human-readable explanation of the outcome.
        permission_level: Effective permission level required by the policy.
        reason_code: Stable machine-readable reason for the outcome.
        output: Reserved result data for a future dispatcher integration.
        executed: Whether a real action was completed.
        dispatcher_invoked: Whether an execution dispatcher was called.
    """

    request_id: str
    action: str
    status: ExecutionStatus
    message: str
    permission_level: PermissionLevel | None = None
    reason_code: str = ""
    output: Mapping[str, Any] = field(default_factory=dict)
    executed: bool = False
    dispatcher_invoked: bool = False

    @property
    def authorized(self) -> bool:
        """Return whether validation and permission checks passed."""

        return self.status is ExecutionStatus.AUTHORIZED

    @property
    def successful(self) -> bool:
        """Return whether a future dispatcher reported successful execution."""

        return self.status is ExecutionStatus.SUCCEEDED and self.executed


__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "PermissionLevel",
]
