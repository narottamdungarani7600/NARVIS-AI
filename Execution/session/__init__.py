"""Public API for NARVIS approval-based execution sessions."""

from .approval import (
    ApprovalManager,
    ApprovalService,
    GatewayAuthorizer,
)
from .exceptions import (
    ApprovalExpiredError,
    ApprovalNotFoundError,
    DuplicateApprovalError,
    DuplicateQueueItemError,
    DuplicateSessionError,
    ExecutionSessionError,
    GatewayAuthorizationError,
    InvalidApprovalError,
    QueueEmptyError,
    QueueError,
    QueueItemNotFoundError,
    SessionExpiredError,
    SessionNotFoundError,
    SessionValidationError,
)
from .models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalToken,
    ExecutionHistoryEntry,
    ExecutionSession,
    QueueStatus,
    SessionStatus,
)
from .queue import EventPublisher, ExecutionQueue
from .session import ExecutionSessionManager, SessionManager

__all__ = [
    "ApprovalDecision",
    "ApprovalExpiredError",
    "ApprovalManager",
    "ApprovalNotFoundError",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalService",
    "ApprovalStatus",
    "ApprovalToken",
    "DuplicateApprovalError",
    "DuplicateQueueItemError",
    "DuplicateSessionError",
    "EventPublisher",
    "ExecutionHistoryEntry",
    "ExecutionQueue",
    "ExecutionSession",
    "ExecutionSessionError",
    "ExecutionSessionManager",
    "GatewayAuthorizationError",
    "GatewayAuthorizer",
    "InvalidApprovalError",
    "QueueEmptyError",
    "QueueError",
    "QueueItemNotFoundError",
    "QueueStatus",
    "SessionExpiredError",
    "SessionManager",
    "SessionNotFoundError",
    "SessionStatus",
    "SessionValidationError",
]
