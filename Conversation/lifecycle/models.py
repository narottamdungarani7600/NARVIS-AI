"""Strongly typed immutable models for conversation lifecycle management."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from Conversation.core.models import (
    ConversationStatus,
    immutable_mapping,
    new_id,
    utc_now,
)

from .exceptions import RetentionPolicyError


class CleanupReason(str, Enum):
    """Reasons a retained in-memory session may be cleaned."""

    EXPIRED = "expired"
    CLOSED_RETENTION = "closed_retention"
    ARCHIVED_RETENTION = "archived_retention"
    SESSION_LIMIT = "session_limit"


class ExportFormat(str, Enum):
    """Export-ready representations that do not perform file writing."""

    JSON = "json"
    TEXT = "text"
    MARKDOWN = "markdown"


class HealthStatus(str, Enum):
    """Aggregate health classifications for the retained session collection."""

    HEALTHY = "healthy"
    ATTENTION = "attention"
    EMPTY = "empty"


def _text(
    value: object,
    name: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        value != value.strip()
        or len(value) > maximum
        or (not value and not allow_empty)
    ):
        raise ValueError(
            f"{name} must be normalized text of at most {maximum} characters"
        )
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of identifiers")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        for value in result
    ):
        raise ValueError(f"{name} must contain normalized non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _duration(
    value: object,
    name: str,
    *,
    allow_none: bool = True,
) -> timedelta | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, timedelta):
        raise RetentionPolicyError(f"{name} must be a timedelta or None")
    if value < timedelta(0):
        raise RetentionPolicyError(f"{name} cannot be negative")
    return value


@dataclass(slots=True, frozen=True)
class ArchiveMetadata:
    """Immutable metadata describing one conversation archive operation."""

    conversation_id: str
    original_status: ConversationStatus
    archived_at: datetime
    reason: str = ""
    tags: tuple[str, ...] = ()
    retention_until: datetime | None = None
    message_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    archive_id: str = field(default_factory=new_id)
    restored_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        _text(self.archive_id, "archive_id", maximum=128)
        if self.original_status not in {
            ConversationStatus.ACTIVE,
            ConversationStatus.CLOSED,
        }:
            raise ValueError("original_status must be active or closed")
        _time(self.archived_at, "archived_at")
        _text(self.reason, "reason", maximum=2000, allow_empty=True)
        object.__setattr__(self, "tags", _identifiers(self.tags, "tags"))
        if self.retention_until is not None:
            _time(self.retention_until, "retention_until")
            if self.retention_until < self.archived_at:
                raise ValueError("retention_until cannot precede archived_at")
        _count(self.message_count, "message_count")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        if self.restored_at is not None:
            _time(self.restored_at, "restored_at")
            if self.restored_at < self.archived_at:
                raise ValueError("restored_at cannot precede archived_at")

    @property
    def active(self) -> bool:
        """Return whether this archive has not been restored."""

        return self.restored_at is None


@dataclass(slots=True, frozen=True)
class RetentionPolicy:
    """Immutable policy controlling expiration and in-memory session cleanup."""

    max_age: timedelta | None = None
    inactive_timeout: timedelta | None = None
    closed_retention: timedelta | None = None
    archived_retention: timedelta | None = None
    expired_retention: timedelta | None = timedelta(0)
    max_sessions: int | None = None
    preserve_current: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_age",
            "inactive_timeout",
            "closed_retention",
            "archived_retention",
            "expired_retention",
        ):
            _duration(getattr(self, name), name)
        if self.max_sessions is not None:
            if (
                isinstance(self.max_sessions, bool)
                or not isinstance(self.max_sessions, int)
                or self.max_sessions < 1
            ):
                raise RetentionPolicyError("max_sessions must be a positive integer")
        if not isinstance(self.preserve_current, bool):
            raise RetentionPolicyError("preserve_current must be a bool")


@dataclass(slots=True, frozen=True)
class ContextCleanupPolicy:
    """Immutable controls for removing transient conversation context."""

    clear_topics: bool = True
    clear_summary: bool = True
    clear_references: bool = True
    clear_metadata: bool = True

    def __post_init__(self) -> None:
        values = (
            self.clear_topics,
            self.clear_summary,
            self.clear_references,
            self.clear_metadata,
        )
        if any(not isinstance(value, bool) for value in values):
            raise TypeError("context cleanup policy values must be bools")
        if not any(values):
            raise ValueError("context cleanup policy must clear at least one field")


@dataclass(slots=True, frozen=True)
class SessionInfo:
    """Immutable lifecycle view used for multi-session listing."""

    session_id: str
    status: ConversationStatus
    message_count: int
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime
    expires_at: datetime | None = None
    archive_id: str | None = None
    current: bool = False

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id", maximum=128)
        if not isinstance(self.status, ConversationStatus):
            raise TypeError("status must be a ConversationStatus")
        _count(self.message_count, "message_count")
        created = _time(self.created_at, "created_at")
        updated = _time(self.updated_at, "updated_at")
        accessed = _time(self.last_accessed_at, "last_accessed_at")
        if updated < created or accessed < created:
            raise ValueError("session lifecycle timestamps cannot precede creation")
        if self.expires_at is not None:
            expires = _time(self.expires_at, "expires_at")
            if expires < created:
                raise ValueError("expires_at cannot precede session creation")
        if self.archive_id is not None:
            _text(self.archive_id, "archive_id", maximum=128)
        if not isinstance(self.current, bool):
            raise TypeError("current must be a bool")

    @property
    def conversation_id(self) -> str:
        """Return the session identifier using conversation terminology."""

        return self.session_id


@dataclass(slots=True, frozen=True)
class CleanupCandidate:
    """One immutable decision produced by retention evaluation."""

    session_id: str
    reason: CleanupReason
    eligible_at: datetime

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id", maximum=128)
        if not isinstance(self.reason, CleanupReason):
            raise TypeError("reason must be a CleanupReason")
        _time(self.eligible_at, "eligible_at")


@dataclass(slots=True, frozen=True)
class CleanupReport:
    """Immutable result of one in-memory cleanup pass."""

    examined_sessions: int
    expired_session_ids: tuple[str, ...]
    removed_session_ids: tuple[str, ...]
    candidates: tuple[CleanupCandidate, ...]
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        _count(self.examined_sessions, "examined_sessions")
        expired = _identifiers(self.expired_session_ids, "expired_session_ids")
        removed = _identifiers(self.removed_session_ids, "removed_session_ids")
        candidates = tuple(self.candidates)
        if any(not isinstance(candidate, CleanupCandidate) for candidate in candidates):
            raise TypeError("candidates must contain CleanupCandidate values")
        if set(removed) != {candidate.session_id for candidate in candidates}:
            raise ValueError("removed_session_ids must match cleanup candidates")
        started = _time(self.started_at, "started_at")
        completed = _time(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("completed_at cannot precede started_at")
        object.__setattr__(self, "expired_session_ids", expired)
        object.__setattr__(self, "removed_session_ids", removed)
        object.__setattr__(self, "candidates", candidates)

    @property
    def removed_count(self) -> int:
        """Return the number of sessions removed from in-memory storage."""

        return len(self.removed_session_ids)

    @property
    def expired_count(self) -> int:
        """Return the number of sessions newly marked expired."""

        return len(self.expired_session_ids)


@dataclass(slots=True, frozen=True)
class ConversationExport:
    """Immutable export-ready artifact with no filesystem behavior."""

    conversation_id: str
    format: ExportFormat
    content: Mapping[str, Any] | str
    mime_type: str
    filename_hint: str
    message_count: int
    generated_at: datetime = field(default_factory=utc_now)
    export_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        _text(self.export_id, "export_id", maximum=128)
        if not isinstance(self.format, ExportFormat):
            raise TypeError("format must be an ExportFormat")
        if isinstance(self.content, Mapping):
            object.__setattr__(self, "content", immutable_mapping(self.content))
        elif not isinstance(self.content, str):
            raise TypeError("content must be an immutable mapping or string")
        _text(self.mime_type, "mime_type", maximum=128)
        _text(self.filename_hint, "filename_hint", maximum=256)
        if any(separator in self.filename_hint for separator in ("/", "\\")):
            raise ValueError("filename_hint cannot contain path separators")
        _count(self.message_count, "message_count")
        _time(self.generated_at, "generated_at")

    @property
    def writes_files(self) -> bool:
        """State the invariant that exports never write files."""

        return False


@dataclass(slots=True, frozen=True)
class ConversationHealth:
    """Immutable aggregate health statistics for retained conversations."""

    status: HealthStatus
    total_sessions: int
    active_sessions: int
    closed_sessions: int
    archived_sessions: int
    expired_sessions: int
    total_messages: int
    current_session_id: str | None
    expiring_sessions: int
    health_score: float
    generated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.status, HealthStatus):
            raise TypeError("status must be a HealthStatus")
        counts = (
            self.total_sessions,
            self.active_sessions,
            self.closed_sessions,
            self.archived_sessions,
            self.expired_sessions,
            self.total_messages,
            self.expiring_sessions,
        )
        for index, count in enumerate(counts):
            _count(count, f"health count {index}")
        if self.total_sessions != (
            self.active_sessions
            + self.closed_sessions
            + self.archived_sessions
            + self.expired_sessions
        ):
            raise ValueError("lifecycle status counts must equal total_sessions")
        if self.current_session_id is not None:
            _text(self.current_session_id, "current_session_id", maximum=128)
        if isinstance(self.health_score, bool) or not isinstance(
            self.health_score,
            (int, float),
        ):
            raise TypeError("health_score must be numeric")
        score = float(self.health_score)
        if not 0.0 <= score <= 100.0:
            raise ValueError("health_score must be between 0 and 100")
        object.__setattr__(self, "health_score", score)
        _time(self.generated_at, "generated_at")


@dataclass(slots=True, frozen=True)
class SessionSwitch:
    """Immutable result of selecting a different active session."""

    current_session_id: str
    previous_session_id: str | None
    switched_at: datetime

    def __post_init__(self) -> None:
        _text(self.current_session_id, "current_session_id", maximum=128)
        if self.previous_session_id is not None:
            _text(self.previous_session_id, "previous_session_id", maximum=128)
        _time(self.switched_at, "switched_at")

    @property
    def changed(self) -> bool:
        """Return whether selection changed to a different session."""

        return self.current_session_id != self.previous_session_id


__all__ = [
    "ArchiveMetadata",
    "CleanupCandidate",
    "CleanupReason",
    "CleanupReport",
    "ContextCleanupPolicy",
    "ConversationExport",
    "ConversationHealth",
    "ExportFormat",
    "HealthStatus",
    "RetentionPolicy",
    "SessionInfo",
    "SessionSwitch",
]
