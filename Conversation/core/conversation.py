"""UI-independent orchestration for immutable conversation sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Any

from Core.logger import LogLevel, Logger, NullLogger

from .context import ConversationContextTracker
from .events import (
    CONVERSATION_CLOSED_EVENT,
    CONVERSATION_CREATED_EVENT,
    CONVERSATION_RESUMED_EVENT,
    CONVERSATION_UPDATED_EVENT,
    ConversationEvents,
    EventPublisher,
)
from .exceptions import (
    ConversationAlreadyActiveError,
    ConversationAlreadyClosedError,
    ConversationClosedError,
    ConversationValidationError,
    MessageValidationError,
)
from .history import ConversationHistoryManager
from .models import (
    AssistantMessage,
    ConversationMessage,
    ConversationSession,
    ConversationStatistics,
    ConversationStatus,
    MessageRole,
    SystemMessage,
    UserMessage,
    immutable_mapping,
    new_id,
    utc_now,
)
from .session import (
    ConversationSessionStore,
    InMemoryConversationSessionStore,
)


class ConversationManager:
    """Coordinate conversation lifecycle, history, context, events, and logs."""

    def __init__(
        self,
        session_store: ConversationSessionStore | None = None,
        history_manager: ConversationHistoryManager | None = None,
        context_tracker: ConversationContextTracker | None = None,
        events: ConversationEvents | None = None,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        """Initialize replaceable dependencies without external side effects."""

        self._clock = clock
        self._id_factory = id_factory
        self._store = session_store or InMemoryConversationSessionStore()
        self._history = history_manager or ConversationHistoryManager(clock=clock)
        self._context = context_tracker or ConversationContextTracker(clock=clock)
        self._logger = logger or NullLogger("narvis.conversation")
        self._events = events or ConversationEvents(event_bus, logger=self._logger)
        self._lock = RLock()

    def create_conversation(
        self,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        context_metadata: Mapping[str, Any] | None = None,
        system_message: str | None = None,
        created_at: datetime | None = None,
    ) -> ConversationSession:
        """Create, retain, log, and announce a new active conversation."""

        with self._lock:
            timestamp = self._timestamp(created_at, "created_at")
            identifier = session_id if session_id is not None else self._id_factory()
            history = self._history.create(identifier, created_at=timestamp)
            if system_message is not None:
                message = SystemMessage(
                    conversation_id=identifier,
                    content=system_message,
                    timestamp=timestamp,
                )
                history = self._history.append(history, message)
            context = self._context.create(
                identifier,
                metadata=context_metadata,
                created_at=timestamp,
            )
            session = ConversationSession(
                session_id=identifier,
                status=ConversationStatus.ACTIVE,
                history=history,
                context=context,
                metadata={} if metadata is None else metadata,
                created_at=timestamp,
                updated_at=max(timestamp, history.updated_at),
            )
            self._store.add(session)
            self._log(
                LogLevel.INFO,
                "Conversation created",
                conversation_id=identifier,
                status=session.status.value,
            )
            self._events.publish(CONVERSATION_CREATED_EVENT, session)
            return session

    create = create_conversation

    def get_conversation(self, session_id: str) -> ConversationSession:
        """Return the latest immutable snapshot for a conversation."""

        return self._store.get(session_id)

    get = get_conversation

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        """Return all retained conversations in store-defined order."""

        return self._store.list()

    list = list_conversations

    def close_conversation(
        self,
        session_id: str,
        *,
        closed_at: datetime | None = None,
    ) -> ConversationSession:
        """Close an active conversation without removing its history."""

        with self._lock:
            current = self._store.get(session_id)
            if current.closed:
                raise ConversationAlreadyClosedError(
                    f"conversation '{session_id}' is already closed"
                )
            timestamp = self._lifecycle_timestamp(
                closed_at,
                "closed_at",
                current,
            )
            session = replace(
                current,
                status=ConversationStatus.CLOSED,
                closed_at=timestamp,
                updated_at=timestamp,
            )
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation closed",
                conversation_id=session_id,
                status=session.status.value,
            )
            self._events.publish(CONVERSATION_CLOSED_EVENT, session)
            return session

    close = close_conversation

    def resume_conversation(
        self,
        session_id: str,
        *,
        resumed_at: datetime | None = None,
    ) -> ConversationSession:
        """Resume a closed conversation while retaining lifecycle history."""

        with self._lock:
            current = self._store.get(session_id)
            if current.active:
                raise ConversationAlreadyActiveError(
                    f"conversation '{session_id}' is already active"
                )
            timestamp = self._lifecycle_timestamp(
                resumed_at,
                "resumed_at",
                current,
            )
            session = replace(
                current,
                status=ConversationStatus.ACTIVE,
                resumed_at=timestamp,
                resume_count=current.resume_count + 1,
                updated_at=timestamp,
            )
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation resumed",
                conversation_id=session_id,
                status=session.status.value,
                resume_count=session.resume_count,
            )
            self._events.publish(CONVERSATION_RESUMED_EVENT, session)
            return session

    resume = resume_conversation

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        message_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> ConversationSession:
        """Append one typed message and publish a safe update event."""

        if not isinstance(role, MessageRole):
            raise MessageValidationError("role must be a MessageRole")
        with self._lock:
            current = self._active_session(session_id)
            message_type = {
                MessageRole.USER: UserMessage,
                MessageRole.ASSISTANT: AssistantMessage,
                MessageRole.SYSTEM: SystemMessage,
            }[role]
            values: dict[str, Any] = {
                "conversation_id": session_id,
                "content": content,
                "metadata": {} if metadata is None else metadata,
                "timestamp": self._lifecycle_timestamp(
                    timestamp,
                    "timestamp",
                    current,
                ),
            }
            if message_id is not None:
                values["message_id"] = message_id
            try:
                message = message_type(**values)
                history = self._history.append(current.history, message)
            except (TypeError, ValueError) as error:
                if isinstance(error, MessageValidationError):
                    raise
                raise MessageValidationError(str(error)) from error
            session = replace(
                current,
                history=history,
                updated_at=max(current.updated_at, history.updated_at),
            )
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation message added",
                conversation_id=session_id,
                message_id=message.message_id,
                role=message.role.value,
                message_count=history.count,
            )
            self._events.publish(
                CONVERSATION_UPDATED_EVENT,
                session,
                update_type="message_added",
                message_id=message.message_id,
                role=message.role.value,
            )
            return session

    def add_user_message(
        self,
        session_id: str,
        content: str,
        **kwargs: Any,
    ) -> ConversationSession:
        """Append a user message."""

        return self.add_message(session_id, MessageRole.USER, content, **kwargs)

    def add_assistant_message(
        self,
        session_id: str,
        content: str,
        **kwargs: Any,
    ) -> ConversationSession:
        """Append an assistant message."""

        return self.add_message(session_id, MessageRole.ASSISTANT, content, **kwargs)

    def add_system_message(
        self,
        session_id: str,
        content: str,
        **kwargs: Any,
    ) -> ConversationSession:
        """Append a system message."""

        return self.add_message(session_id, MessageRole.SYSTEM, content, **kwargs)

    def get_history(
        self,
        session_id: str,
        *,
        role: MessageRole | None = None,
    ) -> tuple[ConversationMessage, ...]:
        """Return retained messages, optionally filtered by typed role."""

        session = self._store.get(session_id)
        return self._history.messages(session.history, role=role)

    def clear_history(
        self,
        session_id: str,
        *,
        cleared_at: datetime | None = None,
    ) -> ConversationSession:
        """Clear retained messages while preserving a cumulative count."""

        with self._lock:
            current = self._active_session(session_id)
            history = self._history.clear(
                current.history,
                cleared_at=self._lifecycle_timestamp(
                    cleared_at,
                    "cleared_at",
                    current,
                ),
            )
            session = replace(current, history=history, updated_at=history.updated_at)
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation history cleared",
                conversation_id=session_id,
                cleared_messages=history.cleared_messages,
            )
            self._events.publish(
                CONVERSATION_UPDATED_EVENT,
                session,
                update_type="history_cleared",
            )
            return session

    def update_context(
        self,
        session_id: str,
        *,
        active_topic: str | None = None,
        referenced_skills: Iterable[str] | None = None,
        referenced_agents: Iterable[str] | None = None,
        summary: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        replace_references: bool = False,
        updated_at: datetime | None = None,
    ) -> ConversationSession:
        """Update topic, references, summary, and context metadata."""

        with self._lock:
            current = self._active_session(session_id)
            context = self._context.update(
                current.context,
                active_topic=active_topic,
                referenced_skills=referenced_skills,
                referenced_agents=referenced_agents,
                summary=summary,
                metadata=metadata,
                replace_references=replace_references,
                updated_at=self._lifecycle_timestamp(
                    updated_at,
                    "updated_at",
                    current,
                ),
            )
            session = replace(current, context=context, updated_at=context.updated_at)
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation context updated",
                conversation_id=session_id,
                active_topic=context.active_topic,
                referenced_skill_count=len(context.referenced_skills),
                referenced_agent_count=len(context.referenced_agents),
            )
            self._events.publish(
                CONVERSATION_UPDATED_EVENT,
                session,
                update_type="context_updated",
            )
            return session

    def clear_context(
        self,
        session_id: str,
        *,
        cleared_at: datetime | None = None,
    ) -> ConversationSession:
        """Clear tracked context for an active conversation."""

        with self._lock:
            current = self._active_session(session_id)
            context = self._context.clear(
                current.context,
                cleared_at=self._lifecycle_timestamp(
                    cleared_at,
                    "cleared_at",
                    current,
                ),
            )
            session = replace(current, context=context, updated_at=context.updated_at)
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation context cleared",
                conversation_id=session_id,
            )
            self._events.publish(
                CONVERSATION_UPDATED_EVENT,
                session,
                update_type="context_cleared",
            )
            return session

    def update_metadata(
        self,
        session_id: str,
        metadata: Mapping[str, Any],
        *,
        updated_at: datetime | None = None,
    ) -> ConversationSession:
        """Merge immutable, non-message conversation metadata."""

        with self._lock:
            current = self._active_session(session_id)
            try:
                additions = immutable_mapping(metadata)
            except (TypeError, ValueError) as error:
                raise ConversationValidationError(str(error)) from error
            next_metadata = dict(current.metadata)
            next_metadata.update(additions)
            timestamp = self._lifecycle_timestamp(
                updated_at,
                "updated_at",
                current,
            )
            session = replace(
                current,
                metadata=next_metadata,
                updated_at=timestamp,
            )
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation metadata updated",
                conversation_id=session_id,
            )
            self._events.publish(
                CONVERSATION_UPDATED_EVENT,
                session,
                update_type="metadata_updated",
            )
            return session

    def conversation_statistics(self, session_id: str) -> ConversationStatistics:
        """Generate immutable retained-history and lifecycle statistics."""

        session = self._store.get(session_id)
        messages = session.history.messages
        return ConversationStatistics(
            conversation_id=session_id,
            status=session.status,
            total_messages=len(messages),
            user_messages=sum(message.role is MessageRole.USER for message in messages),
            assistant_messages=sum(
                message.role is MessageRole.ASSISTANT for message in messages
            ),
            system_messages=sum(
                message.role is MessageRole.SYSTEM for message in messages
            ),
            cleared_messages=session.history.cleared_messages,
            resume_count=session.resume_count,
            active_topic=session.context.active_topic,
            referenced_skill_count=len(session.context.referenced_skills),
            referenced_agent_count=len(session.context.referenced_agents),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    statistics = conversation_statistics
    stats = conversation_statistics

    def _active_session(self, session_id: str) -> ConversationSession:
        """Return a session only when it accepts updates."""

        session = self._store.get(session_id)
        if session.closed:
            raise ConversationClosedError(f"conversation '{session_id}' is closed")
        return session

    def _timestamp(
        self,
        value: datetime | None,
        name: str,
    ) -> datetime:
        """Resolve and validate an aware injected or explicit timestamp."""

        timestamp = self._clock() if value is None else value
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ConversationValidationError(
                f"{name} must be a timezone-aware datetime"
            )
        return timestamp

    def _lifecycle_timestamp(
        self,
        value: datetime | None,
        name: str,
        session: ConversationSession,
    ) -> datetime:
        """Require lifecycle timestamps to be monotonically increasing."""

        timestamp = self._timestamp(value, name)
        if timestamp < session.updated_at:
            raise ConversationValidationError(
                f"{name} cannot precede the latest conversation update"
            )
        return timestamp

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Prevent diagnostic observer failures from changing state."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


ConversationEngine = ConversationManager


__all__ = ["ConversationEngine", "ConversationManager"]
