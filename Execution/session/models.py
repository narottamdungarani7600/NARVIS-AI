"""Strongly typed immutable models for approval-based execution planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from Core.execution.models import ExecutionRequest, ExecutionStatus


class ApprovalDecision(str, Enum):
    """Decisions accepted from an approval authority."""

    APPROVE = "approve"
    DENY = "deny"

    # Compatibility aliases for callers that use outcome terminology.
    APPROVED = "approve"
    DENIED = "deny"
    ALLOW = "approve"
    REJECT = "deny"


class ApprovalStatus(str, Enum):
    """Lifecycle states for an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SessionStatus(str, Enum):
    """Lifecycle states for a planning-only execution session."""

    ACTIVE = "active"
    EXPIRED = "expired"
    CLOSED = "closed"


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_id() -> str:
    """Return a non-semantic opaque identifier."""

    return uuid4().hex


def _default_expiry() -> datetime:
    """Return the conservative default approval expiry."""

    return utc_now() + timedelta(minutes=5)


def _require_text(name: str, value: object, *, maximum: int = 256) -> None:
    """Require a normalized, bounded identifier or label."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise ValueError(
            f"{name} must be a normalized non-empty string of at most "
            f"{maximum} characters"
        )


def _require_datetime(name: str, value: object) -> None:
    """Require a timezone-aware timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _freeze(value: Any) -> Any:
    """Recursively detach mutable containers used by immutable models."""

    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("metadata keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a recursively detached read-only mapping."""

    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    return _freeze(value)


@dataclass(slots=True, frozen=True)
class ApprovalToken:
    """Opaque, request-bound proof of an approval decision.

    Tokens are planning artifacts only.  This sprint has no consumer capable
    of dispatching or executing an action.
    """

    request_id: str
    session_id: str
    issued_to: str
    token_id: str = field(default_factory=new_id)
    issued_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=_default_expiry)

    def __post_init__(self) -> None:
        """Validate exact bindings and expiry."""

        _require_text("request_id", self.request_id, maximum=128)
        _require_text("session_id", self.session_id, maximum=128)
        _require_text("issued_to", self.issued_to, maximum=128)
        _require_text("token_id", self.token_id, maximum=256)
        _require_datetime("issued_at", self.issued_at)
        _require_datetime("expires_at", self.expires_at)
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")

    @property
    def token(self) -> str:
        """Return the opaque token identifier as a compatibility alias."""

        return self.token_id

    @property
    def approval_id(self) -> str:
        """Return the bound approval request identifier."""

        return self.request_id

    def is_expired(self, at: datetime | None = None) -> bool:
        """Return whether the token has expired at an explicit or current time."""

        evaluated_at = at or utc_now()
        _require_datetime("at", evaluated_at)
        return evaluated_at >= self.expires_at


@dataclass(slots=True, frozen=True)
class ApprovalRequest:
    """One immutable human-approval request for an inert gateway request."""

    execution_request: ExecutionRequest
    session_id: str
    requested_by: str
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=new_id)
    requested_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=_default_expiry)
    status: ApprovalStatus = ApprovalStatus.PENDING
    gateway_status: ExecutionStatus | None = None
    gateway_reason_code: str = ""

    def __post_init__(self) -> None:
        """Validate request data and detach all mutable mappings."""

        if not isinstance(self.execution_request, ExecutionRequest):
            raise TypeError("execution_request must be an ExecutionRequest")
        _require_text("request_id", self.request_id, maximum=128)
        _require_text("session_id", self.session_id, maximum=128)
        _require_text("requested_by", self.requested_by, maximum=128)
        if not isinstance(self.description, str) or len(self.description) > 2048:
            raise ValueError("description must be a string of at most 2048 characters")
        _require_datetime("requested_at", self.requested_at)
        _require_datetime("expires_at", self.expires_at)
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be later than requested_at")
        if not isinstance(self.status, ApprovalStatus):
            raise TypeError("status must be an ApprovalStatus")
        if self.gateway_status is not None and not isinstance(
            self.gateway_status, ExecutionStatus
        ):
            raise TypeError("gateway_status must be an ExecutionStatus or None")
        if not isinstance(self.gateway_reason_code, str):
            raise TypeError("gateway_reason_code must be a string")

        execution_request = replace(
            self.execution_request,
            parameters=immutable_mapping(self.execution_request.parameters),
            metadata=immutable_mapping(self.execution_request.metadata),
        )
        object.__setattr__(self, "execution_request", execution_request)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def approval_id(self) -> str:
        """Return the approval identifier using explicit terminology."""

        return self.request_id

    @property
    def execution_request_id(self) -> str:
        """Return the trusted gateway request identifier."""

        return self.execution_request.request_id

    @property
    def action(self) -> str:
        """Return the inert action label from the gateway request."""

        return self.execution_request.action

    @property
    def pending(self) -> bool:
        """Return whether this request can still receive a response."""

        return self.status is ApprovalStatus.PENDING


