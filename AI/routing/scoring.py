"""Deterministic provider scoring over immutable compatibility facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from AI.core.models import AIProvider, AIRequest, ProviderStatus, utc_now

from .capabilities import CompatibilityValidator
from .exceptions import ProviderScoringError
from .models import (
    CompatibilityReport,
    ProviderScore,
    RoutingPolicy,
    ScoringWeights,
)


class ProviderScorer:
    """Produce reproducible weighted scores without contacting providers."""

    _HEALTH_SCORES = {
        ProviderStatus.AVAILABLE: 100.0,
        ProviderStatus.DEGRADED: 60.0,
        ProviderStatus.UNKNOWN: 25.0,
        ProviderStatus.UNAVAILABLE: 0.0,
        ProviderStatus.DISABLED: 0.0,
    }

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        validator: CompatibilityValidator | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        resolved_weights = weights if weights is not None else ScoringWeights()
        if not isinstance(resolved_weights, ScoringWeights):
            raise TypeError("weights must be ScoringWeights")
        resolved_validator = (
            validator if validator is not None else CompatibilityValidator()
        )
        if not callable(getattr(resolved_validator, "validate", None)):
            raise TypeError("validator must provide a validate method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._weights = resolved_weights
        self._validator = resolved_validator
        self._clock = clock

    @property
    def weights(self) -> ScoringWeights:
        """Return the immutable configured scoring weights."""

        return self._weights

    def score(
        self,
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy,
        compatibility: CompatibilityReport | None = None,
    ) -> ProviderScore:
        """Score one provider deterministically without provider execution."""

        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        report = compatibility or self._validator.validate(provider, request, policy)
        if not isinstance(report, CompatibilityReport):
            raise TypeError("compatibility must be a CompatibilityReport or None")
        if (
            report.provider_id != provider.provider_id
            or report.request_id != request.request_id
        ):
            raise ProviderScoringError(
                "compatibility report must match the provider and request"
            )
        capability_score = report.capability_match.score
        health_score = self._HEALTH_SCORES[provider.status]
        priority_score = max(0.0, min(100.0, 100.0 - int(provider.priority)))
        preference_score = self._preference_score(provider, request)
        model_score = 100.0 if report.model_compatible else 0.0
        total = round(
            capability_score * self._weights.capability
            + health_score * self._weights.health
            + priority_score * self._weights.priority
            + preference_score * self._weights.preference
            + model_score * self._weights.model,
            6,
        )
        reasons = (
            f"capability score {capability_score:.2f}",
            f"health score {health_score:.2f}",
            f"priority score {priority_score:.2f}",
            f"preference score {preference_score:.2f}",
            f"model score {model_score:.2f}",
            *report.reasons,
        )
        return ProviderScore(
            provider_id=provider.provider_id,
            request_id=request.request_id,
            total=total,
            capability_score=capability_score,
            health_score=health_score,
            priority_score=priority_score,
            preference_score=preference_score,
            model_score=model_score,
            compatible=report.compatible,
            reasons=reasons,
            scored_at=self._now(),
        )

    @staticmethod
    def _preference_score(provider: AIProvider, request: AIRequest) -> float:
        if request.preferred_provider_id is None:
            return 50.0
        if provider.provider_id == request.preferred_provider_id:
            return 100.0
        return 0.0

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ProviderScoringError("clock must return a timezone-aware datetime")
        return value


DeterministicProviderScorer = ProviderScorer


__all__ = ["DeterministicProviderScorer", "ProviderScorer", "ScoringWeights"]
