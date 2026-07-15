"""Thread-safe lifecycle coordination for AI orchestration sessions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from AI.core.models import new_id, utc_now
from Core.logger import LogLevel, Logger, NullLogger

from .events import (
    AI_SESSION_COMPLETED_EVENT,
    AI_SESSION_CREATED_EVENT,
    OrchestrationEvents,
)
from .exceptions import (
    DuplicatePlanError,
    OrchestrationValidationError,
    SessionExpiredError,
    SessionInactiveError,
)
from .models import (
    OrchestrationPlan,
    OrchestrationSession,
    OrchestrationSessionStatus,
    OrchestrationSummary,
    ProviderSelectionRecord,
)
from .session import OrchestrationSessionStore


class OrchestrationLifecycleManager:
    """Coordinate immutable session creation, history, expiration, and completion."""

    def __init__(
        self,
        session_store: OrchestrationSessionStore | None = None,
        events: OrchestrationEvents | None = None,
        *,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
        default_ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        resolved_store = (
            session_store if session_store is not None else OrchestrationSessionStore()
        )
        if not all(
            callable(getattr(resolved_store, method, None))
            for method in ("add", "get", "replace", "list")
        ):
            raise TypeError("session_store does not implement the session contract")
        resolved_events = events if events is not None else OrchestrationEvents()
        if not callable(getattr(resolved_events, "publish", None)):
            raise TypeError("events must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        if not isinstance(default_ttl, timedelta) or default_ttl <= timedelta(0):
            raise ValueError("default_ttl must be a positive timedelta")
        self._store = resolved_store
        self._events = resolved_events
        self._logger = (
            logger if logger is not None else NullLogger("narvis.ai.lifecycle")
        )
        self._clock = clock
        self._id_factory = id_factory
        self._default_ttl = default_ttl
        self._lock = RLock()

    @property
    def session_store(self) -> OrchestrationSessionStore:
        return self._store

    def create_session(
        self,
        owner_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        ttl: timedelta | None = None,
        expires_at: datetime | None = None,
        session_id: str | None = None,
    ) -> OrchestrationSession:
        """Create and retain one immutable active orchestration session."""

        if (
            not isinstance(owner_id, str)
            or not owner_id
            or owner_id != owner_id.strip()
        ):
            raise OrchestrationValidationError(
                "owner_id must be normalized non-empty text"
            )
        if ttl is not None and expires_at is not None:
            raise OrchestrationValidationError("provide ttl or expires_at, not both")
        if ttl is not None and (not isinstance(ttl, timedelta) or ttl <= timedelta(0)):
            raise OrchestrationValidationError("ttl must be a positive timedelta")
        now = self._now()
        expiry = expires_at or (now + (ttl or self._default_ttl))
        if not isinstance(expiry, datetime) or expiry.tzinfo is None or expiry <= now:
            raise OrchestrationValidationError(
                "expires_at must be an aware future datetime"
            )
        identifier = session_id if session_id is not None else self._new_id()
        session = OrchestrationSession(
            session_id=identifier,
            owner_id=owner_id,
            created_at=now,
            expires_at=expiry,
            updated_at=now,
            metadata={} if metadata is None else metadata,
        )
        with self._lock:
            self._store.add(session)
        self._log(
            LogLevel.INFO,
            "AI orchestration session created",
            session_id=session.session_id,
            owner_id=session.owner_id,
            expires_at=session.expires_at.isoformat(),
        )
        self._events.publish(
            AI_SESSION_CREATED_EVENT,
            session_id=session.session_id,
            owner_id=session.owner_id,
            expires_at=session.expires_at.isoformat(),
            status=session.status.value,
        )
        return session

    create = create_session

    def get_session(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> OrchestrationSession:
        """Return a session, materializing expiration when required."""

        with self._lock:
            session = self._store.get(session_id)
            now = self._at(at)
            if session.active and now >= session.expires_at:
                session = replace(
                    session,
                    status=OrchestrationSessionStatus.EXPIRED,
                    updated_at=max(now, session.updated_at),
                    completed_at=now,
                )
                self._store.replace(session)
                self._log(
                    LogLevel.INFO,
                    "AI orchestration session expired",
                    session_id=session.session_id,
                )
            return session

    get = get_session

    def record_plan(
        self,
        session_id: str,
        plan: OrchestrationPlan,
        *,
        at: datetime | None = None,
    ) -> OrchestrationSession:
        """Append a plan and provider selection to immutable session history."""

        if not isinstance(plan, OrchestrationPlan):
            raise TypeError("plan must be an OrchestrationPlan")
        if plan.session_id != session_id:
            raise OrchestrationValidationError("plan belongs to a different session")
        with self._lock:
            now = self._at(at)
            session = self._require_active(session_id, at=now)
            if plan.plan_id in session.plan_ids:
                raise DuplicatePlanError(f"plan '{plan.plan_id}' is already recorded")
            if plan.request_id in session.request_ids:
                raise DuplicatePlanError(
                    f"request '{plan.request_id}' is already planned"
                )
            try:
                score = next(
                    item
                    for item in plan.negotiation.routing_decision.provider_scores
                    if item.provider_id == plan.provider_id
                )
            except StopIteration as error:
                raise OrchestrationValidationError(
                    "negotiated provider is absent from routing scores"
                ) from error
            record = ProviderSelectionRecord(
                session_id=session_id,
                plan_id=plan.plan_id,
                request_id=plan.request_id,
                provider_id=plan.provider_id,
                model_name=plan.model_name,
                routing_decision_id=plan.negotiation.routing_decision.decision_id,
                score=score.total,
                cost=plan.negotiation.cost,
                latency=plan.negotiation.latency,
                context_size=plan.negotiation.context_size,
                selected_at=max(now, plan.created_at),
            )
            updated = replace(
                session,
                updated_at=max(now, plan.created_at, session.updated_at),
                request_ids=(*session.request_ids, plan.request_id),
                plan_ids=(*session.plan_ids, plan.plan_id),
                provider_selection_history=(
                    *session.provider_selection_history,
                    record,
                ),
            )
            self._store.replace(updated)
            return updated

    def complete_session(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> OrchestrationSession:
        """Complete an active session without executing any retained plan."""

        with self._lock:
            now = self._at(at)
            session = self._require_active(session_id, at=now)
            completed = replace(
                session,
                status=OrchestrationSessionStatus.COMPLETED,
                updated_at=max(now, session.updated_at),
                completed_at=now,
            )
            self._store.replace(completed)
        self._log(
            LogLevel.INFO,
            "AI orchestration session completed",
            session_id=completed.session_id,
            plan_count=len(completed.plan_ids),
            executed=False,
        )
        self._events.publish(
            AI_SESSION_COMPLETED_EVENT,
            session_id=completed.session_id,
            status=completed.status.value,
            request_count=len(completed.request_ids),
            plan_count=len(completed.plan_ids),
            selection_count=len(completed.provider_selection_history),
            executed=False,
        )
        return completed

    complete = complete_session

    def cancel_session(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> OrchestrationSession:
        """Cancel an active planning session without affecting providers."""

        with self._lock:
            now = self._at(at)
            session = self._require_active(session_id, at=now)
            cancelled = replace(
                session,
                status=OrchestrationSessionStatus.CANCELLED,
                updated_at=max(now, session.updated_at),
                completed_at=now,
            )
            self._store.replace(cancelled)
            return cancelled

    def list_sessions(
        self,
        *,
        at: datetime | None = None,
    ) -> tuple[OrchestrationSession, ...]:
        """Return deterministic session snapshots with expiration applied."""

        now = self._at(at)
        with self._lock:
            for session in self._store.list():
                if session.active and now >= session.expires_at:
                    self.get_session(session.session_id, at=now)
            return self._store.list()

    def selection_history(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> tuple[ProviderSelectionRecord, ...]:
        """Return immutable provider selection history for one session."""

        return self.get_session(session_id, at=at).provider_selection_history

    def summary(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> OrchestrationSummary:
        """Generate structured cost, latency, context, and selection facts."""

        session = self.get_session(session_id, at=at)
        history = session.provider_selection_history
        counts = dict(Counter(item.provider_id for item in history))
        known_costs = tuple(
            (item.cost.currency, item.cost.estimated_request_cost)
            for item in history
            if item.cost.estimated_request_cost is not None
        )
        currencies = {currency for currency, _ in known_costs}
        total_cost: float | None = None
        cost_currency: str | None = None
        if known_costs and len(currencies) == 1:
            cost_currency = next(iter(currencies))
            total_cost = round(
                sum(value for _, value in known_costs if value is not None), 8
            )
        latencies = tuple(
            item.latency.estimated_latency_ms
            for item in history
            if item.latency.estimated_latency_ms is not None
        )
        average_latency = (
            round(sum(latencies) / len(latencies), 6) if latencies else None
        )
        contexts = tuple(
            item.context_size.max_context_tokens
            for item in history
            if item.context_size.max_context_tokens is not None
        )
        last = history[-1] if history else None
        return OrchestrationSummary(
            session_id=session.session_id,
            status=session.status,
            request_count=len(session.request_ids),
            plan_count=len(session.plan_ids),
            selection_count=len(history),
            provider_selection_counts=counts,
            total_estimated_cost=total_cost,
            cost_currency=cost_currency,
            average_estimated_latency_ms=average_latency,
            maximum_context_tokens=max(contexts) if contexts else None,
            last_provider_id=None if last is None else last.provider_id,
            last_model_name=None if last is None else last.model_name,
            generated_at=self._at(at),
        )

    orchestration_summary = summary

    def _require_active(
        self,
        session_id: str,
        *,
        at: datetime,
    ) -> OrchestrationSession:
        session = self.get_session(session_id, at=at)
        if session.status is OrchestrationSessionStatus.EXPIRED:
            raise SessionExpiredError(
                f"orchestration session '{session_id}' is expired"
            )
        if not session.active:
            raise SessionInactiveError(
                f"orchestration session '{session_id}' is {session.status.value}"
            )
        return session

    def _at(self, value: datetime | None) -> datetime:
        if value is None:
            return self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise OrchestrationValidationError("at must be a timezone-aware datetime")
        return value

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise OrchestrationValidationError(
                "clock must return a timezone-aware datetime"
            )
        return value

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise OrchestrationValidationError(
                "id_factory must return a normalized non-empty string"
            )
        return value

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


LifecycleManager = OrchestrationLifecycleManager


__all__ = ["LifecycleManager", "OrchestrationLifecycleManager"]
