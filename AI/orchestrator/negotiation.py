"""Deterministic provider, model, and capability negotiation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime

from AI.core.models import AIProvider, AIRequest, utc_now
from AI.routing.models import RoutingPolicy
from AI.routing.policy import RequestPolicyValidator
from AI.routing.router import RequestRouter
from Core.logger import LogLevel, Logger, NullLogger

from .events import AI_PROVIDER_NEGOTIATED_EVENT, OrchestrationEvents
from .exceptions import ProviderNegotiationError
from .models import (
    CapabilityNegotiation,
    ModelOption,
    ModelPreferencePolicy,
    ProviderNegotiation,
)
from .preferences import ModelPreferenceResolver


class CapabilityNegotiator:
    """Negotiate effective capabilities using immutable advertised facts."""

    def __init__(
        self,
        policy_validator: RequestPolicyValidator | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        resolved = (
            policy_validator
            if policy_validator is not None
            else RequestPolicyValidator()
        )
        if not callable(getattr(resolved, "effective_capabilities", None)):
            raise TypeError("policy_validator must provide effective_capabilities")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._policy_validator = resolved
        self._clock = clock

    def negotiate(
        self,
        request: AIRequest,
        provider: AIProvider,
        routing_policy: RoutingPolicy,
        model_option: ModelOption | None = None,
    ) -> CapabilityNegotiation:
        """Return exact matched and missing capability facts."""

        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        if not isinstance(routing_policy, RoutingPolicy):
            raise TypeError("routing_policy must be a RoutingPolicy")
        if model_option is not None and not isinstance(model_option, ModelOption):
            raise TypeError("model_option must be a ModelOption or None")
        if (
            model_option is not None
            and model_option.provider_id != provider.provider_id
        ):
            raise ValueError("model_option must belong to provider")
        required = self._policy_validator.effective_capabilities(
            request,
            routing_policy,
        )
        advertised = provider.capabilities
        if model_option is not None:
            advertised = tuple(
                item for item in advertised if item in model_option.capabilities
            )
        matched = tuple(item for item in required if item in advertised)
        missing = tuple(item for item in required if item not in advertised)
        return CapabilityNegotiation(
            request_id=request.request_id,
            provider_id=provider.provider_id,
            required=required,
            matched=matched,
            missing=missing,
            successful=not missing,
            negotiated_at=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ProviderNegotiationError(
                "clock must return a timezone-aware datetime"
            )
        return value


class ProviderNegotiator:
    """Combine routing and preference results into one provider negotiation."""

    def __init__(
        self,
        request_router: RequestRouter,
        preference_resolver: ModelPreferenceResolver | None = None,
        capability_negotiator: CapabilityNegotiator | None = None,
        events: OrchestrationEvents | None = None,
        *,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not callable(getattr(request_router, "route", None)):
            raise TypeError("request_router must provide a route method")
        resolved_preferences = (
            preference_resolver
            if preference_resolver is not None
            else ModelPreferenceResolver()
        )
        if not callable(getattr(resolved_preferences, "resolve_for_providers", None)):
            raise TypeError("preference_resolver must provide resolve_for_providers")
        resolved_capabilities = (
            capability_negotiator
            if capability_negotiator is not None
            else CapabilityNegotiator(clock=clock)
        )
        if not callable(getattr(resolved_capabilities, "negotiate", None)):
            raise TypeError("capability_negotiator must provide negotiate")
        resolved_events = events if events is not None else OrchestrationEvents()
        if not callable(getattr(resolved_events, "publish", None)):
            raise TypeError("events must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        from AI.core.models import new_id

        resolved_id_factory = id_factory if id_factory is not None else new_id
        if not callable(resolved_id_factory):
            raise TypeError("id_factory must be callable")
        self._request_router = request_router
        self._preferences = resolved_preferences
        self._capabilities = resolved_capabilities
        self._events = resolved_events
        self._logger = (
            logger if logger is not None else NullLogger("narvis.ai.negotiation")
        )
        self._clock = clock
        self._id_factory = resolved_id_factory

    @property
    def preference_resolver(self) -> ModelPreferenceResolver:
        return self._preferences

    @property
    def capability_negotiator(self) -> CapabilityNegotiator:
        return self._capabilities

    def negotiate(
        self,
        request: AIRequest,
        providers: Iterable[AIProvider],
        routing_policy: RoutingPolicy | None = None,
        preference_policy: ModelPreferencePolicy | None = None,
    ) -> ProviderNegotiation:
        """Negotiate one provider/model combination without invoking either."""

        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        resolved_routing = routing_policy or RoutingPolicy()
        resolved_preferences = preference_policy or ModelPreferencePolicy()
        if not isinstance(resolved_routing, RoutingPolicy):
            raise TypeError("routing_policy must be a RoutingPolicy or None")
        if not isinstance(resolved_preferences, ModelPreferencePolicy):
            raise TypeError("preference_policy must be a ModelPreferencePolicy or None")
        if isinstance(providers, (str, bytes)):
            raise TypeError("providers must contain AIProvider values")
        try:
            candidates = tuple(providers)
        except TypeError as error:
            raise TypeError("providers must be iterable") from error
        if any(not isinstance(item, AIProvider) for item in candidates):
            raise TypeError("providers must contain AIProvider values")
        decision = self._request_router.route(request, candidates, resolved_routing)
        providers_by_id = {item.provider_id: item for item in candidates}
        eligible_ids = tuple(
            item.provider_id
            for item in decision.provider_scores
            if item.compatible and item.total >= resolved_routing.minimum_score
        )
        ranked_providers = tuple(providers_by_id[item] for item in eligible_ids)
        effective_capabilities = RequestPolicyValidator.effective_capabilities(
            request,
            resolved_routing,
        )
        preference_request = replace(
            request,
            required_capabilities=effective_capabilities,
        )
        resolution = self._preferences.resolve_for_providers(
            preference_request,
            ranked_providers,
            resolved_preferences,
        )
        provider = providers_by_id.get(resolution.provider_id)
        if provider is None:
            raise ProviderNegotiationError(
                "preference resolution selected an unregistered provider"
            )
        capability = self._capabilities.negotiate(
            request,
            provider,
            resolved_routing,
            resolution.selected_option,
        )
        if not capability.successful:
            missing = ", ".join(item.value for item in capability.missing)
            raise ProviderNegotiationError(
                f"selected provider/model lacks capabilities [{missing}]"
            )
        negotiation = ProviderNegotiation(
            request=request,
            provider=provider,
            routing_decision=decision,
            preference_resolution=resolution,
            capability_negotiation=capability,
            negotiation_id=self._new_id(),
            negotiated_at=self._now(),
        )
        self._log(
            LogLevel.INFO,
            "AI provider negotiated",
            request_id=request.request_id,
            provider_id=provider.provider_id,
            model_name=negotiation.model_name,
            routing_provider_id=decision.selected_provider_id,
        )
        self._events.publish(
            AI_PROVIDER_NEGOTIATED_EVENT,
            request_id=request.request_id,
            provider_id=provider.provider_id,
            model_name=negotiation.model_name,
            routing_provider_id=decision.selected_provider_id,
            capabilities=tuple(item.value for item in capability.matched),
            cost_known=negotiation.cost.known,
            latency_known=negotiation.latency.known,
            context_known=negotiation.context_size.known,
        )
        return negotiation

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ProviderNegotiationError(
                "clock must return a timezone-aware datetime"
            )
        return value

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise ProviderNegotiationError(
                "id_factory must return a normalized non-empty string"
            )
        return value

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["CapabilityNegotiator", "ProviderNegotiator"]
