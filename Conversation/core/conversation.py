"""UI-independent orchestration for immutable conversation sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Any

from Core.logger import LogLevel, Logger, NullLogger

from Conversation.context.context_manager import (
    ConversationContextManager,
    MemoryReferenceReader,
    NamedReferenceReader,
)
from Conversation.context.models import (
    ContextReferences,
    ContextStatistics,
    ConversationSearchResult,
    ConversationSummary,
    ConversationWindow,
    SearchMode,
    TopicDetection,
)
from Conversation.lifecycle.manager import ConversationLifecycleManager
from Conversation.lifecycle.models import (
    ArchiveMetadata,
    CleanupReport,
    ContextCleanupPolicy,
    ConversationExport,
    ConversationHealth,
    ExportFormat,
    RetentionPolicy,
    SessionInfo,
)

from .context import ConversationContextTracker
from .events import (
    CONVERSATION_CLOSED_EVENT,
    CONVERSATION_CREATED_EVENT,
    CONVERSATION_RESUMED_EVENT,
    CONVERSATION_SEARCH_COMPLETED_EVENT,
    CONVERSATION_SUMMARY_GENERATED_EVENT,
    CONVERSATION_TOPIC_CHANGED_EVENT,
    CONVERSATION_UPDATED_EVENT,
    CONVERSATION_WINDOW_UPDATED_EVENT,
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
        context_manager: ConversationContextManager | None = None,
        memory_reader: MemoryReferenceReader | object | None = None,
        skill_reader: NamedReferenceReader | object | None = None,
        agent_reader: NamedReferenceReader | object | None = None,
        lifecycle_manager: ConversationLifecycleManager | None = None,
    ) -> None:
        """Initialize replaceable dependencies without external side effects."""

        self._clock = clock
        self._id_factory = id_factory
        self._store = session_store or InMemoryConversationSessionStore()
        self._history = history_manager or ConversationHistoryManager(clock=clock)
        self._context = context_tracker or ConversationContextTracker(clock=clock)
        self._logger = logger or NullLogger("narvis.conversation")
        self._events = events or ConversationEvents(event_bus, logger=self._logger)
        if context_manager is not None and any(
            reader is not None for reader in (memory_reader, skill_reader, agent_reader)
        ):
            raise ConversationValidationError(
                "inject readers through context_manager or ConversationManager, not both"
            )
        self._intelligent_context = context_manager or ConversationContextManager(
            memory_reader=memory_reader,
            skill_reader=skill_reader,
            agent_reader=agent_reader,
            clock=clock,
        )
        self._lock = RLock()
        self._lifecycle = lifecycle_manager or ConversationLifecycleManager(
            self._store,
            event_bus=event_bus,
            logger=self._logger,
            clock=clock,
        )

    def create_conversation(
        self,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        context_metadata: Mapping[str, Any] | None = None,
        system_message: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
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
                expires_at=expires_at,
            )
            self._store.add(session)
            self._lifecycle.register(session)
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
            if not current.active:
                raise ConversationClosedError(
                    f"conversation '{session_id}' cannot be closed from "
                    f"status '{current.status.value}'"
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
            self._lifecycle.synchronize(session)
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
            if not current.closed:
                raise ConversationClosedError(
                    f"conversation '{session_id}' must be restored or recreated"
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
            self._lifecycle.synchronize(session)
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
        referenced_memories: Iterable[str] | None = None,
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
                referenced_memories=referenced_memories,
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
                referenced_memory_count=len(context.referenced_memories),
                referenced_skill_count=len(context.referenced_skills),
                referenced_agent_count=len(context.referenced_agents),
            )
            self._events.publish(
                CONVERSATION_UPDATED_EVENT,
                session,
                update_type="context_updated",
            )
            if context.active_topic != current.context.active_topic:
                self._events.publish(
                    CONVERSATION_TOPIC_CHANGED_EVENT,
                    session,
                    previous_topic=current.context.active_topic,
                    active_topic=context.active_topic,
                    confidence=None,
                )
            return session

    def generate_summary(
        self,
        session_id: str,
        *,
        max_messages: int | None = None,
    ) -> ConversationSummary:
        """Generate and retain a bounded summary for an active conversation."""

        with self._lock:
            current = self._active_session(session_id)
            summary = self._intelligent_context.summarize(
                current,
                max_messages=max_messages,
            )
            timestamp = max(
                current.updated_at,
                summary.generated_at,
                self._timestamp(None, "updated_at"),
            )
            context = self._context.update(
                current.context,
                summary=summary.text,
                metadata={
                    "summary_id": summary.summary_id,
                    "summary_message_count": summary.message_count,
                    "summary_source_count": len(summary.source_message_ids),
                },
                updated_at=timestamp,
            )
            session = replace(current, context=context, updated_at=timestamp)
            self._store.replace(session)
            self._log(
                LogLevel.INFO,
                "Conversation summary generated",
                conversation_id=session_id,
                summary_id=summary.summary_id,
                message_count=summary.message_count,
                source_count=len(summary.source_message_ids),
            )
            self._events.publish(
                CONVERSATION_SUMMARY_GENERATED_EVENT,
                session,
                summary_id=summary.summary_id,
                source_count=len(summary.source_message_ids),
                summary_length=len(summary.text),
            )
            return summary

    def detect_topic(
        self,
        session_id: str,
        *,
        switch: bool = True,
    ) -> TopicDetection:
        """Detect a topic and optionally switch the active conversation topic."""

        if not isinstance(switch, bool):
            raise ConversationValidationError("switch must be a bool")
        with self._lock:
            current = (
                self._active_session(session_id)
                if switch
                else self._store.get(session_id)
            )
            detection = self._intelligent_context.detect_topic(current)
            if switch and detection.changed:
                timestamp = max(
                    current.updated_at,
                    detection.detected_at,
                    self._timestamp(None, "updated_at"),
                )
                context = self._context.update(
                    current.context,
                    active_topic=detection.topic,
                    updated_at=timestamp,
                )
                session = replace(current, context=context, updated_at=timestamp)
                self._store.replace(session)
                self._events.publish(
                    CONVERSATION_TOPIC_CHANGED_EVENT,
                    session,
                    previous_topic=detection.previous_topic,
                    active_topic=detection.topic,
                    confidence=detection.confidence,
                )
            self._log(
                LogLevel.INFO,
                "Conversation topic analyzed",
                conversation_id=session_id,
                topic=detection.topic,
                confidence=detection.confidence,
                changed=detection.changed and switch,
            )
            return detection

    def active_topic(self, session_id: str, *, detect: bool = False) -> str:
        """Return the stored active topic, optionally detecting and switching it."""

        if not isinstance(detect, bool):
            raise ConversationValidationError("detect must be a bool")
        if detect:
            return self.detect_topic(session_id).topic
        return self._store.get(session_id).context.active_topic

    def conversation_window(
        self,
        session_id: str,
        *,
        max_messages: int | None = None,
        roles: Iterable[MessageRole] | None = None,
    ) -> ConversationWindow:
        """Return and announce a bounded read-only view of recent messages."""

        session = self._store.get(session_id)
        window = self._intelligent_context.window(
            session,
            max_messages=max_messages,
            roles=roles,
        )
        self._log(
            LogLevel.INFO,
            "Conversation window updated",
            conversation_id=session_id,
            message_count=window.message_count,
            max_messages=window.max_messages,
            truncated=window.truncated,
        )
        self._events.publish(
            CONVERSATION_WINDOW_UPDATED_EVENT,
            session,
            window_message_count=window.message_count,
            max_messages=window.max_messages,
            truncated=window.truncated,
        )
        return window

    def search_messages(
        self,
        session_id: str,
        query: str,
        *,
        role: MessageRole | None = None,
        mode: SearchMode = SearchMode.ANY,
        case_sensitive: bool = False,
        limit: int = 20,
    ) -> ConversationSearchResult:
        """Search retained messages and publish only non-sensitive search facts."""

        session = self._store.get(session_id)
        result = self._intelligent_context.search(
            session,
            query,
            role=role,
            mode=mode,
            case_sensitive=case_sensitive,
            limit=limit,
        )
        self._log(
            LogLevel.INFO,
            "Conversation search completed",
            conversation_id=session_id,
            searched_message_count=result.searched_message_count,
            total_matches=result.total_matches,
            returned_matches=result.match_count,
        )
        self._events.publish(
            CONVERSATION_SEARCH_COMPLETED_EVENT,
            session,
            searched_message_count=result.searched_message_count,
            total_matches=result.total_matches,
            returned_matches=result.match_count,
            query_length=len(result.query),
        )
        return result

    def context_statistics(self, session_id: str) -> ContextStatistics:
        """Return immutable intelligent-context statistics."""

        return self._intelligent_context.statistics(self._store.get(session_id))

    def context_references(self, session_id: str) -> ContextReferences:
        """Return immutable memory, skill, and agent reference identifiers."""

        return self._intelligent_context.references(self._store.get(session_id))

    def reference_context(
        self,
        session_id: str,
        *,
        memories: Iterable[str] | None = None,
        skills: Iterable[str] | None = None,
        agents: Iterable[str] | None = None,
        replace_references: bool = False,
        updated_at: datetime | None = None,
    ) -> ConversationSession:
        """Validate external identifiers through read methods and retain only IDs."""

        if not isinstance(replace_references, bool):
            raise ConversationValidationError("replace_references must be a bool")
        with self._lock:
            self._active_session(session_id)
            validated = self._intelligent_context.validate_references(
                session_id,
                memories=() if memories is None else memories,
                skills=() if skills is None else skills,
                agents=() if agents is None else agents,
            )
            return self.update_context(
                session_id,
                referenced_memories=(None if memories is None else validated.memories),
                referenced_skills=None if skills is None else validated.skills,
                referenced_agents=None if agents is None else validated.agents,
                replace_references=replace_references,
                updated_at=updated_at,
            )

    add_references = reference_context

    def reference_memories(
        self,
        session_id: str,
        memory_ids: Iterable[str],
        *,
        replace_references: bool = False,
    ) -> ConversationSession:
        """Retain validated read-only memory identifiers."""

        return self.reference_context(
            session_id,
            memories=memory_ids,
            replace_references=replace_references,
        )

    def reference_skills(
        self,
        session_id: str,
        skill_ids: Iterable[str],
        *,
        replace_references: bool = False,
    ) -> ConversationSession:
        """Retain validated read-only skill identifiers."""

        return self.reference_context(
            session_id,
            skills=skill_ids,
            replace_references=replace_references,
        )

    def reference_agents(
        self,
        session_id: str,
        agent_ids: Iterable[str],
        *,
        replace_references: bool = False,
    ) -> ConversationSession:
        """Retain validated read-only agent identifiers."""

        return self.reference_context(
            session_id,
            agents=agent_ids,
            replace_references=replace_references,
        )

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

    def archive_conversation(
        self,
        session_id: str,
        *,
        reason: str = "",
        tags: Iterable[str] = (),
        retention_until: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        archived_at: datetime | None = None,
    ) -> ConversationSession:
        """Archive an active or closed conversation entirely in memory."""

        return self._lifecycle.archive_conversation(
            session_id,
            reason=reason,
            tags=tags,
            retention_until=retention_until,
            metadata=metadata,
            archived_at=archived_at,
        )

    def restore_conversation(
        self,
        session_id: str,
        *,
        restored_at: datetime | None = None,
    ) -> ConversationSession:
        """Restore an archived conversation to its pre-archive status."""

        return self._lifecycle.restore_conversation(
            session_id,
            restored_at=restored_at,
        )

    def switch_session(
        self,
        session_id: str,
        *,
        switched_at: datetime | None = None,
    ) -> ConversationSession:
        """Select an active conversation session and return its snapshot."""

        self._lifecycle.switch_session(
            session_id,
            switched_at=switched_at,
        )
        return self._store.get(session_id)

    def current_session(self) -> ConversationSession:
        """Return the currently selected active conversation session."""

        return self._lifecycle.current_session()

    @property
    def current_session_id(self) -> str | None:
        """Return the selected session identifier or None."""

        return self._lifecycle.current_session_id

    @property
    def lifecycle_manager(self) -> ConversationLifecycleManager:
        """Return the injected lifecycle coordinator."""

        return self._lifecycle

    def list_sessions(
        self,
        *,
        status: ConversationStatus | None = None,
        include_archived: bool = True,
        include_expired: bool = True,
    ) -> tuple[SessionInfo, ...]:
        """Return immutable lifecycle views for every retained session."""

        return self._lifecycle.list_sessions(
            status=status,
            include_archived=include_archived,
            include_expired=include_expired,
        )

    def cleanup_sessions(
        self,
        policy: RetentionPolicy | None = None,
        *,
        now: datetime | None = None,
    ) -> CleanupReport:
        """Apply retention, expiration, and in-memory session cleanup."""

        return self._lifecycle.cleanup_sessions(policy, now=now)

    def cleanup_conversation_context(
        self,
        session_id: str,
        policy: ContextCleanupPolicy | None = None,
        *,
        cleaned_at: datetime | None = None,
    ) -> ConversationSession:
        """Remove selected transient context without deleting the session."""

        return self._lifecycle.cleanup_context(
            session_id,
            policy,
            cleaned_at=cleaned_at,
        )

    def set_session_expiration(
        self,
        session_id: str,
        expires_at: datetime | None,
    ) -> ConversationSession:
        """Set or clear a session expiration timestamp."""

        return self._lifecycle.set_expiration(session_id, expires_at)

    def expire_conversation(
        self,
        session_id: str,
        *,
        expired_at: datetime | None = None,
    ) -> ConversationSession:
        """Mark one conversation expired without removing it."""

        return self._lifecycle.expire_conversation(
            session_id,
            expired_at=expired_at,
        )

    def archive_metadata(self, session_id: str) -> ArchiveMetadata | None:
        """Return the latest archive metadata for a conversation."""

        return self._lifecycle.archive_metadata(session_id)

    def archive_history(self, session_id: str) -> tuple[ArchiveMetadata, ...]:
        """Return immutable archive history for one conversation."""

        return self._lifecycle.archive_history(session_id)

    def prepare_export(
        self,
        session_id: str,
        *,
        format: ExportFormat = ExportFormat.JSON,
        include_metadata: bool = True,
    ) -> ConversationExport:
        """Prepare export-ready content without writing any file."""

        return self._lifecycle.prepare_export(
            session_id,
            format=format,
            include_metadata=include_metadata,
        )

    export_conversation = prepare_export

    def conversation_health(
        self,
        policy: RetentionPolicy | None = None,
        *,
        now: datetime | None = None,
    ) -> ConversationHealth:
        """Return aggregate conversation lifecycle health statistics."""

        return self._lifecycle.conversation_health(policy, now=now)

    def _active_session(self, session_id: str) -> ConversationSession:
        """Return a session only when it accepts updates."""

        session = self._store.get(session_id)
        if not session.active:
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
