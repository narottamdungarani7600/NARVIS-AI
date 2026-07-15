"""In-memory coordination for complete conversation lifecycle management."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Any

from Core.logger import LogLevel, Logger, NullLogger
from Conversation.core.events import EventPublisher
from Conversation.core.models import (
    ConversationSession,
    ConversationStatus,
    utc_now,
)
from Conversation.core.session import ConversationSessionStore

from .archive import ConversationArchiveService
from .cleanup import ConversationCleanupService
from .events import (
    CONVERSATION_ARCHIVED_EVENT,
    CONVERSATION_CLEANED_EVENT,
    CONVERSATION_EXPIRED_EVENT,
    CONVERSATION_RESTORED_EVENT,
    CONVERSATION_SESSION_SWITCHED_EVENT,
    ConversationLifecycleEvents,
)
from .exceptions import (
    CleanupError,
    ConversationAlreadyArchivedError,
    ConversationExpiredError,
    ConversationNotArchivedError,
    LifecycleValidationError,
    NoCurrentSessionError,
    SessionRemovalUnsupportedError,
    SessionSwitchError,
)
from .export import ConversationExportBuilder, ExportBuilder
from .models import (
    ArchiveMetadata,
    CleanupReport,
    ContextCleanupPolicy,
    ConversationExport,
    ConversationHealth,
    ExportFormat,
    HealthStatus,
    RetentionPolicy,
    SessionInfo,
    SessionSwitch,
)


class ConversationLifecycleManager:
    """Coordinate sessions, archive metadata, retention, cleanup, and exports."""

    def __init__(
        self,
        session_store: ConversationSessionStore,
        archive_service: ConversationArchiveService | None = None,
        cleanup_service: ConversationCleanupService | None = None,
        export_builder: ExportBuilder | None = None,
        events: ConversationLifecycleEvents | None = None,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not all(
            callable(getattr(session_store, method, None))
            for method in ("add", "replace", "get", "list")
        ):
            raise TypeError("session_store must provide add, replace, get, and list")
        self._store = session_store
        self._clock = clock
        self._logger = logger or NullLogger("narvis.conversation.lifecycle")
        resolved_archives = archive_service or ConversationArchiveService(clock=clock)
        if not all(
            callable(getattr(resolved_archives, method, None))
            for method in ("archive", "restore", "current", "history", "remove")
        ):
            raise TypeError("archive_service does not implement the archive contract")
        resolved_cleanup = cleanup_service or ConversationCleanupService()
        if not all(
            callable(getattr(resolved_cleanup, method, None))
            for method in ("due_for_expiration", "candidates", "cleanup_context")
        ):
            raise TypeError("cleanup_service does not implement the cleanup contract")
        resolved_export = export_builder or ConversationExportBuilder(clock=clock)
        if not callable(getattr(resolved_export, "prepare", None)):
            raise TypeError("export_builder must provide a prepare method")
        resolved_events = events or ConversationLifecycleEvents(
            event_bus,
            logger=self._logger,
        )
        if not callable(getattr(resolved_events, "publish", None)):
            raise TypeError("events must provide a publish method")
        self._archives = resolved_archives
        self._cleanup = resolved_cleanup
        self._export = resolved_export
        self._events = resolved_events
        self._last_accessed: dict[str, datetime] = {}
        self._current_session_id: str | None = None
        self._last_switch: SessionSwitch | None = None
        self._lock = RLock()
        for session in self._store.list():
            self.register(session)

    @property
    def current_session_id(self) -> str | None:
        """Return the currently selected active session identifier."""

        with self._lock:
            return self._current_session_id

    @property
    def last_switch(self) -> SessionSwitch | None:
        """Return the latest immutable session switch result."""

        with self._lock:
            return self._last_switch

    def register(
        self,
        session: ConversationSession,
        *,
        make_current: bool | None = None,
    ) -> None:
        """Register lifecycle tracking for a retained session snapshot."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        if make_current is not None and not isinstance(make_current, bool):
            raise LifecycleValidationError("make_current must be a bool or None")
        with self._lock:
            self._last_accessed.setdefault(session.session_id, session.updated_at)
            should_select = session.active and (
                make_current is True
                or (make_current is None and self._current_session_id is None)
            )
            if should_select:
                self._current_session_id = session.session_id

    def synchronize(self, session: ConversationSession) -> None:
        """Refresh lifecycle access facts after a core session update."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        with self._lock:
            existing = self._last_accessed.get(
                session.session_id,
                session.created_at,
            )
            self._last_accessed[session.session_id] = max(
                existing,
                session.updated_at,
            )
            if self._current_session_id == session.session_id and not session.active:
                self._current_session_id = None

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
        """Archive one active or closed session and preserve its original state."""

        with self._lock:
            current = self._store.get(session_id)
            if current.archived:
                raise ConversationAlreadyArchivedError(
                    f"conversation '{session_id}' is already archived"
                )
            if current.expired:
                raise ConversationExpiredError(
                    f"conversation '{session_id}' is expired"
                )
            archive = self._archives.archive(
                current,
                reason=reason,
                tags=tags,
                retention_until=retention_until,
                metadata=metadata,
                archived_at=archived_at,
            )
            session = replace(
                current,
                status=ConversationStatus.ARCHIVED,
                archived_at=archive.archived_at,
                updated_at=archive.archived_at,
            )
            self._store.replace(session)
            self.synchronize(session)
            if self._current_session_id == session_id:
                self._current_session_id = None
            self._log(
                LogLevel.INFO,
                "Conversation archived",
                conversation_id=session_id,
                archive_id=archive.archive_id,
                original_status=archive.original_status.value,
                message_count=archive.message_count,
            )
            self._events.publish(
                CONVERSATION_ARCHIVED_EVENT,
                session_id,
                archive_id=archive.archive_id,
                original_status=archive.original_status.value,
                message_count=archive.message_count,
                retention_until=(
                    archive.retention_until.isoformat()
                    if archive.retention_until is not None
                    else None
                ),
            )
            return session

    archive = archive_conversation

    def restore_conversation(
        self,
        session_id: str,
        *,
        restored_at: datetime | None = None,
    ) -> ConversationSession:
        """Restore an archived session to the state it had before archival."""

        with self._lock:
            current = self._store.get(session_id)
            if not current.archived:
                raise ConversationNotArchivedError(
                    f"conversation '{session_id}' is not archived"
                )
            archive = self._archives.restore(
                session_id,
                restored_at=restored_at,
            )
            assert archive.restored_at is not None
            session = replace(
                current,
                status=archive.original_status,
                updated_at=archive.restored_at,
            )
            self._store.replace(session)
            self.synchronize(session)
            self._log(
                LogLevel.INFO,
                "Conversation restored",
                conversation_id=session_id,
                archive_id=archive.archive_id,
                restored_status=session.status.value,
            )
            self._events.publish(
                CONVERSATION_RESTORED_EVENT,
                session_id,
                archive_id=archive.archive_id,
                restored_status=session.status.value,
            )
            return session

    restore = restore_conversation

    def switch_session(
        self,
        session_id: str,
        *,
        switched_at: datetime | None = None,
    ) -> SessionSwitch:
        """Select one active session without altering its conversation content."""

        with self._lock:
            session = self._store.get(session_id)
            if not session.active:
                raise SessionSwitchError(f"conversation '{session_id}' is not active")
            timestamp = max(
                session.created_at,
                self._time(switched_at, "switched_at"),
            )
            previous = self._current_session_id
            result = SessionSwitch(
                current_session_id=session_id,
                previous_session_id=previous,
                switched_at=timestamp,
            )
            self._current_session_id = session_id
            self._last_accessed[session_id] = max(
                self._last_accessed.get(session_id, session.created_at),
                timestamp,
            )
            self._last_switch = result
            if result.changed:
                self._log(
                    LogLevel.INFO,
                    "Conversation session switched",
                    previous_session_id=previous,
                    current_session_id=session_id,
                )
                self._events.publish(
                    CONVERSATION_SESSION_SWITCHED_EVENT,
                    session_id,
                    previous_session_id=previous,
                    switched_at=timestamp.isoformat(),
                )
            return result

    def current_session(self) -> ConversationSession:
        """Return the currently selected active session."""

        with self._lock:
            if self._current_session_id is None:
                raise NoCurrentSessionError(
                    "no current conversation session is selected"
                )
            session = self._store.get(self._current_session_id)
            if not session.active:
                raise NoCurrentSessionError(
                    "the selected conversation session is no longer active"
                )
            return session

    def list_sessions(
        self,
        *,
        status: ConversationStatus | None = None,
        include_archived: bool = True,
        include_expired: bool = True,
    ) -> tuple[SessionInfo, ...]:
        """Return deterministic immutable lifecycle views for retained sessions."""

        if status is not None and not isinstance(status, ConversationStatus):
            raise LifecycleValidationError(
                "status must be a ConversationStatus or None"
            )
        if not isinstance(include_archived, bool) or not isinstance(
            include_expired,
            bool,
        ):
            raise LifecycleValidationError("include flags must be bools")
        with self._lock:
            sessions = self._store.list()
            for session in sessions:
                self.register(session)
            values = []
            for session in sessions:
                if status is not None and session.status is not status:
                    continue
                if not include_archived and session.archived:
                    continue
                if not include_expired and session.expired:
                    continue
                archive = self._archives.current(session.session_id)
                values.append(
                    SessionInfo(
                        session_id=session.session_id,
                        status=session.status,
                        message_count=session.history.count,
                        created_at=session.created_at,
                        updated_at=session.updated_at,
                        last_accessed_at=self._accessed(session),
                        expires_at=session.expires_at,
                        archive_id=(
                            archive.archive_id if archive is not None else None
                        ),
                        current=session.session_id == self._current_session_id,
                    )
                )
            return tuple(
                sorted(
                    values,
                    key=lambda info: (info.created_at, info.session_id),
                )
            )

    def set_expiration(
        self,
        session_id: str,
        expires_at: datetime | None,
    ) -> ConversationSession:
        """Set or clear an explicit session expiration timestamp."""

        with self._lock:
            session = self._store.get(session_id)
            if session.archived:
                raise ConversationAlreadyArchivedError(
                    "archived conversations cannot change expiration"
                )
            if session.expired:
                raise ConversationExpiredError(
                    "expired conversations cannot change expiration"
                )
            if expires_at is not None:
                timestamp = self._time(expires_at, "expires_at")
                if timestamp < session.created_at:
                    raise LifecycleValidationError(
                        "expires_at cannot precede session creation"
                    )
            else:
                timestamp = None
            updated = replace(session, expires_at=timestamp)
            self._store.replace(updated)
            return updated

    def expire_conversation(
        self,
        session_id: str,
        *,
        expired_at: datetime | None = None,
        reason: str = "expiration_due",
    ) -> ConversationSession:
        """Mark one active or closed session expired without deleting it."""

        with self._lock:
            session = self._store.get(session_id)
            if session.archived:
                raise ConversationAlreadyArchivedError(
                    "archived conversations use archive retention"
                )
            if session.expired:
                return session
            timestamp = max(
                session.updated_at,
                self._time(expired_at, "expired_at"),
            )
            updated = replace(
                session,
                status=ConversationStatus.EXPIRED,
                expired_at=timestamp,
                updated_at=timestamp,
            )
            self._store.replace(updated)
            self.synchronize(updated)
            if self._current_session_id == session_id:
                self._current_session_id = None
            self._log(
                LogLevel.INFO,
                "Conversation expired",
                conversation_id=session_id,
                reason=reason,
            )
            self._events.publish(
                CONVERSATION_EXPIRED_EVENT,
                session_id,
                expired_at=timestamp.isoformat(),
                reason=reason,
            )
            return updated

    def expire_due_sessions(
        self,
        policy: RetentionPolicy | None = None,
        *,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Mark every due active or closed session expired."""

        resolved = policy or RetentionPolicy()
        if not isinstance(resolved, RetentionPolicy):
            raise TypeError("policy must be a RetentionPolicy")
        timestamp = self._time(now, "now")
        expired: list[str] = []
        with self._lock:
            for session in self._store.list():
                if self._cleanup.due_for_expiration(
                    session,
                    resolved,
                    last_accessed_at=self._accessed(session),
                    now=timestamp,
                ):
                    self.expire_conversation(
                        session.session_id,
                        expired_at=timestamp,
                        reason="retention_policy",
                    )
                    expired.append(session.session_id)
        return tuple(expired)

    def cleanup_sessions(
        self,
        policy: RetentionPolicy | None = None,
        *,
        now: datetime | None = None,
    ) -> CleanupReport:
        """Expire due sessions and remove policy-eligible in-memory snapshots."""

        resolved = policy or RetentionPolicy()
        if not isinstance(resolved, RetentionPolicy):
            raise TypeError("policy must be a RetentionPolicy")
        started = self._time(now, "now")
        with self._lock:
            examined = len(self._store.list())
            expired_ids = self.expire_due_sessions(resolved, now=started)
            sessions = self._store.list()
            archives = {
                session.session_id: archive
                for session in sessions
                if (archive := self._archives.current(session.session_id)) is not None
            }
            candidates = self._cleanup.candidates(
                sessions,
                resolved,
                last_accessed={
                    session.session_id: self._accessed(session) for session in sessions
                },
                archives=archives,
                current_session_id=self._current_session_id,
                now=started,
            )
            remover = getattr(self._store, "remove", None)
            if candidates and not callable(remover):
                raise SessionRemovalUnsupportedError(
                    "injected session_store does not support cleanup removal"
                )
            removed_ids: list[str] = []
            for candidate in candidates:
                assert callable(remover)
                remover(candidate.session_id)
                self._archives.remove(candidate.session_id)
                self._last_accessed.pop(candidate.session_id, None)
                if self._current_session_id == candidate.session_id:
                    self._current_session_id = None
                removed_ids.append(candidate.session_id)
                self._events.publish(
                    CONVERSATION_CLEANED_EVENT,
                    candidate.session_id,
                    reason=candidate.reason.value,
                    scope="session",
                )
            completed = max(started, self._time(now, "completed_at"))
            report = CleanupReport(
                examined_sessions=examined,
                expired_session_ids=expired_ids,
                removed_session_ids=tuple(removed_ids),
                candidates=candidates,
                started_at=started,
                completed_at=completed,
            )
            self._log(
                LogLevel.INFO,
                "Conversation sessions cleaned",
                examined_sessions=examined,
                expired_count=report.expired_count,
                removed_count=report.removed_count,
            )
            return report

    def cleanup_context(
        self,
        session_id: str,
        policy: ContextCleanupPolicy | None = None,
        *,
        cleaned_at: datetime | None = None,
    ) -> ConversationSession:
        """Remove selected transient context from a non-expired session."""

        with self._lock:
            session = self._store.get(session_id)
            if session.expired:
                raise ConversationExpiredError(
                    "expired conversation context cannot be changed"
                )
            timestamp = max(
                session.updated_at,
                self._time(cleaned_at, "cleaned_at"),
            )
            updated = self._cleanup.cleanup_context(
                session,
                policy,
                cleaned_at=timestamp,
            )
            self._store.replace(updated)
            self.synchronize(updated)
            self._events.publish(
                CONVERSATION_CLEANED_EVENT,
                session_id,
                reason="context_cleanup",
                scope="context",
            )
            self._log(
                LogLevel.INFO,
                "Conversation context cleaned",
                conversation_id=session_id,
            )
            return updated

    def archive_metadata(self, session_id: str) -> ArchiveMetadata | None:
        """Return the latest immutable archive metadata."""

        return self._archives.current(session_id)

    def archive_history(self, session_id: str) -> tuple[ArchiveMetadata, ...]:
        """Return all archive generations for one session."""

        return self._archives.history(session_id)

    def prepare_export(
        self,
        session_id: str,
        *,
        format: ExportFormat = ExportFormat.JSON,
        include_metadata: bool = True,
    ) -> ConversationExport:
        """Build an export artifact without filesystem access or mutation."""

        session = self._store.get(session_id)
        return self._export.prepare(
            session,
            format=format,
            archive=self._archives.current(session_id),
            include_metadata=include_metadata,
        )

    export_conversation = prepare_export

    def conversation_health(
        self,
        policy: RetentionPolicy | None = None,
        *,
        now: datetime | None = None,
    ) -> ConversationHealth:
        """Generate aggregate lifecycle, message, and expiration health facts."""

        resolved = policy or RetentionPolicy()
        if not isinstance(resolved, RetentionPolicy):
            raise TypeError("policy must be a RetentionPolicy")
        timestamp = self._time(now, "now")
        sessions = self._store.list()
        expiring = sum(
            self._cleanup.due_for_expiration(
                session,
                resolved,
                last_accessed_at=self._accessed(session),
                now=timestamp,
            )
            for session in sessions
        )
        counts = {
            status: sum(session.status is status for session in sessions)
            for status in ConversationStatus
        }
        total = len(sessions)
        attention = counts[ConversationStatus.EXPIRED] + expiring
        if total == 0:
            health_status = HealthStatus.EMPTY
            score = 100.0
        elif attention:
            health_status = HealthStatus.ATTENTION
            score = max(0.0, 100.0 - (attention / total * 60.0))
        else:
            health_status = HealthStatus.HEALTHY
            score = 100.0
        current = self._current_session_id
        if current is not None and all(
            session.session_id != current for session in sessions
        ):
            current = None
        return ConversationHealth(
            status=health_status,
            total_sessions=total,
            active_sessions=counts[ConversationStatus.ACTIVE],
            closed_sessions=counts[ConversationStatus.CLOSED],
            archived_sessions=counts[ConversationStatus.ARCHIVED],
            expired_sessions=counts[ConversationStatus.EXPIRED],
            total_messages=sum(session.history.count for session in sessions),
            current_session_id=current,
            expiring_sessions=expiring,
            health_score=score,
            generated_at=timestamp,
        )

    health = conversation_health

    def _accessed(self, session: ConversationSession) -> datetime:
        return max(
            session.updated_at,
            self._last_accessed.get(session.session_id, session.updated_at),
        )

    def _time(self, value: datetime | None, name: str) -> datetime:
        timestamp = self._clock() if value is None else value
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise LifecycleValidationError(f"{name} must be a timezone-aware datetime")
        return timestamp

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


LifecycleManager = ConversationLifecycleManager


__all__ = ["ConversationLifecycleManager", "LifecycleManager"]
