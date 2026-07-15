"""Thread-safe storage for immutable AI orchestration sessions."""

from __future__ import annotations

from threading import RLock

from .exceptions import SessionAlreadyExistsError, SessionNotFoundError
from .models import OrchestrationSession


class OrchestrationSessionStore:
    """Retain immutable session snapshots behind a re-entrant lock."""

    def __init__(self) -> None:
        self._sessions: dict[str, OrchestrationSession] = {}
        self._lock = RLock()

    def add(self, session: OrchestrationSession) -> OrchestrationSession:
        if not isinstance(session, OrchestrationSession):
            raise TypeError("session must be an OrchestrationSession")
        with self._lock:
            if session.session_id in self._sessions:
                raise SessionAlreadyExistsError(
                    f"orchestration session '{session.session_id}' already exists"
                )
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> OrchestrationSession:
        identifier = self._session_id(session_id)
        with self._lock:
            try:
                return self._sessions[identifier]
            except KeyError as error:
                raise SessionNotFoundError(
                    f"orchestration session '{identifier}' was not found"
                ) from error

    def replace(self, session: OrchestrationSession) -> OrchestrationSession:
        if not isinstance(session, OrchestrationSession):
            raise TypeError("session must be an OrchestrationSession")
        with self._lock:
            if session.session_id not in self._sessions:
                raise SessionNotFoundError(
                    f"orchestration session '{session.session_id}' was not found"
                )
            self._sessions[session.session_id] = session
            return session

    def list(self) -> tuple[OrchestrationSession, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._sessions.values(),
                    key=lambda session: (
                        session.created_at,
                        session.session_id.casefold(),
                        session.session_id,
                    ),
                )
            )

    def clear(self) -> tuple[OrchestrationSession, ...]:
        with self._lock:
            sessions = self.list()
            self._sessions.clear()
            return sessions

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    @staticmethod
    def _session_id(value: object) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 128
        ):
            raise ValueError("session_id must be normalized non-empty text")
        return value


InMemoryOrchestrationSessionStore = OrchestrationSessionStore


__all__ = ["InMemoryOrchestrationSessionStore", "OrchestrationSessionStore"]
