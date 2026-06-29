"""Conversation context management for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .conversation import ChatHistoryManager, ConversationManager, ConversationTurn, SessionManager
from .intent import IntentType


@dataclass(slots=True)
class ConversationContext:
    """Represents the evolving state of a conversation session."""

    conversation_id: str
    session_id: str | None = None
    last_intent: IntentType | None = None
    last_route: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[ConversationTurn] = field(default_factory=list)


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


class InMemoryContextManager:
    """Simple in-memory context manager for development and testing."""

    def __init__(self, session_manager: SessionManager | None = None, chat_history_manager: ChatHistoryManager | None = None) -> None:
        self._contexts: dict[str, ConversationContext] = {}
        self._conversation_manager = ConversationManager()
        self._session_manager = session_manager or SessionManager()
        self._chat_history_manager = chat_history_manager or ChatHistoryManager(max_turns=50)

    def get_or_create(self, conversation_id: str | None, session_id: str | None = None) -> ConversationContext:
        """Return an existing context or create a new context with a generated id."""
        cid = conversation_id or self._new_conversation_id()
        if cid not in self._contexts:
            context = ConversationContext(conversation_id=cid, session_id=session_id)
            if session_id is None:
                session = self._session_manager.create_session()
                context.session_id = session.session_id
            self._contexts[cid] = context
        return self._contexts[cid]

    def record_turn(
        self,
        context: ConversationContext,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Add a turn to the context and the underlying conversation history."""
        turn = self._conversation_manager.add_turn(role=role, content=content, metadata=metadata)
        self._chat_history_manager.record_turn(role=role, content=content, metadata=metadata)
        context.history.append(turn)
        return turn

    def update_context(
        self,
        context: ConversationContext,
        last_intent: IntentType | None = None,
        last_route: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationContext:
        """Update the context state with the latest intent and route information."""
        if last_intent is not None:
            context.last_intent = last_intent
        if last_route is not None:
            context.last_route = last_route
        if metadata:
            context.metadata.update(metadata)
        return context

    def get_history(self, conversation_id: str | None = None) -> list[ConversationTurn]:
        """Return the conversation history for a given context or the latest context."""
        if conversation_id is None:
            if not self._contexts:
                return []
            conversation_id = next(reversed(self._contexts))
        context = self._contexts.get(conversation_id)
        return list(context.history) if context else []

    def _new_conversation_id(self) -> str:
        """Create a simple conversation identifier for new conversations."""
        return f"conv-{len(self._contexts) + 1}"
