"""In-memory storage contracts for immutable conversation sessions."""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from .exceptions import (
    ConversationNotFoundError,
    DuplicateConversationError,
)
from .models import ConversationSession


class ConversationSessionStore(Protocol):
    """Replaceable storage contract with no file or network requirements."""

    def add(self, session: ConversationSession) -> None:
        """Retain a new conversation session."""

    def replace(self, session: ConversationSession) -> None:
        """Replace one retained immutable snapshot."""

    def get(self, session_id: str) -> ConversationSession:
        """Return a retained conversation session."""

    def list(self) -> tuple[ConversationSession, ...]:
        """Return retained sessions in insertion order."""


class InMemoryConversationSessionStore:
    """Thread-safe process-local storage for immutable session snapshots."""

    def __init__(self) -> None:
        """Initialize empty in-memory storage."""

        self._sessions: dict[str, ConversationSession] = {}
        self._lock = RLock()

    def add(self, session: ConversationSession) -> None:
        """Retain a new session or raise on duplicate identifiers."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        with self._lock:
            if session.session_id in self._sessions:
                raise DuplicateConversationError(
                    f"conversation '{session.session_id}' already exists"
                )
            self._sessions[session.session_id] = session

    def replace(self, session: ConversationSession) -> None:
        """Replace an existing session snapshot."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        with self._lock:
            if session.session_id not in self._sessions:
                raise ConversationNotFoundError(
                    f"conversation '{session.session_id}' was not found"
                )
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> ConversationSession:
        """Return one retained session or raise a typed lookup error."""

        if not isinstance(session_id, str) or not session_id:
            raise ConversationNotFoundError(
                "a non-empty conversation session ID is required"
            )
        with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as error:
                raise ConversationNotFoundError(
                    f"conversation '{session_id}' was not found"
                ) from error

    def find(self, session_id: str) -> ConversationSession | None:
        """Return one session or None without raising."""

        if not isinstance(session_id, str):
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> tuple[ConversationSession, ...]:
        """Return sessions in insertion order."""

        with self._lock:
            return tuple(self._sessions.values())


SessionStore = ConversationSessionStore
InMemorySessionStore = InMemoryConversationSessionStore
SessionManager = InMemoryConversationSessionStore


__all__ = [
    "ConversationSessionStore",
    "InMemoryConversationSessionStore",
    "InMemorySessionStore",
    "SessionManager",
    "SessionStore",
]
