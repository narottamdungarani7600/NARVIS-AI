"""In-memory conversation archive metadata services."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Any, Protocol

from Conversation.core.models import (
    ConversationSession,
    ConversationStatus,
    new_id,
    utc_now,
)

from .exceptions import (
    ConversationAlreadyArchivedError,
    ConversationArchiveError,
    ConversationExpiredError,
    ConversationNotArchivedError,
)
from .models import ArchiveMetadata


class ArchiveRepository(Protocol):
    """Replaceable process-local archive metadata repository contract."""

    def add(self, metadata: ArchiveMetadata) -> None:
        """Retain a new archive generation."""

    def replace(self, metadata: ArchiveMetadata) -> None:
        """Replace the latest generation metadata."""

    def current(self, conversation_id: str) -> ArchiveMetadata | None:
        """Return the latest archive generation."""

    def history(self, conversation_id: str) -> tuple[ArchiveMetadata, ...]:
        """Return all archive generations for one conversation."""

    def list(self) -> tuple[ArchiveMetadata, ...]:
        """Return every retained archive generation."""

    def remove(self, conversation_id: str) -> tuple[ArchiveMetadata, ...]:
        """Remove archive metadata associated with a cleaned session."""


class InMemoryArchiveRepository:
    """Thread-safe in-memory archive history with no filesystem behavior."""

    def __init__(self) -> None:
        self._archives: dict[str, tuple[ArchiveMetadata, ...]] = {}
        self._lock = RLock()

    def add(self, metadata: ArchiveMetadata) -> None:
        if not isinstance(metadata, ArchiveMetadata):
            raise TypeError("metadata must be ArchiveMetadata")
        with self._lock:
            history = self._archives.get(metadata.conversation_id, ())
            if history and history[-1].active:
                raise ConversationAlreadyArchivedError(
                    f"conversation '{metadata.conversation_id}' is already archived"
                )
            self._archives[metadata.conversation_id] = (*history, metadata)

    def replace(self, metadata: ArchiveMetadata) -> None:
        if not isinstance(metadata, ArchiveMetadata):
            raise TypeError("metadata must be ArchiveMetadata")
        with self._lock:
            history = self._archives.get(metadata.conversation_id, ())
            if not history or history[-1].archive_id != metadata.archive_id:
                raise ConversationNotArchivedError(
                    f"conversation '{metadata.conversation_id}' has no matching archive"
                )
            self._archives[metadata.conversation_id] = (*history[:-1], metadata)

    def current(self, conversation_id: str) -> ArchiveMetadata | None:
        with self._lock:
            history = self._archives.get(conversation_id, ())
            return history[-1] if history else None

    def history(self, conversation_id: str) -> tuple[ArchiveMetadata, ...]:
        with self._lock:
            return self._archives.get(conversation_id, ())

    def list(self) -> tuple[ArchiveMetadata, ...]:
        with self._lock:
            return tuple(
                metadata for history in self._archives.values() for metadata in history
            )

    def remove(self, conversation_id: str) -> tuple[ArchiveMetadata, ...]:
        with self._lock:
            return self._archives.pop(conversation_id, ())


class ConversationArchiveService:
    """Create and restore archive metadata without persisting conversation data."""

    def __init__(
        self,
        repository: ArchiveRepository | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        resolved = repository or InMemoryArchiveRepository()
        if not all(
            callable(getattr(resolved, method, None))
            for method in ("add", "replace", "current", "history", "list", "remove")
        ):
            raise TypeError(
                "repository must provide add, replace, current, history, list, and remove"
            )
        self._repository = resolved
        self._clock = clock
        self._id_factory = id_factory

    @property
    def repository(self) -> ArchiveRepository:
        """Return the injected archive repository."""

        return self._repository

    def archive(
        self,
        session: ConversationSession,
        *,
        reason: str = "",
        tags: Iterable[str] = (),
        retention_until: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        archived_at: datetime | None = None,
    ) -> ArchiveMetadata:
        """Create an archive generation for an active or closed session."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        if session.archived:
            raise ConversationAlreadyArchivedError(
                f"conversation '{session.session_id}' is already archived"
            )
        if session.expired:
            raise ConversationExpiredError(
                f"conversation '{session.session_id}' is expired"
            )
        if session.status not in {
            ConversationStatus.ACTIVE,
            ConversationStatus.CLOSED,
        }:
            raise ConversationArchiveError("conversation cannot be archived")
        if isinstance(tags, (str, bytes)):
            raise ConversationArchiveError("tags must be an iterable of identifiers")
        timestamp = max(session.updated_at, self._time(archived_at, "archived_at"))
        try:
            archive = ArchiveMetadata(
                conversation_id=session.session_id,
                original_status=session.status,
                archived_at=timestamp,
                reason=reason,
                tags=tuple(tags),
                retention_until=retention_until,
                message_count=session.history.count,
                metadata={} if metadata is None else metadata,
                archive_id=self._id_factory(),
            )
        except (TypeError, ValueError) as error:
            raise ConversationArchiveError(str(error)) from error
        self._repository.add(archive)
        return archive

    def restore(
        self,
        conversation_id: str,
        *,
        restored_at: datetime | None = None,
    ) -> ArchiveMetadata:
        """Mark the current archive generation restored and retain its history."""

        archive = self._repository.current(conversation_id)
        if archive is None or not archive.active:
            raise ConversationNotArchivedError(
                f"conversation '{conversation_id}' is not archived"
            )
        timestamp = max(
            archive.archived_at,
            self._time(restored_at, "restored_at"),
        )
        restored = replace(archive, restored_at=timestamp)
        self._repository.replace(restored)
        return restored

    def current(self, conversation_id: str) -> ArchiveMetadata | None:
        """Return the latest archive metadata, including restored generations."""

        return self._repository.current(conversation_id)

    def history(self, conversation_id: str) -> tuple[ArchiveMetadata, ...]:
        """Return immutable archive metadata history for one conversation."""

        return self._repository.history(conversation_id)

    def remove(self, conversation_id: str) -> tuple[ArchiveMetadata, ...]:
        """Remove metadata for a conversation removed by in-memory cleanup."""

        return self._repository.remove(conversation_id)

    def _time(self, value: datetime | None, name: str) -> datetime:
        timestamp = self._clock() if value is None else value
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ConversationArchiveError(f"{name} must be a timezone-aware datetime")
        return timestamp


ArchiveService = ConversationArchiveService
InMemoryArchiveStore = InMemoryArchiveRepository


__all__ = [
    "ArchiveRepository",
    "ArchiveService",
    "ConversationArchiveService",
    "InMemoryArchiveRepository",
    "InMemoryArchiveStore",
]