@dataclass(slots=True, frozen=True)
class ApprovalResponse:
    """One immutable decision submitted for an approval request."""

    request_id: str
    decision: ApprovalDecision
    responded_by: str
    reason: str = ""
    responded_at: datetime = field(default_factory=utc_now)
    token: ApprovalToken | None = None

    def __post_init__(self) -> None:
        """Validate the response without interpreting it as executable input."""

        _require_text("request_id", self.request_id, maximum=128)
        _require_text("responded_by", self.responded_by, maximum=128)
        if not isinstance(self.decision, ApprovalDecision):
            raise TypeError("decision must be an ApprovalDecision")
        if not isinstance(self.reason, str) or len(self.reason) > 2048:
            raise ValueError("reason must be a string of at most 2048 characters")
        _require_datetime("responded_at", self.responded_at)
        if self.token is not None and not isinstance(self.token, ApprovalToken):
            raise TypeError("token must be an ApprovalToken or None")
        if self.decision is ApprovalDecision.DENY and self.token is not None:
            raise ValueError("denied responses cannot contain an approval token")

    @property
    def approval_id(self) -> str:
        """Return the target approval identifier."""

        return self.request_id

    @property
    def approved(self) -> bool:
        """Return whether approval was explicitly granted."""

        return self.decision is ApprovalDecision.APPROVE

    @property
    def status(self) -> ApprovalStatus:
        """Translate the decision into its terminal request status."""

        if self.approved:
            return ApprovalStatus.APPROVED
        return ApprovalStatus.DENIED


@dataclass(slots=True, frozen=True)
class QueueStatus:
    """Immutable snapshot of approval queue state."""

    size: int
    request_ids: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Validate the queue snapshot."""

        object.__setattr__(self, "request_ids", tuple(self.request_ids))
        if self.size < 0 or self.size != len(self.request_ids):
            raise ValueError("size must match the number of request_ids")
        if any(not isinstance(item, str) or not item for item in self.request_ids):
            raise ValueError("request_ids must contain non-empty strings")
        _require_datetime("updated_at", self.updated_at)

    @property
    def count(self) -> int:
        """Return the number of queued approval requests."""

        return self.size

    @property
    def empty(self) -> bool:
        """Return whether the snapshot contains no requests."""

        return self.size == 0


@dataclass(slots=True, frozen=True)
class ExecutionHistoryEntry:
    """An inert execution-plan history record; it can never claim execution."""

    request_id: str
    action: str
    approval_status: ApprovalStatus
    details: Mapping[str, Any] = field(default_factory=dict)
    history_id: str = field(default_factory=new_id)
    recorded_at: datetime = field(default_factory=utc_now)
    executed: bool = False

    def __post_init__(self) -> None:
        """Validate the immutable, non-executing history record."""

        _require_text("request_id", self.request_id, maximum=128)
        _require_text("action", self.action, maximum=256)
        _require_text("history_id", self.history_id, maximum=128)
        if not isinstance(self.approval_status, ApprovalStatus):
            raise TypeError("approval_status must be an ApprovalStatus")
        _require_datetime("recorded_at", self.recorded_at)
        if self.executed is not False:
            raise ValueError("safe execution history cannot record real execution")
        object.__setattr__(self, "details", immutable_mapping(self.details))

    @property
    def status(self) -> ApprovalStatus:
        """Return the approval status using concise history terminology."""

        return self.approval_status


@dataclass(slots=True, frozen=True)
class ExecutionSession:
    """Immutable snapshot of a planning-only execution session."""

    session_id: str
    owner_id: str
    created_at: datetime
    expires_at: datetime
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: Mapping[str, Any] = field(default_factory=dict)
    approval_request_ids: tuple[str, ...] = ()
    history: tuple[ExecutionHistoryEntry, ...] = ()

    def __post_init__(self) -> None:
        """Validate session lifecycle and recursively freeze metadata."""

        _require_text("session_id", self.session_id, maximum=128)
        _require_text("owner_id", self.owner_id, maximum=128)
        _require_datetime("created_at", self.created_at)
        _require_datetime("expires_at", self.expires_at)
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if not isinstance(self.status, SessionStatus):
            raise TypeError("status must be a SessionStatus")
        approval_ids = tuple(self.approval_request_ids)
        if any(not isinstance(item, str) or not item for item in approval_ids):
            raise ValueError("approval_request_ids must contain non-empty strings")
        history = tuple(self.history)
        if any(not isinstance(item, ExecutionHistoryEntry) for item in history):
            raise TypeError("history must contain ExecutionHistoryEntry instances")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        object.__setattr__(self, "approval_request_ids", approval_ids)
        object.__setattr__(self, "history", history)

    @property
    def approvals(self) -> tuple[str, ...]:
        """Return tracked approval identifiers."""

        return self.approval_request_ids

    @property
    def execution_history(self) -> tuple[ExecutionHistoryEntry, ...]:
        """Return retained planning history."""

        return self.history

    @property
    def active(self) -> bool:
        """Return whether the retained lifecycle status is active."""

        return self.status is SessionStatus.ACTIVE

    def is_expired(self, at: datetime | None = None) -> bool:
        """Return whether the session has reached its deadline."""

        evaluated_at = at or utc_now()
        _require_datetime("at", evaluated_at)
        return self.status is SessionStatus.EXPIRED or evaluated_at >= self.expires_at


__all__ = [
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalStatus",
    "ApprovalToken",
    "ExecutionHistoryEntry",
    "ExecutionSession",
    "QueueStatus",
    "SessionStatus",
]
