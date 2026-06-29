"""Conversation orchestration abstractions for the NARVIS Brain subsystem.

This module keeps lightweight conversation state separate from the Brain
orchestration logic so the rest of the AI package can depend on stable,
test-friendly interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


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
class ConversationTurn:
    """A single message exchanged within a conversation."""

    role: str
    content: str
    timestamp: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationSession:
    """Represents a logical chat session for the Brain subsystem."""

    session_id: str
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationManager:
    """Manage turn history for one or more conversations."""

    def __init__(self, max_turns: int | None = None, logger: Any | None = None) -> None:
        """Initialize the manager with optional turn retention."""
        self.max_turns = max_turns
        self.logger = logger
        self._turns_by_conversation: dict[str, list[ConversationTurn]] = {}

    def add_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Append a new turn to a conversation history."""
        turn = ConversationTurn(role=role, content=content, metadata=metadata or {})
        turns = self._turns_by_conversation.setdefault(conversation_id, [])
        turns.append(turn)
        if self.max_turns is not None and len(turns) > self.max_turns:
            self._turns_by_conversation[conversation_id] = turns[-self.max_turns :]
        _emit_log(
            self.logger,
            "debug",
            "Recorded conversation turn",
            conversation_id=conversation_id,
            role=role,
            total_turns=len(self._turns_by_conversation[conversation_id]),
        )
        return turn

    def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        """Return a copy of the stored history for a conversation."""
        return list(self._turns_by_conversation.get(conversation_id, []))

    def list_conversation_ids(self) -> list[str]:
        """Return the known conversation identifiers."""
        return list(self._turns_by_conversation.keys())

    def clear(self, conversation_id: str | None = None) -> None:
        """Clear one conversation history or all histories."""
        if conversation_id is None:
            self._turns_by_conversation.clear()
            _emit_log(self.logger, "info", "Cleared all conversation histories")
            return

        self._turns_by_conversation.pop(conversation_id, None)
        _emit_log(self.logger, "info", "Cleared conversation history", conversation_id=conversation_id)


class ChatHistoryManager(ConversationManager):
    """Specialized conversation history manager for chat transcripts."""

    def record_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Record a turn using chat-oriented naming semantics."""
        return self.add_turn(
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata=metadata,
        )


class SessionManager:
    """Create and track logical chat sessions."""

    def __init__(self, logger: Any | None = None) -> None:
        """Initialize the in-memory session registry."""
        self.logger = logger
        self._sessions: dict[str, ConversationSession] = {}

    def create_session(
        self,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationSession:
        """Create a session or return an existing session with the same id."""
        resolved_session_id = session_id or f"session-{uuid4().hex}"
        if resolved_session_id in self._sessions:
            session = self._sessions[resolved_session_id]
            if metadata:
                session.metadata.update(metadata)
            session.updated_at = _utc_now()
            _emit_log(self.logger, "debug", "Reused existing session", session_id=resolved_session_id)
            return session

        session = ConversationSession(session_id=resolved_session_id, metadata=dict(metadata or {}))
        self._sessions[resolved_session_id] = session
        _emit_log(self.logger, "info", "Created session", session_id=resolved_session_id)
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        """Fetch an existing session by identifier."""
        return self._sessions.get(session_id)

    def touch_session(self, session_id: str) -> ConversationSession | None:
        """Update the session timestamp to mark it as active."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.updated_at = _utc_now()
        return session

    def update_session(self, session_id: str, **updates: Any) -> ConversationSession | None:
        """Update session attributes while refreshing the session timestamp."""
        session = self._sessions.get(session_id)
        if session is None:
            return None

        for key, value in updates.items():
            if key == "metadata" and isinstance(value, dict):
                session.metadata.update(value)
                continue
            if hasattr(session, key):
                setattr(session, key, value)
        session.updated_at = _utc_now()
        _emit_log(self.logger, "debug", "Updated session", session_id=session_id)
        return session

    def delete_session(self, session_id: str) -> None:
        """Remove a session from the manager."""
        self._sessions.pop(session_id, None)
        _emit_log(self.logger, "info", "Deleted session", session_id=session_id)

    def list_sessions(self) -> list[ConversationSession]:
        """Return all tracked sessions."""
        return list(self._sessions.values())
