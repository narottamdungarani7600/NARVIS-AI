"""Composition service for intelligent, read-only conversation context."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Protocol

from Conversation.core.models import ConversationSession, MessageRole, utc_now

from .exceptions import ReferenceNotFoundError, ReferenceValidationError
from .models import (
    ContextReferences,
    ContextStatistics,
    ConversationSearchResult,
    ConversationSummary,
    ConversationWindow,
    SearchMode,
    TopicDetection,
)
from .search import ConversationSearch
from .summary import ExtractiveConversationSummarizer, SummaryGenerator
from .topic import KeywordTopicDetector, TopicDetector
from .window import ConversationWindowManager


class MemoryReferenceReader(Protocol):
    """Read-only exact lookup contract compatible with Memory repositories."""

    def load(self, key: str) -> object | None:
        """Return one memory value without modifying memory."""


class NamedReferenceReader(Protocol):
    """Read-only lookup contract compatible with skill registries."""

    def find(self, name: str) -> object | None:
        """Return one named value without modifying its source."""


class ConversationContextManager:
    """Compose pure context services and optional read-only reference sources."""

    def __init__(
        self,
        summarizer: SummaryGenerator | None = None,
        topic_detector: TopicDetector | None = None,
        window_manager: ConversationWindowManager | None = None,
        search_service: ConversationSearch | None = None,
        *,
        memory_reader: MemoryReferenceReader | object | None = None,
        skill_reader: NamedReferenceReader | object | None = None,
        agent_reader: NamedReferenceReader | object | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._summarizer = summarizer or ExtractiveConversationSummarizer(clock=clock)
        self._topic_detector = topic_detector or KeywordTopicDetector(clock=clock)
        self._window_manager = window_manager or ConversationWindowManager(clock=clock)
        self._search = search_service or ConversationSearch(clock=clock)
        self._memory_reader = self._memory_source(memory_reader)
        self._skill_reader = self._named_source(skill_reader, "skill_reader")
        self._agent_reader = self._named_source(agent_reader, "agent_reader")

    @property
    def window_manager(self) -> ConversationWindowManager:
        """Return the injected immutable window service."""

        return self._window_manager

    def summarize(
        self,
        session: ConversationSession,
        *,
        max_messages: int | None = None,
    ) -> ConversationSummary:
        """Generate an immutable summary from retained history."""

        current = self._session(session)
        return self._summarizer.generate(
            current.session_id,
            current.messages,
            active_topic=current.context.active_topic,
            max_messages=max_messages,
        )

    generate_summary = summarize

    def detect_topic(self, session: ConversationSession) -> TopicDetection:
        """Detect a topic without mutating the supplied session snapshot."""

        current = self._session(session)
        return self._topic_detector.detect(
            current.session_id,
            current.messages,
            current_topic=current.context.active_topic,
        )

    def window(
        self,
        session: ConversationSession,
        *,
        max_messages: int | None = None,
        roles: Iterable[MessageRole] | None = None,
    ) -> ConversationWindow:
        """Build a recent immutable window over retained history."""

        current = self._session(session)
        return self._window_manager.build(
            current.session_id,
            current.messages,
            max_messages=max_messages,
            roles=roles,
        )

    conversation_window = window

    def search(
        self,
        session: ConversationSession,
        query: str,
        *,
        role: MessageRole | None = None,
        mode: SearchMode = SearchMode.ANY,
        case_sensitive: bool = False,
        limit: int = 20,
    ) -> ConversationSearchResult:
        """Search retained messages with no external index or storage."""

        current = self._session(session)
        return self._search.search(
            current.session_id,
            current.messages,
            query,
            role=role,
            mode=mode,
            case_sensitive=case_sensitive,
            limit=limit,
        )

    search_messages = search

    def references(self, session: ConversationSession) -> ContextReferences:
        """Return immutable external identifiers without retrieving mutable values."""

        current = self._session(session)
        return ContextReferences(
            conversation_id=current.session_id,
            memories=current.context.referenced_memories,
            skills=current.context.referenced_skills,
            agents=current.context.referenced_agents,
        )

    def validate_references(
        self,
        conversation_id: str,
        *,
        memories: Iterable[str] = (),
        skills: Iterable[str] = (),
        agents: Iterable[str] = (),
    ) -> ContextReferences:
        """Resolve identifiers through read methods only and return a snapshot."""

        try:
            references = ContextReferences(
                conversation_id=conversation_id,
                memories=tuple(memories),
                skills=tuple(skills),
                agents=tuple(agents),
            )
        except (TypeError, ValueError) as error:
            raise ReferenceValidationError(str(error)) from error
        self._require_memories(references.memories)
        self._require_named(self._skill_reader, references.skills, "skill")
        self._require_named(self._agent_reader, references.agents, "agent")
        return references

    def statistics(self, session: ConversationSession) -> ContextStatistics:
        """Generate immutable message, window, summary, topic, and reference facts."""

        current = self._session(session)
        window = self.window(current)
        messages = current.messages
        summary_available = bool(current.context.summary)
        raw_summary_count = current.context.metadata.get("summary_message_count", 0)
        summary_count = (
            raw_summary_count
            if isinstance(raw_summary_count, int)
            and not isinstance(raw_summary_count, bool)
            and raw_summary_count >= 0
            else 0
        )
        if not summary_available:
            summary_count = 0
        characters = sum(len(message.content) for message in messages)
        return ContextStatistics(
            conversation_id=current.session_id,
            total_messages=len(messages),
            user_messages=sum(message.role is MessageRole.USER for message in messages),
            assistant_messages=sum(
                message.role is MessageRole.ASSISTANT for message in messages
            ),
            system_messages=sum(
                message.role is MessageRole.SYSTEM for message in messages
            ),
            cleared_messages=current.history.cleared_messages,
            window_messages=window.message_count,
            window_capacity=window.max_messages,
            total_characters=characters,
            estimated_tokens=(characters + 3) // 4,
            active_topic=current.context.active_topic,
            previous_topic=current.context.previous_topic,
            summary_available=summary_available,
            summary_message_count=summary_count,
            referenced_memory_count=len(current.context.referenced_memories),
            referenced_skill_count=len(current.context.referenced_skills),
            referenced_agent_count=len(current.context.referenced_agents),
            generated_at=window.updated_at,
        )

    context_statistics = statistics

    @staticmethod
    def _session(value: object) -> ConversationSession:
        if not isinstance(value, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        return value

    @staticmethod
    def _memory_source(value: object | None) -> object | None:
        if value is None:
            return None
        if not callable(getattr(value, "load", None)) and not callable(
            getattr(value, "search", None)
        ):
            raise ReferenceValidationError(
                "memory_reader must provide a read-only load or search method"
            )
        return value

    @staticmethod
    def _named_source(value: object | None, name: str) -> object | None:
        if value is not None and not callable(getattr(value, "find", None)):
            raise ReferenceValidationError(
                f"{name} must provide a read-only find method"
            )
        return value

    def _require_memories(self, identifiers: tuple[str, ...]) -> None:
        source = self._memory_reader
        if source is None:
            return
        loader = getattr(source, "load", None)
        searcher = getattr(source, "search", None)
        for identifier in identifiers:
            if callable(loader):
                found = loader(identifier)
            elif callable(searcher):
                try:
                    values = tuple(searcher(identifier, limit=10))
                except TypeError:
                    values = tuple(searcher(identifier))
                found = next(
                    (
                        item
                        for item in values
                        if getattr(item, "key", identifier) == identifier
                    ),
                    None,
                )
            else:  # pragma: no cover - constructor validation is authoritative
                found = None
            if found is None:
                raise ReferenceNotFoundError(
                    f"memory reference '{identifier}' was not found"
                )

    @staticmethod
    def _require_named(
        source: object | None,
        identifiers: tuple[str, ...],
        kind: str,
    ) -> None:
        if source is None:
            return
        finder = getattr(source, "find")
        for identifier in identifiers:
            if finder(identifier) is None:
                raise ReferenceNotFoundError(
                    f"{kind} reference '{identifier}' was not found"
                )


IntelligentContextManager = ConversationContextManager


__all__ = [
    "ConversationContextManager",
    "IntelligentContextManager",
    "MemoryReferenceReader",
    "NamedReferenceReader",
]
