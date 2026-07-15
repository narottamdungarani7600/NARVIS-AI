"""Generation of immutable AI orchestration plans with no execution path."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

from AI.core.models import AIProvider, AIRequest, new_id, utc_now
from AI.routing.models import RoutingPolicy
from Core.logger import LogLevel, Logger, NullLogger

from .events import AI_PLAN_GENERATED_EVENT, OrchestrationEvents
from .exceptions import PlanGenerationError, SessionInactiveError
from .models import (
    ModelPreferencePolicy,
    OrchestrationPlan,
    OrchestrationPlanStep,
    OrchestrationSession,
    OrchestrationStepType,
)
from .negotiation import ProviderNegotiator


class OrchestrationPlanner:
    """Build an ordered architecture-only plan from negotiated metadata."""

    def __init__(
        self,
        negotiator: ProviderNegotiator,
        events: OrchestrationEvents | None = None,
        *,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        if not callable(getattr(negotiator, "negotiate", None)):
            raise TypeError("negotiator must provide a negotiate method")
        resolved_events = events if events is not None else OrchestrationEvents()
        if not callable(getattr(resolved_events, "publish", None)):
            raise TypeError("events must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._negotiator = negotiator
        self._events = resolved_events
        self._logger = logger if logger is not None else NullLogger("narvis.ai.planner")
        self._clock = clock
        self._id_factory = id_factory

    @property
    def negotiator(self) -> ProviderNegotiator:
        return self._negotiator

    def plan(
        self,
        session: OrchestrationSession,
        request: AIRequest,
        providers: Iterable[AIProvider],
        routing_policy: RoutingPolicy | None = None,
        preference_policy: ModelPreferencePolicy | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> OrchestrationPlan:
        """Generate one non-executable plan for an active session."""

        if not isinstance(session, OrchestrationSession):
            raise TypeError("session must be an OrchestrationSession")
        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        now = self._now()
        if not session.active or now >= session.expires_at:
            raise SessionInactiveError("orchestration session is not active")
        resolved_routing = routing_policy or RoutingPolicy()
        resolved_preferences = preference_policy or ModelPreferencePolicy()
        if not isinstance(resolved_routing, RoutingPolicy):
            raise TypeError("routing_policy must be a RoutingPolicy or None")
        if not isinstance(resolved_preferences, ModelPreferencePolicy):
            raise TypeError("preference_policy must be a ModelPreferencePolicy or None")
        negotiation = self._negotiator.negotiate(
            request,
            providers,
            resolved_routing,
            resolved_preferences,
        )
        steps = (
            OrchestrationPlanStep(
                order=1,
                step_type=OrchestrationStepType.VALIDATE_REQUEST,
                description="Validate immutable request and policy constraints",
            ),
            OrchestrationPlanStep(
                order=2,
                step_type=OrchestrationStepType.ROUTE_PROVIDER,
                description="Rank compatible providers deterministically",
            ),
            OrchestrationPlanStep(
                order=3,
                step_type=OrchestrationStepType.RESOLVE_PREFERENCES,
                description="Resolve model, cost, latency, and context preferences",
            ),
            OrchestrationPlanStep(
                order=4,
                step_type=OrchestrationStepType.NEGOTIATE_PROVIDER,
                description="Negotiate provider, model, and capabilities",
            ),
            OrchestrationPlanStep(
                order=5,
                step_type=OrchestrationStepType.PREPARE_PLAN,
                description="Prepare an architecture-only non-executable plan",
            ),
        )
        plan = OrchestrationPlan(
            session_id=session.session_id,
            request=request,
            negotiation=negotiation,
            steps=steps,
            routing_policy=resolved_routing,
            preference_policy=resolved_preferences,
            metadata={} if metadata is None else metadata,
            plan_id=self._new_id(),
            created_at=now,
        )
        self._log(
            LogLevel.INFO,
            "AI orchestration plan generated",
            session_id=session.session_id,
            plan_id=plan.plan_id,
            request_id=request.request_id,
            provider_id=plan.provider_id,
            step_count=len(plan.steps),
            executable=False,
        )
        self._events.publish(
            AI_PLAN_GENERATED_EVENT,
            session_id=session.session_id,
            plan_id=plan.plan_id,
            request_id=request.request_id,
            provider_id=plan.provider_id,
            model_name=plan.model_name,
            step_count=len(plan.steps),
            architecture_only=True,
            executable=False,
        )
        return plan

    generate = plan

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise PlanGenerationError("clock must return a timezone-aware datetime")
        return value

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise PlanGenerationError(
                "id_factory must return a normalized non-empty string"
            )
        return value

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


ExecutionPlanner = OrchestrationPlanner


__all__ = ["ExecutionPlanner", "OrchestrationPlanner"]
