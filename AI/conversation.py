"""Conversation orchestration abstractions for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class ConversationTurn:
    """A single message exchanged within a conversation."""

    role: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationSession:
    """Represents a logical chat session for the Brain subsystem."""

    session_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationManager:
    """Generic conversation history manager for Brain components."""

    def __init__(self) -> None:
        self._turns: list[ConversationTurn] = []

    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Append a new turn to the conversation history."""
        turn = ConversationTurn(role=role, content=content, metadata=metadata or {})
        self._turns.append(turn)
        return turn

    def get_history(self) -> list[ConversationTurn]:
        """Return a copy of the conversation history."""
        return list(self._turns)

    def clear(self) -> None:
        """Clear all recorded conversation turns."""
        self._turns.clear()


class ChatHistoryManager:
    """Maintains conversational history with configurable retention."""

    def __init__(self, max_turns: int | None = None) -> None:
        self.max_turns = max_turns
        self._turns: list[ConversationTurn] = []

    def record_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Record a turn and enforce the configured retention window."""
        turn = ConversationTurn(role=role, content=content, metadata=metadata or {})
        self._turns.append(turn)
        if self.max_turns is not None and len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]
        return turn

    def get_history(self) -> list[ConversationTurn]:
        """Return a copy of the stored history."""
        return list(self._turns)

    def clear(self) -> None:
        """Clear the stored history."""
        self._turns.clear()


class SessionManager:
    """Creates and tracks logical chat sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def create_session(self, session_id: str | None = None, metadata: dict[str, Any] | None = None) -> ConversationSession:
        """Create a new session object."""
        session_id = session_id or f"session-{len(self._sessions) + 1}"
        session = ConversationSession(session_id=session_id, metadata=metadata or {})
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        """Fetch an existing session by identifier."""
        return self._sessions.get(session_id)

    def update_session(self, session_id: str, **updates: Any) -> ConversationSession | None:
        """Update a session's metadata or timestamp."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        for key, value in updates.items():
            setattr(session, key, value)
        session.updated_at = datetime.now(timezone.utc)
        return session

    def delete_session(self, session_id: str) -> None:
        """Remove a session from the manager."""
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[ConversationSession]:
        """List all tracked sessions."""
        return list(self._sessions.values())
