"""Approval lifecycle coordination for safe execution planning."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Protocol

from Core.execution import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    TrustedExecutionGateway,
)
from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import (
    ApprovalExpiredError,
    ApprovalNotFoundError,
    DuplicateApprovalError,
    GatewayAuthorizationError,
    InvalidApprovalError,
)
from .models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalToken,
    new_id,
    utc_now,
)
from .queue import EventPublisher, ExecutionQueue


class GatewayAuthorizer(Protocol):
    """The non-executing portion of the trusted gateway contract."""

    def authorize(self, request: ExecutionRequest) -> ExecutionResult:
        """Return a trust decision without dispatching the request."""


class ApprovalManager:
    """Manage approval requests, responses, and tokens without execution."""

    EXECUTION_REQUESTED_EVENT = "execution.requested"
    EXECUTION_APPROVED_EVENT = "execution.approved"
    EXECUTION_DENIED_EVENT = "execution.denied"
    EXECUTION_CANCELLED_EVENT = "execution.cancelled"

    def __init__(
        self,
        gateway: GatewayAuthorizer | None = None,
        *,
        queue: ExecutionQueue | None = None,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
        request_ttl: timedelta = timedelta(minutes=5),
        token_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        """Initialize all collaborators through dependency injection.

        Only ``gateway.authorize`` is used.  The gateway's ``execute`` method
        is deliberately outside the structural contract accepted here.
        """

        self._logger = logger or NullLogger("narvis.execution.session.approval")
        self._event_bus = event_bus
        self._clock = clock
        self._id_factory = id_factory
        self._request_ttl = self._validate_ttl("request_ttl", request_ttl)
        self._token_ttl = self._validate_ttl("token_ttl", token_ttl)
        self._gateway = gateway or TrustedExecutionGateway(
            logger=self._logger,
            event_bus=event_bus,
        )
        self._queue = queue or ExecutionQueue(
            event_bus=event_bus,
            logger=self._logger,
            clock=clock,
        )
        self._requests: dict[str, ApprovalRequest] = {}
        self._responses: dict[str, ApprovalResponse] = {}
        self._tokens: dict[str, ApprovalToken] = {}
        self._lock = RLock()

    @property
    def queue(self) -> ExecutionQueue:
        """Return the injected approval queue."""

        return self._queue

    @property
    def gateway(self) -> GatewayAuthorizer:
        """Return the trusted gateway authorizer."""

        return self._gateway

    def create_request(
        self,
        execution_request: ExecutionRequest,
        *,
        session_id: str,
        requested_by: str,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        requested_at: datetime | None = None,
        expires_at: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> ApprovalRequest:
        """Build, gateway-check, retain, and enqueue an approval request."""

        now = requested_at or self._now()
        if expires_at is not None and ttl is not None:
            raise ValueError("expires_at and ttl are mutually exclusive")
        lifetime = (
            self._validate_ttl("ttl", ttl) if ttl is not None else self._request_ttl
        )
        request = ApprovalRequest(
            execution_request=execution_request,
            session_id=session_id,
            requested_by=requested_by,
            description=description,
            metadata=metadata or {},
            request_id=request_id or self._make_id(),
            requested_at=now,
            expires_at=expires_at or now + lifetime,
        )
        return self.submit(request)

    def request_approval(
        self,
        execution_request: ExecutionRequest,
        *,
        session_id: str,
        requested_by: str,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> ApprovalRequest:
        """Compatibility alias for :meth:`create_request`."""

        return self.create_request(
            execution_request,
            session_id=session_id,
            requested_by=requested_by,
            description=description,
            metadata=metadata,
            expires_at=expires_at,
            ttl=ttl,
        )

    def submit(self, request: ApprovalRequest) -> ApprovalRequest:
        """Validate a prebuilt request through the gateway and enqueue it."""

        if not isinstance(request, ApprovalRequest):
            raise TypeError("submit requires an ApprovalRequest")
        if request.status is not ApprovalStatus.PENDING:
            raise InvalidApprovalError(
                "only pending approval requests may be submitted"
            )
        now = self._now()
        if now >= request.expires_at:
            self._log_invalid(request.request_id, "approval request already expired")
            raise ApprovalExpiredError("approval request has already expired")

        with self._lock:
            if request.request_id in self._requests:
                self._log_invalid(request.request_id, "duplicate approval request")
                raise DuplicateApprovalError(
                    f"approval request '{request.request_id}' already exists"
                )

            gateway_result = self._authorize_safely(request.execution_request)
            checked = replace(
                request,
                gateway_status=gateway_result.status,
                gateway_reason_code=gateway_result.reason_code,
            )
            self._queue.enqueue(checked)
            self._requests[checked.request_id] = checked
            self._log_approval(checked, "requested", level=LogLevel.INFO)
            self._publish_request(self.EXECUTION_REQUESTED_EVENT, checked)
            return checked

    def respond(self, response: ApprovalResponse) -> ApprovalResponse:
        """Apply one terminal approval decision and optionally issue a token."""

        if not isinstance(response, ApprovalResponse):
            raise TypeError("respond requires an ApprovalResponse")

        with self._lock:
            request = self._requests.get(response.request_id)
            if request is None:
                self._log_invalid(response.request_id, "approval request not found")
                raise ApprovalNotFoundError(
                    f"approval request '{response.request_id}' was not found"
                )
            now = self._now()
            if request.status is not ApprovalStatus.PENDING:
                self._log_invalid(response.request_id, "duplicate approval response")
                raise DuplicateApprovalError(
                    f"approval request '{response.request_id}' is already "
                    f"{request.status.value}"
                )
            if (
                response.responded_at < request.requested_at
                or response.responded_at > now
            ):
                self._log_invalid(response.request_id, "invalid approval response time")
                raise InvalidApprovalError(
                    "responded_at must be between the request time and current time"
                )
            if now >= request.expires_at or response.responded_at >= request.expires_at:
                self._expire_locked(request, now=now)
                raise ApprovalExpiredError(
                    f"approval request '{response.request_id}' has expired"
                )
            if response.token is not None:
                self._log_invalid(response.request_id, "caller supplied approval token")
                raise InvalidApprovalError(
                    "approval tokens are issued only by ApprovalManager"
                )

            completed = response
            if response.decision is ApprovalDecision.APPROVE:
                token_expiry = min(request.expires_at, now + self._token_ttl)
                token = ApprovalToken(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    issued_to=response.responded_by,
                    token_id=self._make_id(),
                    issued_at=now,
                    expires_at=token_expiry,
                )
                completed = replace(response, token=token)
                self._tokens[token.token_id] = token

            status = completed.status
            finalized_request = replace(request, status=status)
            self._requests[request.request_id] = finalized_request
            self._responses[request.request_id] = completed
            if self._queue.contains(request.request_id):
                self._queue.remove(request.request_id)

            if status is ApprovalStatus.APPROVED:
                event_name = self.EXECUTION_APPROVED_EVENT
                level = LogLevel.INFO
                outcome = "approved"
            else:
                event_name = self.EXECUTION_DENIED_EVENT
                level = LogLevel.WARNING
                outcome = "denied"
            self._log_approval(finalized_request, outcome, level=level)
            self._publish_request(
                event_name,
                finalized_request,
                responded_by=completed.responded_by,
                reason=completed.reason,
                token_issued=completed.token is not None,
            )
            return completed

    def approve(
        self,
        request_id: str,
        *,
        responded_by: str,
        reason: str = "",
        responded_at: datetime | None = None,
    ) -> ApprovalResponse:
        """Approve a pending request using a concise convenience API."""

        return self.respond(
            ApprovalResponse(
                request_id=request_id,
                decision=ApprovalDecision.APPROVE,
                responded_by=responded_by,
                reason=reason,
                responded_at=responded_at or self._now(),
            )
        )

    def deny(
        self,
        request_id: str,
        *,
        responded_by: str,
        reason: str = "",
        responded_at: datetime | None = None,
    ) -> ApprovalResponse:
        """Deny a pending request using a concise convenience API."""

        return self.respond(
            ApprovalResponse(
                request_id=request_id,
                decision=ApprovalDecision.DENY,
                responded_by=responded_by,
                reason=reason,
                responded_at=responded_at or self._now(),
            )
        )

    def cancel(self, request_id: str, *, reason: str = "cancelled") -> ApprovalRequest:
        """Cancel a pending approval request without issuing a response token."""

        with self._lock:
            request = self._require_request(request_id)
            if request.status is not ApprovalStatus.PENDING:
                self._log_invalid(request_id, "duplicate approval cancellation")
                raise DuplicateApprovalError(
                    f"approval request '{request_id}' is already {request.status.value}"
                )
            if self._queue.contains(request_id):
                cancelled = self._queue.cancel(request_id, reason=reason)
            else:
                cancelled = replace(request, status=ApprovalStatus.CANCELLED)
                self._publish_request(
                    self.EXECUTION_CANCELLED_EVENT,
                    cancelled,
                    reason=reason,
                )
                self._log_approval(cancelled, "cancelled", level=LogLevel.INFO)
            self._requests[request_id] = cancelled
            return cancelled

    def expire(self, request_id: str, *, at: datetime | None = None) -> ApprovalRequest:
        """Mark a pending request expired when its deadline has elapsed."""

        with self._lock:
            request = self._require_request(request_id)
            now = at or self._now()
            if now < request.expires_at:
                raise InvalidApprovalError("approval request has not expired")
            if request.status is not ApprovalStatus.PENDING:
                raise DuplicateApprovalError(
                    f"approval request '{request_id}' is already {request.status.value}"
                )
            return self._expire_locked(request, now=now)

    def expire_pending(
        self, *, at: datetime | None = None
    ) -> tuple[ApprovalRequest, ...]:
        """Expire every pending request whose deadline has elapsed."""

        with self._lock:
            now = at or self._now()
            expired = []
            for request in tuple(self._requests.values()):
                if (
                    request.status is ApprovalStatus.PENDING
                    and now >= request.expires_at
                ):
                    expired.append(self._expire_locked(request, now=now))
            return tuple(expired)

    def validate_token(
        self,
        token: ApprovalToken | ApprovalResponse,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        at: datetime | None = None,
    ) -> bool:
        """Return whether a manager-issued token has exact, unexpired bindings."""

        if isinstance(token, ApprovalResponse):
            if token.token is None:
                return False
            token = token.token
        if not isinstance(token, ApprovalToken):
            return False
        with self._lock:
            stored = self._tokens.get(token.token_id)
            request = self._requests.get(token.request_id)
            now = at or self._now()
            return bool(
                stored == token
                and request is not None
                and request.status is ApprovalStatus.APPROVED
                and token.request_id == request.request_id
                and token.session_id == request.session_id
                and (request_id is None or token.request_id == request_id)
                and (session_id is None or token.session_id == session_id)
                and not token.is_expired(now)
            )

    def require_valid_token(
        self,
        token: ApprovalToken | ApprovalResponse,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        at: datetime | None = None,
    ) -> ApprovalToken:
        """Return a valid token or raise a typed fail-closed error."""

        resolved = token.token if isinstance(token, ApprovalResponse) else token
        if not isinstance(resolved, ApprovalToken):
            raise InvalidApprovalError("an issued ApprovalToken is required")
        if not self.validate_token(
            resolved,
            request_id=request_id,
            session_id=session_id,
            at=at,
        ):
            evaluated_at = at or self._now()
            if resolved.is_expired(evaluated_at):
                raise ApprovalExpiredError("approval token has expired")
            raise InvalidApprovalError("approval token is invalid or incorrectly bound")
        return resolved

    def get_request(
        self, request_id: str, *, at: datetime | None = None
    ) -> ApprovalRequest:
        """Return one retained request, applying deadline expiration if needed."""

        with self._lock:
            request = self._require_request(request_id)
            now = at or self._now()
            if request.status is ApprovalStatus.PENDING and now >= request.expires_at:
                request = self._expire_locked(request, now=now)
            return request

    def get_response(self, request_id: str) -> ApprovalResponse | None:
        """Return the retained response for a completed request, if any."""

        with self._lock:
            self._require_request(request_id)
            return self._responses.get(request_id)

    def get_token(self, token_id: str) -> ApprovalToken | None:
        """Return one retained token without validating its current expiry."""

        with self._lock:
            return self._tokens.get(token_id)

    def status(self, request_id: str, *, at: datetime | None = None) -> ApprovalStatus:
        """Return the current lifecycle status for one request."""

        return self.get_request(request_id, at=at).status

    def pending(self, *, at: datetime | None = None) -> tuple[ApprovalRequest, ...]:
        """Return all currently pending requests in queue order."""

        self.expire_pending(at=at)
        with self._lock:
            ids = self._queue.status().request_ids
            return tuple(self._requests[request_id] for request_id in ids)

    def _authorize_safely(self, request: ExecutionRequest) -> ExecutionResult:
        """Call only gateway authorization and validate the inert result."""

        try:
            result = self._gateway.authorize(request)
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Trusted gateway authorization failed",
                execution_request_id=request.request_id,
                action=request.action,
                error_type=type(error).__name__,
                executed=False,
            )
            raise GatewayAuthorizationError(
                "trusted gateway authorization failed closed"
            ) from error
        if not isinstance(result, ExecutionResult):
            raise GatewayAuthorizationError(
                "trusted gateway returned an invalid authorization result"
            )
        if (
            result.request_id != request.request_id
            or result.action != request.action
            or result.executed is not False
            or result.dispatcher_invoked is not False
        ):
            raise GatewayAuthorizationError(
                "trusted gateway result has unsafe or inconsistent bindings"
            )
        if result.status not in {ExecutionStatus.PENDING, ExecutionStatus.AUTHORIZED}:
            raise GatewayAuthorizationError(
                f"trusted gateway did not permit approval: {result.status.value}"
            )
        return result

    def _expire_locked(
        self, request: ApprovalRequest, *, now: datetime
    ) -> ApprovalRequest:
        """Apply one expiration transition while the manager lock is held."""

        if now < request.expires_at:
            raise InvalidApprovalError("approval request has not expired")
        expired = replace(request, status=ApprovalStatus.EXPIRED)
        self._requests[request.request_id] = expired
        if self._queue.contains(request.request_id):
            self._queue.remove(request.request_id)
        self._log_approval(expired, "expired", level=LogLevel.WARNING)
        self._publish_request(
            self.EXECUTION_CANCELLED_EVENT,
            expired,
            reason="approval_expired",
        )
        return expired

    def _require_request(self, request_id: str) -> ApprovalRequest:
        """Return one retained request or raise a typed lookup error."""

        if not isinstance(request_id, str) or not request_id:
            raise ApprovalNotFoundError("a non-empty request_id is required")
        try:
            return self._requests[request_id]
        except KeyError as error:
            raise ApprovalNotFoundError(
                f"approval request '{request_id}' was not found"
            ) from error

    def _publish_request(
        self,
        event_name: str,
        request: ApprovalRequest,
        **extra: object,
    ) -> None:
        """Publish a non-sensitive approval event."""

        payload: dict[str, object] = {
            "request_id": request.request_id,
            "execution_request_id": request.execution_request_id,
            "session_id": request.session_id,
            "action": request.action,
            "status": request.status.value,
            "gateway_status": (
                request.gateway_status.value
                if request.gateway_status is not None
                else ""
            ),
            "executed": False,
            "dispatcher_invoked": False,
        }
        payload.update(extra)
        self._publish(event_name, payload)

    def _publish(self, name: str, payload: dict[str, object]) -> None:
        """Publish without allowing observer failures to change approval state."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish safe execution approval event",
                event_name=name,
                error_type=type(error).__name__,
            )

    def _log_approval(
        self,
        request: ApprovalRequest,
        outcome: str,
        *,
        level: LogLevel,
    ) -> None:
        """Log every successfully applied approval lifecycle event."""

        self._log(
            level,
            f"Execution approval {outcome}",
            request_id=request.request_id,
            execution_request_id=request.execution_request_id,
            session_id=request.session_id,
            action=request.action,
            approval_status=request.status.value,
            executed=False,
            dispatcher_invoked=False,
        )

    def _log_invalid(self, request_id: str, reason: str) -> None:
        """Log rejected approval activity for auditability."""

        self._log(
            LogLevel.WARNING,
            "Invalid execution approval event rejected",
            request_id=request_id,
            reason=reason,
            executed=False,
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit structured logging without altering approval control flow."""

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

    @staticmethod
    def _validate_ttl(name: str, value: timedelta) -> timedelta:
        """Require a strictly positive duration."""

        if not isinstance(value, timedelta) or value <= timedelta(0):
            raise ValueError(f"{name} must be a positive timedelta")
        return value


ApprovalService = ApprovalManager


__all__ = [
    "ApprovalDecision",
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalService",
    "ApprovalStatus",
    "ApprovalToken",
    "GatewayAuthorizer",
]
