"""Strongly typed immutable models for intelligent conversation context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from Conversation.core.models import (
    ConversationMessage,
    MessageRole,
    immutable_mapping,
    new_id,
    utc_now,
)


class SearchMode(str, Enum):
    """Supported deterministic query matching modes."""

    ANY = "any"
    ALL = "all"
    PHRASE = "phrase"


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
        identifiers = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    if any(
        not isinstance(identifier, str)
        or not identifier
        or identifier != identifier.strip()
        or len(identifier) > 256
        for identifier in identifiers
    ):
        raise ValueError(f"{name} must contain normalized non-empty strings")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{name} cannot contain duplicates")
    return identifiers


@dataclass(slots=True, frozen=True)
class ConversationSummary:
    """One immutable extractive summary of retained conversation messages."""

    conversation_id: str
    text: str
    message_count: int
    source_message_ids: tuple[str, ...] = ()
    active_topic: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    summary_id: str = field(default_factory=new_id)
    generated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        _text(self.summary_id, "summary_id", maximum=128)
        _text(self.text, "summary text", maximum=20_000)
        count = _count(self.message_count, "message_count")
        identifiers = _identifiers(self.source_message_ids, "source_message_ids")
        if len(identifiers) > count:
            raise ValueError("source_message_ids cannot exceed message_count")
        _text(self.active_topic, "active_topic", maximum=1024, allow_empty=True)
        object.__setattr__(self, "source_message_ids", identifiers)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        _time(self.generated_at, "generated_at")

    @property
    def summary(self) -> str:
        """Return summary text using concise terminology."""

        return self.text


@dataclass(slots=True, frozen=True)
class TopicDetection:
    """Immutable result of deterministic topic detection."""

    conversation_id: str
    topic: str
    previous_topic: str = ""
    confidence: float = 0.0
    keywords: tuple[str, ...] = ()
    source_message_ids: tuple[str, ...] = ()
    detected_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        _text(self.topic, "topic", maximum=1024, allow_empty=True)
        _text(self.previous_topic, "previous_topic", maximum=1024, allow_empty=True)
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise TypeError("confidence must be numeric")
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "keywords", _identifiers(self.keywords, "keywords"))
        object.__setattr__(
            self,
            "source_message_ids",
            _identifiers(self.source_message_ids, "source_message_ids"),
        )
        _time(self.detected_at, "detected_at")

    @property
    def changed(self) -> bool:
        """Return whether a non-empty detected topic differs from the current one."""

        return bool(self.topic) and self.topic != self.previous_topic


@dataclass(slots=True, frozen=True)
class ConversationWindow:
    """Immutable bounded view over the most recent conversation messages."""

    conversation_id: str
    messages: tuple[ConversationMessage, ...]
    start_offset: int
    end_offset: int
    total_message_count: int
    max_messages: int
    included_roles: tuple[MessageRole, ...] = tuple(MessageRole)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        if isinstance(self.messages, (str, bytes)):
            raise TypeError("messages must contain ConversationMessage values")
        messages = tuple(self.messages)
        if any(not isinstance(message, ConversationMessage) for message in messages):
            raise TypeError("messages must contain ConversationMessage values")
        if any(message.conversation_id != self.conversation_id for message in messages):
            raise ValueError("window messages must belong to the conversation")
        object.__setattr__(self, "messages", messages)
        start = _count(self.start_offset, "start_offset")
        end = _count(self.end_offset, "end_offset")
        total = _count(self.total_message_count, "total_message_count")
        if isinstance(self.max_messages, bool) or not isinstance(
            self.max_messages, int
        ):
            raise TypeError("max_messages must be an integer")
        if not 1 <= self.max_messages <= 10_000:
            raise ValueError("max_messages must be between 1 and 10000")
        if start > end or end > total or end - start != len(messages):
            raise ValueError("window offsets must exactly describe retained messages")
        roles = tuple(self.included_roles)
        if not roles or any(not isinstance(role, MessageRole) for role in roles):
            raise TypeError("included_roles must contain MessageRole values")
        if len(set(roles)) != len(roles):
            raise ValueError("included_roles cannot contain duplicates")
        if any(message.role not in roles for message in messages):
            raise ValueError("window contains a message outside included_roles")
        object.__setattr__(self, "included_roles", roles)
        _time(self.updated_at, "updated_at")

    @property
    def message_count(self) -> int:
        """Return the number of messages in this window."""

        return len(self.messages)

    @property
    def truncated(self) -> bool:
        """Return whether older eligible messages were omitted."""

        return self.start_offset > 0


@dataclass(slots=True, frozen=True)
class SearchMatch:
    """One immutable message match with deterministic relevance facts."""

    message: ConversationMessage
    message_index: int
    score: float
    matched_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.message, ConversationMessage):
            raise TypeError("message must be a ConversationMessage")
        _count(self.message_index, "message_index")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be numeric")
        score = float(self.score)
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        object.__setattr__(self, "score", score)
        object.__setattr__(
            self,
            "matched_terms",
            _identifiers(self.matched_terms, "matched_terms"),
        )


@dataclass(slots=True, frozen=True)
class ConversationSearchResult:
    """Immutable result of an in-memory conversation history search."""

    conversation_id: str
    query: str
    matches: tuple[SearchMatch, ...]
    searched_message_count: int
    total_matches: int
    mode: SearchMode = SearchMode.ANY
    role: MessageRole | None = None
    completed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        _text(self.query, "query", maximum=1000)
        if not isinstance(self.matches, tuple):
            object.__setattr__(self, "matches", tuple(self.matches))
        if any(not isinstance(match, SearchMatch) for match in self.matches):
            raise TypeError("matches must contain SearchMatch values")
        searched = _count(self.searched_message_count, "searched_message_count")
        total = _count(self.total_matches, "total_matches")
        if total < len(self.matches) or searched < total:
            raise ValueError("search counts are inconsistent")
        if not isinstance(self.mode, SearchMode):
            raise TypeError("mode must be a SearchMode")
        if self.role is not None and not isinstance(self.role, MessageRole):
            raise TypeError("role must be a MessageRole or None")
        _time(self.completed_at, "completed_at")

    @property
    def match_count(self) -> int:
        """Return the number of returned matches."""

        return len(self.matches)

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        """Return matching messages in ranked order."""

        return tuple(match.message for match in self.matches)


@dataclass(slots=True, frozen=True)
class ContextReferences:
    """Immutable identifiers referencing external read-only context sources."""

    conversation_id: str
    memories: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        object.__setattr__(self, "memories", _identifiers(self.memories, "memories"))
        object.__setattr__(self, "skills", _identifiers(self.skills, "skills"))
        object.__setattr__(self, "agents", _identifiers(self.agents, "agents"))

    @property
    def total_count(self) -> int:
        """Return the total number of external references."""

        return len(self.memories) + len(self.skills) + len(self.agents)


@dataclass(slots=True, frozen=True)
class ContextStatistics:
    """Immutable aggregate statistics for intelligent conversation context."""

    conversation_id: str
    total_messages: int
    user_messages: int
    assistant_messages: int
    system_messages: int
    cleared_messages: int
    window_messages: int
    window_capacity: int
    total_characters: int
    estimated_tokens: int
    active_topic: str
    previous_topic: str
    summary_available: bool
    summary_message_count: int
    referenced_memory_count: int
    referenced_skill_count: int
    referenced_agent_count: int
    generated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.conversation_id, "conversation_id", maximum=128)
        counts = (
            self.total_messages,
            self.user_messages,
            self.assistant_messages,
            self.system_messages,
            self.cleared_messages,
            self.window_messages,
            self.window_capacity,
            self.total_characters,
            self.estimated_tokens,
            self.summary_message_count,
            self.referenced_memory_count,
            self.referenced_skill_count,
            self.referenced_agent_count,
        )
        for index, count in enumerate(counts):
            _count(count, f"statistic count {index}")
        if (
            self.total_messages
            != self.user_messages + self.assistant_messages + self.system_messages
        ):
            raise ValueError("role counts must equal total_messages")
        if (
            self.window_messages > self.window_capacity
            or self.window_messages > self.total_messages
        ):
            raise ValueError("window message count is inconsistent")
        if not isinstance(self.summary_available, bool):
            raise TypeError("summary_available must be a bool")
        if not self.summary_available and self.summary_message_count:
            raise ValueError("summary_message_count requires an available summary")
        _text(self.active_topic, "active_topic", maximum=1024, allow_empty=True)
        _text(self.previous_topic, "previous_topic", maximum=1024, allow_empty=True)
        _time(self.generated_at, "generated_at")

    @property
    def referenced_total(self) -> int:
        """Return the total number of read-only references."""

        return (
            self.referenced_memory_count
            + self.referenced_skill_count
            + self.referenced_agent_count
        )


__all__ = [
    "ContextReferences",
    "ContextStatistics",
    "ConversationSearchResult",
    "ConversationSummary",
    "ConversationWindow",
    "SearchMatch",
    "SearchMode",
    "TopicDetection",
]
