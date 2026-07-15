"""Strongly typed immutable models for conversation core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class MessageRole(str, Enum):
    """Supported conversation message roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationStatus(str, Enum):
    """Lifecycle states for a conversation session."""

    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"
    EXPIRED = "expired"


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_id() -> str:
    """Return an opaque non-semantic identifier."""

    return uuid4().hex


def _require_text(
    name: str,
    value: object,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> None:
    """Require normalized bounded text."""

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


def _require_time(name: str, value: object) -> None:
    """Require a timezone-aware timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _freeze(value: Any) -> Any:
    """Recursively detach mutable metadata containers."""

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


def _references(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    """Validate normalized unique reference identifiers."""

    normalized = tuple(values)
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        for value in normalized
    ):
        raise ValueError(f"{name} must contain normalized non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} cannot contain duplicates")
    return normalized


@dataclass(slots=True, frozen=True)
class ConversationMessage:
    """One immutable user, assistant, or system conversation message."""

    conversation_id: str
    content: str
    role: MessageRole
    metadata: Mapping[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Validate message identity, role, content, timestamp, and metadata."""

        _require_text("conversation_id", self.conversation_id, maximum=128)
        _require_text("message_id", self.message_id, maximum=128)
        if not isinstance(self.role, MessageRole):
            raise TypeError("role must be a MessageRole")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string")
        if len(self.content) > 100_000:
            raise ValueError("content cannot exceed 100000 characters")
        _require_time("timestamp", self.timestamp)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @classmethod
    def user(
        cls,
        conversation_id: str,
        content: str,
        **kwargs: Any,
    ) -> ConversationMessage:
        """Create a user-role message."""

        return cls(
            conversation_id=conversation_id,
            content=content,
            role=MessageRole.USER,
            **kwargs,
        )

    @classmethod
    def assistant(
        cls,
        conversation_id: str,
        content: str,
        **kwargs: Any,
    ) -> ConversationMessage:
        """Create an assistant-role message."""

        return cls(
            conversation_id=conversation_id,
            content=content,
            role=MessageRole.ASSISTANT,
            **kwargs,
        )

    @classmethod
    def system(
        cls,
        conversation_id: str,
        content: str,
        **kwargs: Any,
    ) -> ConversationMessage:
        """Create a system-role message."""

        return cls(
            conversation_id=conversation_id,
            content=content,
            role=MessageRole.SYSTEM,
            **kwargs,
        )


Message = ConversationMessage


@dataclass(slots=True, frozen=True)
class UserMessage(ConversationMessage):
    """Convenience model with an immutable USER role."""

    role: MessageRole = field(default=MessageRole.USER, init=False)


@dataclass(slots=True, frozen=True)
class AssistantMessage(ConversationMessage):
    """Convenience model with an immutable ASSISTANT role."""

    role: MessageRole = field(default=MessageRole.ASSISTANT, init=False)


@dataclass(slots=True, frozen=True)
class SystemMessage(ConversationMessage):
    """Convenience model with an immutable SYSTEM role."""

    role: MessageRole = field(default=MessageRole.SYSTEM, init=False)


@dataclass(slots=True, frozen=True)
class ConversationHistory:
    """Immutable ordered message history for one conversation."""

    conversation_id: str
    messages: tuple[ConversationMessage, ...] = ()
    cleared_messages: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Validate ordered, conversation-bound message history."""

        _require_text("conversation_id", self.conversation_id, maximum=128)
        if isinstance(self.messages, (str, bytes)):
            raise TypeError("messages must contain ConversationMessage instances")
        messages = tuple(self.messages)
        if any(not isinstance(message, ConversationMessage) for message in messages):
            raise TypeError("messages must contain ConversationMessage instances")
        if any(message.conversation_id != self.conversation_id for message in messages):
            raise ValueError("all messages must belong to the history conversation")
        if any(
            later.timestamp < earlier.timestamp
            for earlier, later in zip(messages, messages[1:])
        ):
            raise ValueError("conversation messages must be timestamp ordered")
        object.__setattr__(self, "messages", messages)
        if (
            isinstance(self.cleared_messages, bool)
            or not isinstance(self.cleared_messages, int)
            or self.cleared_messages < 0
        ):
            raise ValueError("cleared_messages must be a non-negative integer")
        _require_time("created_at", self.created_at)
        _require_time("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if any(message.timestamp < self.created_at for message in messages):
            raise ValueError("message timestamps cannot precede history creation")
        if any(message.timestamp > self.updated_at for message in messages):
            raise ValueError("message timestamps cannot follow history updated_at")

    @property
    def count(self) -> int:
        """Return the retained message count."""

        return len(self.messages)


@dataclass(slots=True, frozen=True)
class ConversationContext:
    """Immutable topic, skill, agent, and summary context."""

    conversation_id: str
    active_topic: str = ""
    previous_topic: str = ""
    referenced_skills: tuple[str, ...] = ()
    referenced_agents: tuple[str, ...] = ()
    summary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=utc_now)
    referenced_memories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate context text, references, metadata, and timestamp."""

        _require_text("conversation_id", self.conversation_id, maximum=128)
        _require_text(
            "active_topic",
            self.active_topic,
            maximum=1024,
            allow_empty=True,
        )
        _require_text(
            "previous_topic",
            self.previous_topic,
            maximum=1024,
            allow_empty=True,
        )
        if not isinstance(self.summary, str) or len(self.summary) > 20_000:
            raise ValueError("summary must be a string of at most 20000 characters")
        if isinstance(self.referenced_skills, (str, bytes)):
            raise TypeError("referenced_skills must be a sequence of identifiers")
        if isinstance(self.referenced_agents, (str, bytes)):
            raise TypeError("referenced_agents must be a sequence of identifiers")
        if isinstance(self.referenced_memories, (str, bytes)):
            raise TypeError("referenced_memories must be a sequence of identifiers")
        object.__setattr__(
            self,
            "referenced_skills",
            _references("referenced_skills", tuple(self.referenced_skills)),
        )
        object.__setattr__(
            self,
            "referenced_agents",
            _references("referenced_agents", tuple(self.referenced_agents)),
        )
        object.__setattr__(
            self,
            "referenced_memories",
            _references("referenced_memories", tuple(self.referenced_memories)),
        )
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        _require_time("updated_at", self.updated_at)


@dataclass(slots=True, frozen=True)
class ConversationSession:
    """Immutable conversation lifecycle snapshot."""

    session_id: str
    status: ConversationStatus
    history: ConversationHistory
    context: ConversationContext
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    closed_at: datetime | None = None
    resumed_at: datetime | None = None
    resume_count: int = 0
    archived_at: datetime | None = None
    expires_at: datetime | None = None
    expired_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate exact session, history, context, and lifecycle bindings."""

        _require_text("session_id", self.session_id, maximum=128)
        if not isinstance(self.status, ConversationStatus):
            raise TypeError("status must be a ConversationStatus")
        if not isinstance(self.history, ConversationHistory):
            raise TypeError("history must be a ConversationHistory")
        if not isinstance(self.context, ConversationContext):
            raise TypeError("context must be a ConversationContext")
        if self.history.conversation_id != self.session_id:
            raise ValueError("history must be bound to the session")
        if self.context.conversation_id != self.session_id:
            raise ValueError("context must be bound to the session")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        _require_time("created_at", self.created_at)
        _require_time("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.closed_at is not None:
            _require_time("closed_at", self.closed_at)
            if self.closed_at < self.created_at:
                raise ValueError("closed_at cannot precede created_at")
        if self.resumed_at is not None:
            _require_time("resumed_at", self.resumed_at)
            if self.resumed_at < self.created_at:
                raise ValueError("resumed_at cannot precede created_at")
        if self.archived_at is not None:
            _require_time("archived_at", self.archived_at)
            if self.archived_at < self.created_at:
                raise ValueError("archived_at cannot precede created_at")
        if self.expires_at is not None:
            _require_time("expires_at", self.expires_at)
            if self.expires_at < self.created_at:
                raise ValueError("expires_at cannot precede created_at")
        if self.expired_at is not None:
            _require_time("expired_at", self.expired_at)
            if self.expired_at < self.created_at:
                raise ValueError("expired_at cannot precede created_at")
        if self.status is ConversationStatus.CLOSED and self.closed_at is None:
            raise ValueError("closed conversations require closed_at")
        if self.status is ConversationStatus.ARCHIVED and self.archived_at is None:
            raise ValueError("archived conversations require archived_at")
        if self.status is ConversationStatus.EXPIRED and self.expired_at is None:
            raise ValueError("expired conversations require expired_at")
        if (
            isinstance(self.resume_count, bool)
            or not isinstance(self.resume_count, int)
            or self.resume_count < 0
        ):
            raise ValueError("resume_count must be a non-negative integer")

    @property
    def conversation_id(self) -> str:
        """Return the session identifier using conversation terminology."""

        return self.session_id

    @property
    def active(self) -> bool:
        """Return whether the conversation accepts updates."""

        return self.status is ConversationStatus.ACTIVE

    @property
    def closed(self) -> bool:
        """Return whether the conversation is closed."""

        return self.status is ConversationStatus.CLOSED

    @property
    def archived(self) -> bool:
        """Return whether the conversation is archived."""

        return self.status is ConversationStatus.ARCHIVED

    @property
    def expired(self) -> bool:
        """Return whether the conversation has expired."""

        return self.status is ConversationStatus.EXPIRED

    @property
    def mutable(self) -> bool:
        """Return whether the conversation accepts content or context changes."""

        return self.status is ConversationStatus.ACTIVE

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        """Return retained history messages."""

        return self.history.messages


Conversation = ConversationSession


@dataclass(slots=True, frozen=True)
class ConversationStatistics:
    """Immutable aggregate statistics for one conversation."""

    conversation_id: str
    status: ConversationStatus
    total_messages: int
    user_messages: int
    assistant_messages: int
    system_messages: int
    cleared_messages: int
    resume_count: int
    active_topic: str
    referenced_skill_count: int
    referenced_agent_count: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Validate counts and lifecycle facts."""

        _require_text("conversation_id", self.conversation_id, maximum=128)
        if not isinstance(self.status, ConversationStatus):
            raise TypeError("status must be a ConversationStatus")
        counts = (
            self.total_messages,
            self.user_messages,
            self.assistant_messages,
            self.system_messages,
            self.cleared_messages,
            self.resume_count,
            self.referenced_skill_count,
            self.referenced_agent_count,
        )
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in counts
        ):
            raise ValueError(
                "conversation statistic counts must be non-negative integers"
            )
        if self.total_messages != (
            self.user_messages + self.assistant_messages + self.system_messages
        ):
            raise ValueError("role message counts must equal total_messages")
        _require_text(
            "active_topic",
            self.active_topic,
            maximum=1024,
            allow_empty=True,
        )
        _require_time("created_at", self.created_at)
        _require_time("updated_at", self.updated_at)

    @property
    def message_count(self) -> int:
        """Return the retained message count."""

        return self.total_messages


__all__ = [
    "AssistantMessage",
    "Conversation",
    "ConversationContext",
    "ConversationHistory",
    "ConversationMessage",
    "ConversationSession",
    "ConversationStatistics",
    "ConversationStatus",
    "Message",
    "MessageRole",
    "SystemMessage",
    "UserMessage",
]
