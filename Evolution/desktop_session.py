"""Standalone immutable desktop-session lifecycle for Phase 11."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .execution_validator import ExecutionValidationReason, ExecutionValidationResult
from .models import compact_text, stable_id
from .trusted_execution_gateway import (
    TrustedExecutionDecision,
    TrustedExecutionDecisionType,
)


class DesktopSessionStatus(str, Enum):
    """The closed lifecycle states for one desktop session."""

    ACTIVE = "active"
    ENDED = "ended"
    TIMED_OUT = "timed_out"


class DesktopSessionOperation(str, Enum):
    """The lifecycle operations that can emit a session decision."""

    BEGIN = "begin"
    END = "end"
    VALIDATE_OWNERSHIP = "validate_ownership"


class DesktopSessionDecisionType(str, Enum):
    """The only lifecycle decisions emitted by the session service."""

    ALLOW = "ALLOW"
    DENY = "DENY"


class DesktopSessionReason(str, Enum):
    """Stable typed reasons for desktop-session lifecycle decisions."""

    SESSION_STARTED = "session_started"
    SESSION_ALREADY_ACTIVE = "session_already_active"
    SESSION_ENDED = "session_ended"
    SESSION_OWNER_VALID = "session_owner_valid"
    INVALID_REQUEST = "invalid_request"
    OWNER_REQUIRED = "owner_required"
    SNAPSHOT_REQUIRED = "snapshot_required"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_TIMEOUT = "invalid_timeout"
    TRUSTED_AUTHORIZATION_REQUIRED = "trusted_authorization_required"
    TRUSTED_AUTHORIZATION_DENIED = "trusted_authorization_denied"
    TRUSTED_AUTHORIZATION_INVALID = "trusted_authorization_invalid"
    UNSUPPORTED_ACTION_CATEGORY = "unsupported_action_category"
    SNAPSHOT_BINDING_MISMATCH = "snapshot_binding_mismatch"
    SESSION_ALREADY_EXISTS = "session_already_exists"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_OWNER_MISMATCH = "session_owner_mismatch"
    SESSION_NOT_ACTIVE = "session_not_active"
    SESSION_TIMED_OUT = "session_timed_out"


@dataclass(slots=True, frozen=True)
class DesktopSession:
    """One immutable gateway-bound desktop session record."""

    session_id: str
    authorization_binding_id: str
    owner_id: str
    snapshot_id: str
    action_id: str
    mutation_approval_id: str
    recovery_outcome_id: str
    mutation_target_ids: tuple[str, ...]
    started_at: datetime
    expires_at: datetime
    status: DesktopSessionStatus = DesktopSessionStatus.ACTIVE
    ended_at: datetime | None = None
    end_reason: str = ""

    @property
    def active(self) -> bool:
        """Return True only while this immutable record is in the active state."""

        return self.status is DesktopSessionStatus.ACTIVE


@dataclass(slots=True, frozen=True)
class DesktopSessionBeginRequest:
    """One typed request to begin a non-executing desktop session."""

    authorization: TrustedExecutionDecision
    owner_id: str
    snapshot_id: str
    started_at: datetime
    timeout_seconds: int


@dataclass(slots=True, frozen=True)
class DesktopSessionEndRequest:
    """One typed owner-bound request to end an active desktop session."""

    session_id: str
    owner_id: str
    ended_at: datetime


@dataclass(slots=True, frozen=True)
class DesktopSessionOwnershipRequest:
    """One typed request to validate active ownership at an explicit time."""

    session_id: str
    owner_id: str
    evaluated_at: datetime


@dataclass(slots=True, frozen=True)
class DesktopSessionDecision:
    """One immutable typed session lifecycle decision."""

    operation: DesktopSessionOperation
    decision: DesktopSessionDecisionType
    reason: DesktopSessionReason
    detail: str
    session_id: str = ""
    session: DesktopSession | None = None

    @property
    def allowed(self) -> bool:
        """Return True only for an explicit lifecycle ALLOW decision."""

        return self.decision is DesktopSessionDecisionType.ALLOW

    @property
    def reason_code(self) -> str:
        """Return the stable machine-readable lifecycle reason."""

        return self.reason.value


_DESKTOP_ACTION_NAMESPACES = frozenset(
    {"desktop", "keyboard", "mouse", "clipboard", "vision", "system"}
)


def _normalized_text(value: Any, *, max_chars: int = 120) -> str:
    """Normalize one bounded identity without interpreting it as an instruction."""

    return compact_text(value if isinstance(value, str) else "", max_chars=max_chars)


def _normalized_timestamp(value: Any) -> datetime | None:
    """Normalize an explicit timestamp without consulting the host clock."""

    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DesktopSessionService:
    """Manage gateway-bound desktop session records without executing actions."""

    def __init__(self) -> None:
        self._sessions: dict[str, DesktopSession] = {}

    def begin_session(self, request: DesktopSessionBeginRequest) -> DesktopSessionDecision:
        """Begin one deterministic immutable session after trusted authorization."""

        if not isinstance(request, DesktopSessionBeginRequest):
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.INVALID_REQUEST,
                "Desktop sessions require one typed DesktopSessionBeginRequest.",
            )

        authorization_error = self._validate_authorization(request.authorization)
        if authorization_error is not None:
            reason, detail = authorization_error
            return self._deny(DesktopSessionOperation.BEGIN, reason, detail)

        owner_id = _normalized_text(request.owner_id)
        if not owner_id:
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.OWNER_REQUIRED,
                "Desktop sessions require one explicit owner identity.",
            )
        snapshot_id = _normalized_text(request.snapshot_id)
        if not snapshot_id:
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.SNAPSHOT_REQUIRED,
                "Desktop sessions require one explicit execution-context snapshot identifier.",
            )
        if snapshot_id != request.authorization.context_snapshot_id:
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.SNAPSHOT_BINDING_MISMATCH,
                "The desktop session snapshot must exactly match the trusted gateway authorization.",
            )

        started_at = _normalized_timestamp(request.started_at)
        if started_at is None:
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.INVALID_TIMESTAMP,
                "Desktop sessions require one explicit valid start timestamp.",
            )
        if (
            not isinstance(request.timeout_seconds, int)
            or isinstance(request.timeout_seconds, bool)
            or request.timeout_seconds <= 0
        ):
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.INVALID_TIMEOUT,
                "Desktop session timeouts must be positive whole seconds.",
            )
        try:
            expires_at = started_at + timedelta(seconds=request.timeout_seconds)
        except OverflowError:
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.INVALID_TIMEOUT,
                "The desktop session timeout exceeds the supported timestamp range.",
            )

        authorization_binding_id = self._authorization_binding_id(request.authorization)
        session_id = stable_id(
            "desktop_session",
            owner_id,
            snapshot_id,
            authorization_binding_id,
            started_at.isoformat(),
            expires_at.isoformat(),
        )
        session = DesktopSession(
            session_id=session_id,
            authorization_binding_id=authorization_binding_id,
            owner_id=owner_id,
            snapshot_id=snapshot_id,
            action_id=request.authorization.action_id,
            mutation_approval_id=request.authorization.mutation_approval_id,
            recovery_outcome_id=request.authorization.recovery_outcome_id,
            mutation_target_ids=request.authorization.mutation_target_ids,
            started_at=started_at,
            expires_at=expires_at,
        )
        existing = self._sessions.get(session_id)
        if existing is not None:
            if existing == session:
                return self._allow(
                    DesktopSessionOperation.BEGIN,
                    DesktopSessionReason.SESSION_ALREADY_ACTIVE,
                    "The exact deterministic desktop session is already active.",
                    existing,
                )
            return self._deny(
                DesktopSessionOperation.BEGIN,
                DesktopSessionReason.SESSION_ALREADY_EXISTS,
                "The deterministic desktop session identifier is already retained.",
                session_id=session_id,
                session=existing,
            )

        self._sessions[session_id] = session
        return self._allow(
            DesktopSessionOperation.BEGIN,
            DesktopSessionReason.SESSION_STARTED,
            "The authorized desktop session lifecycle record was created without execution.",
            session,
        )

    def end_session(self, request: DesktopSessionEndRequest) -> DesktopSessionDecision:
        """End one active session after exact owner validation."""

        if not isinstance(request, DesktopSessionEndRequest):
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.INVALID_REQUEST,
                "Ending a desktop session requires one typed DesktopSessionEndRequest.",
            )
        session_id = _normalized_text(request.session_id)
        owner_id = _normalized_text(request.owner_id)
        ended_at = _normalized_timestamp(request.ended_at)
        if not session_id or not owner_id or ended_at is None:
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.INVALID_REQUEST,
                "Ending a desktop session requires session, owner, and timestamp bindings.",
                session_id=session_id,
            )
        session = self._sessions.get(session_id)
        if session is None:
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.SESSION_NOT_FOUND,
                "No retained desktop session matches the supplied identifier.",
                session_id=session_id,
            )
        if owner_id != session.owner_id:
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.SESSION_OWNER_MISMATCH,
                "Only the exact active desktop session owner may end the session.",
                session_id=session_id,
            )
        if ended_at < session.started_at:
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.INVALID_TIMESTAMP,
                "A desktop session cannot end before its explicit start timestamp.",
                session_id=session_id,
                session=session,
            )

        session = self._apply_timeout(session, ended_at)
        if session.status is DesktopSessionStatus.TIMED_OUT:
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.SESSION_TIMED_OUT,
                "The desktop session timed out before the requested end transition.",
                session_id=session_id,
                session=session,
            )
        if session.status is not DesktopSessionStatus.ACTIVE:
            return self._deny(
                DesktopSessionOperation.END,
                DesktopSessionReason.SESSION_NOT_ACTIVE,
                "Only an active desktop session may transition to ended.",
                session_id=session_id,
                session=session,
            )

        ended_session = replace(
            session,
            status=DesktopSessionStatus.ENDED,
            ended_at=ended_at,
            end_reason="ended_by_owner",
        )
        self._sessions[session_id] = ended_session
        return self._allow(
            DesktopSessionOperation.END,
            DesktopSessionReason.SESSION_ENDED,
            "The desktop session lifecycle ended without invoking any action.",
            ended_session,
        )

    def lookup_session(
        self,
        session_id: str,
        *,
        evaluated_at: datetime | None = None,
    ) -> DesktopSession | None:
        """Look up one session and optionally apply timeout at an explicit timestamp."""

        normalized_session_id = _normalized_text(session_id)
        session = self._sessions.get(normalized_session_id)
        if session is None or evaluated_at is None:
            return session
        timestamp = _normalized_timestamp(evaluated_at)
        if timestamp is None or timestamp < session.started_at:
            return None
        return self._apply_timeout(session, timestamp)

    def list_sessions(
        self,
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[DesktopSession, ...]:
        """Return retained immutable sessions in deterministic identifier order."""

        if evaluated_at is not None:
            timestamp = _normalized_timestamp(evaluated_at)
            if timestamp is None:
                return ()
            for session in tuple(self._sessions.values()):
                if timestamp >= session.started_at:
                    self._apply_timeout(session, timestamp)
        return tuple(sorted(self._sessions.values(), key=lambda session: session.session_id))

    def validate_active_session_ownership(
        self,
        request: DesktopSessionOwnershipRequest,
    ) -> DesktopSessionDecision:
        """Validate exact ownership of one active, non-expired session."""

        if not isinstance(request, DesktopSessionOwnershipRequest):
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.INVALID_REQUEST,
                "Ownership validation requires one typed DesktopSessionOwnershipRequest.",
            )
        session_id = _normalized_text(request.session_id)
        owner_id = _normalized_text(request.owner_id)
        evaluated_at = _normalized_timestamp(request.evaluated_at)
        if not session_id or not owner_id or evaluated_at is None:
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.INVALID_REQUEST,
                "Ownership validation requires session, owner, and timestamp bindings.",
                session_id=session_id,
            )
        session = self._sessions.get(session_id)
        if session is None:
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.SESSION_NOT_FOUND,
                "No retained desktop session matches the supplied identifier.",
                session_id=session_id,
            )
        if owner_id != session.owner_id:
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.SESSION_OWNER_MISMATCH,
                "The supplied owner does not match the desktop session owner.",
                session_id=session_id,
            )
        if evaluated_at < session.started_at:
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.INVALID_TIMESTAMP,
                "Ownership cannot be validated before the desktop session start timestamp.",
                session_id=session_id,
                session=session,
            )

        session = self._apply_timeout(session, evaluated_at)
        if session.status is DesktopSessionStatus.TIMED_OUT:
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.SESSION_TIMED_OUT,
                "The desktop session is no longer active because its timeout elapsed.",
                session_id=session_id,
                session=session,
            )
        if session.status is not DesktopSessionStatus.ACTIVE:
            return self._deny(
                DesktopSessionOperation.VALIDATE_OWNERSHIP,
                DesktopSessionReason.SESSION_NOT_ACTIVE,
                "Ownership is valid only while the desktop session remains active.",
                session_id=session_id,
                session=session,
            )
        return self._allow(
            DesktopSessionOperation.VALIDATE_OWNERSHIP,
            DesktopSessionReason.SESSION_OWNER_VALID,
            "The supplied owner exactly owns the active desktop session.",
            session,
        )

    def _validate_authorization(
        self,
        authorization: TrustedExecutionDecision,
    ) -> tuple[DesktopSessionReason, str] | None:
        """Require one complete typed gateway ALLOW decision without reauthorizing it."""

        if not isinstance(authorization, TrustedExecutionDecision):
            return (
                DesktopSessionReason.TRUSTED_AUTHORIZATION_REQUIRED,
                "Desktop sessions require one typed TrustedExecutionGateway decision.",
            )
        if (
            not authorization.allowed
            or authorization.decision is not TrustedExecutionDecisionType.ALLOW
            or authorization.reason is not ExecutionValidationReason.ALLOWED
        ):
            return (
                DesktopSessionReason.TRUSTED_AUTHORIZATION_DENIED,
                "A denied trusted gateway decision cannot begin a desktop session.",
            )
        validation = authorization.validation_result
        if not isinstance(validation, ExecutionValidationResult):
            return (
                DesktopSessionReason.TRUSTED_AUTHORIZATION_INVALID,
                "The trusted gateway decision must retain its typed validation result.",
            )
        if (
            not validation.allowed
            or validation.reason is not ExecutionValidationReason.ALLOWED
            or authorization.action_id != validation.action_id
            or authorization.context_snapshot_id != validation.context_snapshot_id
            or authorization.mutation_approval_id != validation.mutation_approval_id
            or authorization.recovery_outcome_id != validation.recovery_outcome_id
            or authorization.mutation_target_ids != validation.mutation_target_ids
            or not authorization.action_id
            or not authorization.context_snapshot_id
            or not authorization.mutation_approval_id
            or not authorization.recovery_outcome_id
            or not authorization.mutation_target_ids
        ):
            return (
                DesktopSessionReason.TRUSTED_AUTHORIZATION_INVALID,
                "The trusted gateway decision has incomplete or inconsistent exact bindings.",
            )
        namespace = authorization.action_id.partition(".")[0]
        if namespace not in _DESKTOP_ACTION_NAMESPACES:
            return (
                DesktopSessionReason.UNSUPPORTED_ACTION_CATEGORY,
                "Desktop sessions accept only trusted desktop-related action categories.",
            )
        return None

    def _authorization_binding_id(self, authorization: TrustedExecutionDecision) -> str:
        """Build one deterministic identifier for the exact gateway authorization facts."""

        return stable_id(
            "trusted_execution_binding",
            authorization.action_id,
            authorization.context_snapshot_id,
            authorization.mutation_approval_id,
            authorization.recovery_outcome_id,
            authorization.mutation_target_ids,
            authorization.reason.value,
        )

    def _apply_timeout(self, session: DesktopSession, evaluated_at: datetime) -> DesktopSession:
        """Replace one elapsed active session with an immutable timed-out record."""

        if session.status is not DesktopSessionStatus.ACTIVE or evaluated_at < session.expires_at:
            return session
        timed_out = replace(
            session,
            status=DesktopSessionStatus.TIMED_OUT,
            ended_at=session.expires_at,
            end_reason="timeout_elapsed",
        )
        self._sessions[session.session_id] = timed_out
        return timed_out

    def _allow(
        self,
        operation: DesktopSessionOperation,
        reason: DesktopSessionReason,
        detail: str,
        session: DesktopSession,
    ) -> DesktopSessionDecision:
        """Build one typed lifecycle ALLOW decision."""

        return DesktopSessionDecision(
            operation=operation,
            decision=DesktopSessionDecisionType.ALLOW,
            reason=reason,
            detail=detail,
            session_id=session.session_id,
            session=session,
        )

    def _deny(
        self,
        operation: DesktopSessionOperation,
        reason: DesktopSessionReason,
        detail: str,
        *,
        session_id: str = "",
        session: DesktopSession | None = None,
    ) -> DesktopSessionDecision:
        """Build one typed lifecycle DENY decision."""

        return DesktopSessionDecision(
            operation=operation,
            decision=DesktopSessionDecisionType.DENY,
            reason=reason,
            detail=detail,
            session_id=session_id or (session.session_id if session is not None else ""),
            session=session,
        )


__all__ = [
    "DesktopSession",
    "DesktopSessionBeginRequest",
    "DesktopSessionDecision",
    "DesktopSessionDecisionType",
    "DesktopSessionEndRequest",
    "DesktopSessionOperation",
    "DesktopSessionOwnershipRequest",
    "DesktopSessionReason",
    "DesktopSessionService",
    "DesktopSessionStatus",
]
