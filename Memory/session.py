"""Session-scoped memory and conversation history for NARVIS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from .memory import MemoryEntry, MemoryRepository, _emit_log, utc_now


@dataclass(slots=True)
class SessionTurn:
    """A persisted conversation turn associated with a session."""

    session_id: str
    role: str
    content: str
    conversation_id: str | None = None
    turn_id: str = field(default_factory=lambda: f"turn-{uuid4().hex}")
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the turn into a serializable dictionary."""

        return {
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_value(cls, value: Any) -> SessionTurn | None:
        """Create a :class:`SessionTurn` from repository data."""

        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            return None
        timestamp = value.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif not isinstance(timestamp, datetime):
            timestamp = utc_now()
        return cls(
            session_id=str(value.get("session_id", "")),
            role=str(value.get("role", "user")),
            content=str(value.get("content", "")),
            conversation_id=value.get("conversation_id"),
            turn_id=str(value.get("turn_id", f"turn-{uuid4().hex}")),
            timestamp=timestamp,
            metadata=dict(value.get("metadata", {})),
        )


class SessionMemory(Protocol):
    """Protocol for session-scoped memory services."""

    def store(self, session_id: str, key: str, value: Any, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a value in a named session scope."""

    def recall(self, session_id: str, key: str) -> MemoryEntry | None:
        """Retrieve a session-scoped value."""


class BaseSessionMemory(ABC):
    """Abstract base class for session memory implementations."""

    def __init__(self, repository: MemoryRepository, logger: Any | None = None) -> None:
        self.repository = repository
        self.logger = logger

    @abstractmethod
    def store(self, session_id: str, key: str, value: Any, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Store a value in a named session scope."""

    @abstractmethod
    def recall(self, session_id: str, key: str) -> MemoryEntry | None:
        """Retrieve a session-scoped value."""


class InMemorySessionMemory(BaseSessionMemory):
    """Repository-backed session memory with conversation history support."""

    def store(self, session_id: str, key: str, value: Any, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """Persist a session-scoped key-value entry using the repository."""

        normalized_metadata = {"session_id": session_id, "entry_type": "session_value", **dict(metadata or {})}
        entry = MemoryEntry(
            key=self._session_key(session_id, key),
            value=value,
            category="session",
            metadata=normalized_metadata,
        )
        self.repository.save(entry)
        _emit_log(self.logger, "debug", "Stored session memory", session_id=session_id, key=key)
        return entry

    def recall(self, session_id: str, key: str) -> MemoryEntry | None:
        """Retrieve a session-scoped entry."""

        entry = self.repository.load(self._session_key(session_id, key))
        if entry is None or entry.category != "session":
            return None
        return entry

    def record_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTurn:
        """Persist a conversation turn for later history retrieval."""

        turn = SessionTurn(
            session_id=session_id,
            role=role,
            content=content,
            conversation_id=conversation_id,
            metadata=dict(metadata or {}),
        )
        entry = MemoryEntry(
            key=self._history_key(turn),
            value=turn.to_dict(),
            category="conversation_history",
            timestamp=turn.timestamp,
            metadata={
                "session_id": session_id,
                "conversation_id": conversation_id,
                "role": role,
                "entry_type": "conversation_turn",
                **turn.metadata,
            },
        )
        self.repository.save(entry)
        _emit_log(
            self.logger,
            "debug",
            "Recorded session conversation turn",
            session_id=session_id,
            conversation_id=conversation_id,
            role=role,
        )
        return turn

    def get_history(
        self,
        session_id: str,
        conversation_id: str | None = None,
        limit: int | None = None,
    ) -> list[SessionTurn]:
        """Return conversation history for a session."""

        history_entries = self.repository.list_entries(category="conversation_history")
        turns: list[SessionTurn] = []
        for entry in history_entries:
            if entry.metadata.get("session_id") != session_id:
                continue
            if conversation_id is not None and entry.metadata.get("conversation_id") != conversation_id:
                continue
            turn = SessionTurn.from_value(entry.value)
            if turn is not None:
                turns.append(turn)
        turns.sort(key=lambda turn: (turn.timestamp, turn.turn_id))
        if limit is not None:
            turns = turns[-max(limit, 0) :]
        _emit_log(
            self.logger,
            "debug",
            "Loaded session conversation history",
            session_id=session_id,
            conversation_id=conversation_id,
            count=len(turns),
        )
        return turns

    def clear_history(self, session_id: str, conversation_id: str | None = None) -> None:
        """Delete persisted conversation history for a session."""

        deleted = 0
        for entry in self.repository.list_entries(category="conversation_history"):
            if entry.metadata.get("session_id") != session_id:
                continue
            if conversation_id is not None and entry.metadata.get("conversation_id") != conversation_id:
                continue
            self.repository.delete(entry.key)
            deleted += 1
        _emit_log(
            self.logger,
            "info",
            "Cleared session conversation history",
            session_id=session_id,
            conversation_id=conversation_id,
            deleted=deleted,
        )

    def clear_session(self, session_id: str) -> None:
        """Delete all session state and conversation history for a session."""

        deleted = 0
        for entry in self.repository.list_entries():
            if entry.metadata.get("session_id") != session_id:
                continue
            self.repository.delete(entry.key)
            deleted += 1
        _emit_log(self.logger, "info", "Cleared session memory", session_id=session_id, deleted=deleted)

    def _session_key(self, session_id: str, key: str) -> str:
        """Build a stable repository key for session-scoped values."""

        return f"session:{session_id}:{key}"

    def _history_key(self, turn: SessionTurn) -> str:
        """Build a stable repository key for conversation history."""

        conversation_id = turn.conversation_id or "default"
        return f"history:{turn.session_id}:{conversation_id}:{turn.turn_id}"


__all__ = ["BaseSessionMemory", "InMemorySessionMemory", "SessionMemory", "SessionTurn"]
