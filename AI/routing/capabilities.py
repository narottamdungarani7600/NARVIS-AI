"""Capability matching and provider compatibility validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from AI.core.models import AIProvider, AIRequest, ProviderStatus, utc_now

from .exceptions import ProviderCompatibilityError
from .models import CapabilityMatch, CompatibilityReport, RoutingPolicy
from .policy import RequestPolicyValidator


class CapabilityMatcher:
    """Match effective required capabilities against immutable metadata."""

    def __init__(self, policy_validator: RequestPolicyValidator | None = None) -> None:
        resolved = (
            policy_validator
            if policy_validator is not None
            else RequestPolicyValidator()
        )
        if not callable(getattr(resolved, "effective_capabilities", None)):
            raise TypeError("policy_validator must provide effective_capabilities")
        self._policy_validator = resolved

    def match(
        self,
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy,
    ) -> CapabilityMatch:
        """Return an immutable, ratio-scored capability match."""

        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        required = self._policy_validator.effective_capabilities(request, policy)
        advertised = provider.capabilities
        matched = tuple(item for item in required if item in advertised)
        missing = tuple(item for item in required if item not in advertised)
        score = 100.0 if not required else 100.0 * len(matched) / len(required)
        return CapabilityMatch(
            provider_id=provider.provider_id,
            required=required,
            advertised=advertised,
            matched=matched,
            missing=missing,
            score=score,
        )


class CompatibilityValidator:
    """Validate health, capabilities, model hints, and policy exclusions."""

    def __init__(
        self,
        matcher: CapabilityMatcher | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        resolved = matcher if matcher is not None else CapabilityMatcher()
        if not callable(getattr(resolved, "match", None)):
            raise TypeError("matcher must provide a match method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._matcher = resolved
        self._clock = clock

    def validate(
        self,
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy,
    ) -> CompatibilityReport:
        """Return compatibility facts without invoking or probing a provider."""

        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        capability_match = self._matcher.match(provider, request, policy)
        enabled = provider.metadata.enabled and (
            provider.provider_id not in policy.excluded_provider_ids
        )
        health_compatible = self._health_compatible(provider, policy)
        model_compatible = self._model_compatible(provider, request, policy)
        reasons: list[str] = []
        if not provider.metadata.enabled:
            reasons.append("provider is disabled")
        elif provider.provider_id in policy.excluded_provider_ids:
            reasons.append("provider is excluded by routing policy")
        if not health_compatible:
            reasons.append(f"provider health status is {provider.status.value}")
        if capability_match.missing:
            missing = ", ".join(item.value for item in capability_match.missing)
            reasons.append(f"missing required capabilities [{missing}]")
        if not model_compatible:
            reasons.append("requested model is not supported")
        compatible = (
            enabled
            and health_compatible
            and capability_match.compatible
            and model_compatible
        )
        return CompatibilityReport(
            provider_id=provider.provider_id,
            request_id=request.request_id,
            compatible=compatible,
            capability_match=capability_match,
            enabled=enabled,
            health_compatible=health_compatible,
            model_compatible=model_compatible,
            reasons=tuple(reasons),
            validated_at=self._now(),
        )

    @staticmethod
    def _health_compatible(
        provider: AIProvider,
        policy: RoutingPolicy,
    ) -> bool:
        if provider.status is ProviderStatus.AVAILABLE:
            return True
        if provider.status is ProviderStatus.DEGRADED:
            return policy.allow_degraded
        if provider.status is ProviderStatus.UNKNOWN:
            return policy.allow_unknown
        return False

    @staticmethod
    def _model_compatible(
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy,
    ) -> bool:
        if request.model_hint is None or not policy.require_model_match:
            return True
        return request.model_hint in provider.metadata.supported_models

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ProviderCompatibilityError(
                "clock must return a timezone-aware datetime"
            )
        return value


ProviderCompatibilityValidator = CompatibilityValidator


__all__ = [
    "CapabilityMatcher",
    "CompatibilityValidator",
    "ProviderCompatibilityValidator",
]
