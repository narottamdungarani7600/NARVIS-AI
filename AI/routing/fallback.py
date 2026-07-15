"""Pure planning for deterministic provider fallback chains."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from AI.core.models import utc_now

from .exceptions import FallbackUnavailableError
from .models import FallbackPlan, ProviderScore, RoutingPolicy


class FallbackPlanner:
    """Build ordered fallback identifiers from already-ranked provider scores."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock

    def plan(
        self,
        request_id: str,
        ranked_scores: Iterable[ProviderScore],
        primary_provider_id: str,
        policy: RoutingPolicy,
    ) -> FallbackPlan:
        """Return a bounded immutable chain without invoking any provider."""

        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be non-empty text")
        if not isinstance(primary_provider_id, str) or not primary_provider_id:
            raise ValueError("primary_provider_id must be non-empty text")
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        if isinstance(ranked_scores, (str, bytes)):
            raise TypeError("ranked_scores must contain ProviderScore values")
        try:
            scores = tuple(ranked_scores)
        except TypeError as error:
            raise TypeError("ranked_scores must be iterable") from error
        if any(not isinstance(item, ProviderScore) for item in scores):
            raise TypeError("ranked_scores must contain ProviderScore values")
        if any(item.request_id != request_id for item in scores):
            raise ValueError("ranked_scores must belong to request_id")
        identifiers = tuple(item.provider_id for item in scores)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("ranked_scores cannot contain duplicate providers")
        if primary_provider_id not in identifiers:
            raise ValueError("primary provider must be present in ranked_scores")
        primary = next(
            item for item in scores if item.provider_id == primary_provider_id
        )
        if not primary.compatible or primary.total < policy.minimum_score:
            raise ValueError(
                "primary provider must be compatible and meet minimum score"
            )
        fallback_ids = tuple(
            item.provider_id
            for item in scores
            if item.provider_id != primary_provider_id
            and item.request_id == request_id
            and item.compatible
            and item.total >= policy.minimum_score
        )[: policy.max_fallbacks]
        return FallbackPlan(
            request_id=request_id,
            primary_provider_id=primary_provider_id,
            provider_ids=fallback_ids,
            created_at=self._now(),
        )

    @staticmethod
    def next_provider_id(
        plan: FallbackPlan,
        current_provider_id: str | None = None,
    ) -> str:
        """Return the next planned identifier or raise a typed failure."""

        if not isinstance(plan, FallbackPlan):
            raise TypeError("plan must be a FallbackPlan")
        try:
            remaining = plan.after(current_provider_id)
        except ValueError as error:
            raise FallbackUnavailableError(str(error)) from error
        if not remaining:
            raise FallbackUnavailableError("no fallback provider remains")
        return remaining[0]

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


__all__ = ["FallbackPlanner"]
