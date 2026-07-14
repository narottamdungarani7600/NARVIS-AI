"""Planning-only execution session lifecycle and approval tracking."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from Core.execution import ExecutionRequest
from Core.logger import LogLevel, Logger, NullLogger

from .approval import ApprovalManager, GatewayAuthorizer
from .exceptions import (
    DuplicateApprovalError,
    DuplicateSessionError,
    SessionExpiredError,
    SessionNotFoundError,
)
from .models import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ExecutionHistoryEntry,
    ExecutionSession,
    SessionStatus,
    immutable_mapping,
    new_id,
    utc_now,
)
from .queue import EventPublisher


class ExecutionSessionManager:
    """Create and retain immutable safe-execution session snapshots."""

    def __init__(
        self,
        approval_manager: ApprovalManager | None = None,
        *,
        gateway: GatewayAuthorizer | None = None,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
        default_ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        """Initialize session dependencies and in-memory immutable storage."""

        if approval_manager is not None and gateway is not None:
            raise ValueError("gateway must be injected through approval_manager")
        if not isinstance(default_ttl, timedelta) or default_ttl <= timedelta(0):
            raise ValueError("default_ttl must be a positive timedelta")
        self._logger = logger or NullLogger("narvis.execution.session")
        self._clock = clock
        self._id_factory = id_factory
        self._default_ttl = default_ttl
        self._approval_manager = approval_manager or ApprovalManager(
            gateway,
            event_bus=event_bus,
            logger=self._logger,
            clock=clock,
            id_factory=id_factory,
        )
        self._sessions: dict[str, ExecutionSession] = {}
        self._lock = RLock()

    @property
    def approval_manager(self) -> ApprovalManager:
        """Return the approval service used by this session manager."""

        return self._approval_manager

    def create_session(
        self,
        *,
        owner_id: str,
        metadata: Mapping[str, Any] | None = None,
        session_id: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> ExecutionSession:
        """Create and retain one active planning session."""

        now = created_at or self._now()
        if expires_at is not None and ttl is not None:
            raise ValueError("expires_at and ttl are mutually exclusive")
        lifetime = ttl if ttl is not None else self._default_ttl
        if not isinstance(lifetime, timedelta) or lifetime <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta")
        session = ExecutionSession(
            session_id=session_id or self._make_id(),
            owner_id=owner_id,
            created_at=now,
            expires_at=expires_at or now + lifetime,
            metadata=metadata or {},
        )
        with self._lock:
            if session.session_id in self._sessions:
                raise DuplicateSessionError(
                    f"execution session '{session.session_id}' already exists"
                )
            self._sessions[session.session_id] = session
        self._log(
            LogLevel.INFO,
            "Safe execution session created",
            session_id=session.session_id,
            owner_id=session.owner_id,
            expires_at=session.expires_at.isoformat(),
            executed=False,
        )
        return session

    def create(self, **kwargs: Any) -> ExecutionSession:
        """Return :meth:`create_session` for concise callers."""

        return self.create_session(**kwargs)

    def get_session(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Return a session after applying deadline expiration."""

        with self._lock:
            session = self._require_session(session_id)
            now = at or self._now()
            if session.status is SessionStatus.ACTIVE and now >= session.expires_at:
                session = self._expire_locked(session, now=now)
            return session

    def expire_session(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Expire a session once its configured deadline has elapsed."""

        with self._lock:
            session = self._require_session(session_id)
            now = at or self._now()
            if session.status is SessionStatus.EXPIRED:
                return session
            if session.status is not SessionStatus.ACTIVE:
                raise SessionExpiredError(
                    f"execution session '{session_id}' is {session.status.value}"
                )
            if now < session.expires_at:
                raise SessionExpiredError(
                    "execution session has not reached its expiry"
                )
            return self._expire_locked(session, now=now)

    def expire(
        self, session_id: str, *, at: datetime | None = None
    ) -> ExecutionSession:
        """Compatibility alias for :meth:`expire_session`."""

        return self.expire_session(session_id, at=at)

    def close_session(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Close an active session and cancel any pending approvals."""

        with self._lock:
            session = self.get_session(session_id, at=at)
            if session.status is not SessionStatus.ACTIVE:
                raise SessionExpiredError(
                    f"execution session '{session_id}' is {session.status.value}"
                )
            closed = replace(session, status=SessionStatus.CLOSED)
            self._sessions[session_id] = closed
            self._cancel_pending_approvals(closed, reason="session_closed")
            self._log(
                LogLevel.INFO,
                "Safe execution session closed",
                session_id=session_id,
                executed=False,
            )
            return closed

    def is_expired(self, session_id: str, *, at: datetime | None = None) -> bool:
        """Return whether a retained session is expired at the supplied time."""

        return self.get_session(session_id, at=at).status is SessionStatus.EXPIRED

    def update_metadata(
        self,
        session_id: str,
        metadata: Mapping[str, Any],
        *,
        replace_existing: bool = False,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Return a new session snapshot with detached metadata."""

        with self._lock:
            session = self._require_active(session_id, at=at)
            incoming = immutable_mapping(metadata)
            if replace_existing:
                updated_metadata = incoming
            else:
                updated_metadata = {**session.metadata, **incoming}
            updated = replace(session, metadata=updated_metadata)
            self._sessions[session_id] = updated
            return updated

    def track_approval(
        self,
        session_id: str,
        approval: ApprovalRequest | str,
        *,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Track one exact approval request identifier in an active session."""

        with self._lock:
            session = self._require_active(session_id, at=at)
            if isinstance(approval, ApprovalRequest):
                if approval.session_id != session_id:
                    raise ValueError("approval request belongs to a different session")
                request_id = approval.request_id
            elif isinstance(approval, str) and approval:
                request_id = approval
            else:
                raise TypeError("approval must be an ApprovalRequest or request_id")
            if request_id in session.approval_request_ids:
                raise DuplicateApprovalError(
                    f"approval request '{request_id}' is already tracked"
                )
            updated = replace(
                session,
                approval_request_ids=(*session.approval_request_ids, request_id),
            )
            self._sessions[session_id] = updated
            return updated

    def request_approval(
        self,
        session_id: str,
        execution_request: ExecutionRequest,
        *,
        requested_by: str,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> ApprovalRequest:
        """Create an approval through the injected manager and track it."""

        self._require_active(session_id)
        request = self._approval_manager.request_approval(
            execution_request,
            session_id=session_id,
            requested_by=requested_by,
            description=description,
            metadata=metadata,
            expires_at=expires_at,
            ttl=ttl,
        )
        with self._lock:
            self.track_approval(session_id, request)
            self._append_history_locked(
                session_id,
                ExecutionHistoryEntry(
                    request_id=request.request_id,
                    action=request.action,
                    approval_status=ApprovalStatus.PENDING,
                    recorded_at=request.requested_at,
                    details={"execution_request_id": request.execution_request_id},
                ),
            )
        return request

    def respond_to_approval(self, response: ApprovalResponse) -> ApprovalResponse:
        """Apply a response and append its terminal status to session history."""

        if not isinstance(response, ApprovalResponse):
            raise TypeError("response must be an ApprovalResponse")
        request = self._approval_manager.get_request(response.request_id)
        self._require_active(request.session_id)
        completed = self._approval_manager.respond(response)
        with self._lock:
            session = self._require_session(request.session_id)
            if request.request_id not in session.approval_request_ids:
                session = replace(
                    session,
                    approval_request_ids=(
                        *session.approval_request_ids,
                        request.request_id,
                    ),
                )
                self._sessions[session.session_id] = session
            self._append_history_locked(
                session.session_id,
                ExecutionHistoryEntry(
                    request_id=request.request_id,
                    action=request.action,
                    approval_status=completed.status,
                    recorded_at=completed.responded_at,
                    details={"responded_by": completed.responded_by},
                ),
            )
        return completed

    def record_history(
        self,
        session_id: str,
        entry: ExecutionHistoryEntry,
        *,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Append a typed non-executing history record to an active session."""

        if not isinstance(entry, ExecutionHistoryEntry):
            raise TypeError("entry must be an ExecutionHistoryEntry")
        with self._lock:
            self._require_active(session_id, at=at)
            return self._append_history_locked(session_id, entry)

    def history(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> tuple[ExecutionHistoryEntry, ...]:
        """Return immutable planning history for one session."""

        return self.get_session(session_id, at=at).history

    def approvals(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> tuple[str, ...]:
        """Return tracked approval request identifiers for one session."""

        return self.get_session(session_id, at=at).approval_request_ids

    def list_sessions(
        self, *, at: datetime | None = None
    ) -> tuple[ExecutionSession, ...]:
        """Return all retained session snapshots in creation order."""

        with self._lock:
            now = at or self._now()
            for session in tuple(self._sessions.values()):
                if session.status is SessionStatus.ACTIVE and now >= session.expires_at:
                    self._expire_locked(session, now=now)
            return tuple(self._sessions.values())

    def _append_history_locked(
        self,
        session_id: str,
        entry: ExecutionHistoryEntry,
    ) -> ExecutionSession:
        """Append one entry while the manager lock is held."""

        session = self._require_session(session_id)
        updated = replace(session, history=(*session.history, entry))
        self._sessions[session_id] = updated
        return updated

    def _require_active(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> ExecutionSession:
        """Return one active, unexpired session."""

        session = self.get_session(session_id, at=at)
        if session.status is not SessionStatus.ACTIVE:
            raise SessionExpiredError(
                f"execution session '{session_id}' is {session.status.value}"
            )
        return session

    def _require_session(self, session_id: str) -> ExecutionSession:
        """Return a retained session or raise a typed lookup error."""

        if not isinstance(session_id, str) or not session_id:
            raise SessionNotFoundError("a non-empty session_id is required")
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise SessionNotFoundError(
                f"execution session '{session_id}' was not found"
            ) from error

    def _expire_locked(
        self,
        session: ExecutionSession,
        *,
        now: datetime,
    ) -> ExecutionSession:
        """Apply session expiration and cancel outstanding approvals."""

        if now < session.expires_at:
            raise SessionExpiredError("execution session has not reached its expiry")
        expired = replace(session, status=SessionStatus.EXPIRED)
        self._sessions[session.session_id] = expired
        self._cancel_pending_approvals(expired, reason="session_expired")
        self._log(
            LogLevel.INFO,
            "Safe execution session expired",
            session_id=session.session_id,
            owner_id=session.owner_id,
            executed=False,
        )
        return expired

    def _cancel_pending_approvals(
        self,
        session: ExecutionSession,
        *,
        reason: str,
    ) -> None:
        """Cancel approvals that cannot outlive their containing session."""

        for request_id in session.approval_request_ids:
            try:
                status = self._approval_manager.status(request_id)
                if status is ApprovalStatus.PENDING:
                    self._approval_manager.cancel(request_id, reason=reason)
            except Exception as error:
                self._log(
                    LogLevel.WARNING,
                    "Unable to cancel approval during session transition",
                    session_id=session.session_id,
                    request_id=request_id,
                    error_type=type(error).__name__,
                )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failures to alter session state."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value

    def _make_id(self) -> str:
        """Return and validate one injected opaque identifier."""

        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("id_factory must return a normalized non-empty string")
        return value


SessionManager = ExecutionSessionManager


__all__ = [
    "ExecutionHistoryEntry",
    "ExecutionSession",
    "ExecutionSessionManager",
    "SessionManager",
    "SessionStatus",
]
