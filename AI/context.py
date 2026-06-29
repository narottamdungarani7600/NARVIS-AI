"""Conversation context management for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from .conversation import ChatHistoryManager, ConversationTurn, SessionManager
from .intent import IntentType


def _utc_now() -> datetime:
    """Return the current timestamp in UTC."""
    return datetime.now(timezone.utc)


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message through either the Core logger or stdlib logging."""
    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


@dataclass(slots=True)
class ConversationContext:
    """Represents the evolving state of a conversation session."""

    conversation_id: str
    session_id: str | None = None
    last_intent: IntentType | None = None
    last_route: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


class ContextManager(Protocol):
    """Protocol for services that manage conversation context."""

    def get_or_create(self, conversation_id: str | None, session_id: str | None = None) -> ConversationContext:
        """Return an existing context or create a new one."""

    def record_turn(
        self,
        context: ConversationContext,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Append a conversation turn to the provided context."""

    def update_context(
        self,
        context: ConversationContext,
        last_intent: IntentType | None = None,
        last_route: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationContext:
        """Update context values for the current conversation."""

    def get_history(self, conversation_id: str | None = None) -> list[ConversationTurn]:
        """Return history for a conversation."""

    def clear(self, conversation_id: str | None = None) -> None:
        """Clear one context or all contexts."""


class InMemoryContextManager:
    """Simple in-memory context manager for development and testing."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        chat_history_manager: ChatHistoryManager | None = None,
        logger: Any | None = None,
    ) -> None:
        """Initialize the context manager with injected dependencies."""
        self.logger = logger
        self._contexts: dict[str, ConversationContext] = {}
        self._session_manager = session_manager or SessionManager(logger=logger)
        self._chat_history_manager = chat_history_manager or ChatHistoryManager(max_turns=50, logger=logger)

    @property
    def session_manager(self) -> SessionManager:
        """Expose the session manager used by this context manager."""
        return self._session_manager

    @property
    def chat_history_manager(self) -> ChatHistoryManager:
        """Expose the chat history manager used by this context manager."""
        return self._chat_history_manager

    def get_or_create(self, conversation_id: str | None, session_id: str | None = None) -> ConversationContext:
        """Return an existing context or create a new context with generated ids."""
        resolved_conversation_id = conversation_id or self._new_conversation_id()
        existing = self._contexts.get(resolved_conversation_id)
        if existing is not None:
            if session_id and existing.session_id != session_id:
                existing.session_id = session_id
                self._session_manager.create_session(session_id=session_id)
            existing.updated_at = _utc_now()
            return existing

        session = self._session_manager.create_session(session_id=session_id)
        context = ConversationContext(
            conversation_id=resolved_conversation_id,
            session_id=session.session_id,
        )
        self._contexts[resolved_conversation_id] = context
        _emit_log(
            self.logger,
            "info",
            "Created conversation context",
            conversation_id=resolved_conversation_id,
            session_id=session.session_id,
        )
        return context

    def record_turn(
        self,
        context: ConversationContext,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Add a turn to the context and its backing chat history store."""
        turn = self._chat_history_manager.record_turn(
            conversation_id=context.conversation_id,
            role=role,
            content=content,
            metadata=metadata,
        )
        context.history = self._chat_history_manager.get_history(context.conversation_id)
        context.updated_at = _utc_now()
        if context.session_id is not None:
            self._session_manager.touch_session(context.session_id)
        return turn

    def update_context(
        self,
        context: ConversationContext,
        last_intent: IntentType | None = None,
        last_route: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationContext:
        """Update the mutable state associated with a conversation."""
        if last_intent is not None:
            context.last_intent = last_intent
        if last_route is not None:
            context.last_route = last_route
        if metadata:
            context.metadata.update(metadata)
        context.updated_at = _utc_now()
        _emit_log(
            self.logger,
            "debug",
            "Updated conversation context",
            conversation_id=context.conversation_id,
            session_id=context.session_id,
            last_intent=context.last_intent.value if context.last_intent else None,
            last_route=context.last_route,
        )
        return context

    def get_history(self, conversation_id: str | None = None) -> list[ConversationTurn]:
        """Return the history for a given context or the most recent context."""
        if conversation_id is None:
            if not self._contexts:
                return []
            conversation_id = next(reversed(self._contexts))
        return self._chat_history_manager.get_history(conversation_id)

    def clear(self, conversation_id: str | None = None) -> None:
        """Clear one context or all contexts and associated history."""
        if conversation_id is None:
            session_ids = {context.session_id for context in self._contexts.values() if context.session_id}
            self._contexts.clear()
            self._chat_history_manager.clear()
            for session_id in session_ids:
                self._session_manager.delete_session(session_id)
            _emit_log(self.logger, "info", "Cleared all conversation contexts")
            return

        context = self._contexts.pop(conversation_id, None)
        self._chat_history_manager.clear(conversation_id)
        if context and context.session_id and not self._is_session_in_use(context.session_id):
            self._session_manager.delete_session(context.session_id)
        _emit_log(self.logger, "info", "Cleared conversation context", conversation_id=conversation_id)

    def _is_session_in_use(self, session_id: str) -> bool:
        """Return whether a session id is still referenced by another context."""
        return any(context.session_id == session_id for context in self._contexts.values())

    def _new_conversation_id(self) -> str:
        """Create a stable unique conversation identifier."""
        return f"conv-{uuid4().hex}"
