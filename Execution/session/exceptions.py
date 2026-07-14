"""Exception hierarchy for the safe execution session layer."""

from __future__ import annotations


class ExecutionSessionError(Exception):
    """Base exception for approval queue and session failures."""


class SessionValidationError(ExecutionSessionError, ValueError):
    """Raised when a safe execution model or operation is invalid."""


class InvalidApprovalError(SessionValidationError):
    """Raised when an approval response or token fails validation."""


class DuplicateApprovalError(InvalidApprovalError):
    """Raised when an approval request is submitted or answered twice."""


class ApprovalNotFoundError(InvalidApprovalError, LookupError):
    """Raised when an approval request cannot be found."""


class ApprovalExpiredError(InvalidApprovalError):
    """Raised when an expired request or token is used."""


class GatewayAuthorizationError(InvalidApprovalError):
    """Raised when the trusted gateway does not return a safe planning result."""


class QueueError(ExecutionSessionError):
    """Base exception for execution queue failures."""


class QueueEmptyError(QueueError, LookupError):
    """Raised when an item is requested from an empty queue."""


class QueueItemNotFoundError(QueueError, LookupError):
    """Raised when a queue item cannot be found."""


class DuplicateQueueItemError(QueueError, ValueError):
    """Raised when the same approval request is enqueued twice."""


class SessionNotFoundError(ExecutionSessionError, LookupError):
    """Raised when an execution session cannot be found."""


class DuplicateSessionError(ExecutionSessionError, ValueError):
    """Raised when an execution session identifier is already retained."""


class SessionExpiredError(ExecutionSessionError):
    """Raised when an operation requires an active execution session."""


__all__ = [
    "ApprovalExpiredError",
    "ApprovalNotFoundError",
    "DuplicateApprovalError",
    "DuplicateQueueItemError",
    "DuplicateSessionError",
    "ExecutionSessionError",
    "GatewayAuthorizationError",
    "InvalidApprovalError",
    "QueueEmptyError",
    "QueueError",
    "QueueItemNotFoundError",
    "SessionExpiredError",
    "SessionNotFoundError",
    "SessionValidationError",
]
