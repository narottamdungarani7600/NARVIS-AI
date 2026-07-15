"""Immutable models for deterministic, provider-agnostic AI routing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from AI.core.models import (
    AIProvider,
    AIRequest,
    ProviderCapability,
    immutable_mapping,
    new_id,
    utc_now,
)


class SelectionPolicy(str, Enum):
    """Deterministic ranking policies available to the request router."""

    BALANCED = "balanced"
    PRIORITY = "priority"
    PRIORITY_FIRST = "priority"
    HEALTH = "health"
    HEALTH_FIRST = "health"
    CAPABILITY = "capability"
    CAPABILITY_FIRST = "capability"
    PREFERRED = "preferred"
    PREFERRED_FIRST = "preferred"


def _text(
    value: object,
    name: str,
    *,
    maximum: int = 256,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        value != value.strip()
        or len(value) > maximum
        or (not value and not allow_empty)
    ):
        raise ValueError(
            f"{name} must be normalized text of at most {maximum} characters"
        )
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _score(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if result != result or result < 0.0 or result > 100.0:
        raise ValueError(f"{name} must be between 0 and 100")
    return result


def _capabilities(
    values: object,
    name: str,
) -> tuple[ProviderCapability, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must contain ProviderCapability values")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    if any(not isinstance(item, ProviderCapability) for item in result):
        raise TypeError(f"{name} must contain ProviderCapability values")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    for value in result:
        _text(value, name, maximum=128)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _reasons(values: object, name: str = "reasons") -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    for value in result:
        _text(value, name, maximum=1000)
    return result


@dataclass(slots=True, frozen=True)
class ScoringWeights:
    """Normalized deterministic weights used for provider scoring."""

    capability: float = 0.35
    health: float = 0.25
    priority: float = 0.20
    preference: float = 0.10
    model: float = 0.10

    def __post_init__(self) -> None:
        values = (
            self.capability,
            self.health,
            self.priority,
            self.preference,
            self.model,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value != value
            or value < 0
            for value in values
        ):
            raise ValueError("scoring weights must be finite non-negative numbers")
        total = float(sum(values))
        if abs(total - 1.0) > 1e-9:
            raise ValueError("scoring weights must total 1.0")
        for name in ("capability", "health", "priority", "preference", "model"):
            object.__setattr__(self, name, float(getattr(self, name)))


@dataclass(slots=True, frozen=True)
class RoutingPolicy:
    """Immutable request policy controlling validation, ranking, and fallback."""

    selection: SelectionPolicy = SelectionPolicy.BALANCED
    required_capabilities: tuple[ProviderCapability, ...] = ()
    allowed_capabilities: tuple[ProviderCapability, ...] = ()
    allow_degraded: bool = True
    allow_unknown: bool = False
    require_model_match: bool = True
    minimum_score: float = 0.0
    max_fallbacks: int = 3
    excluded_provider_ids: tuple[str, ...] = ()
    maximum_prompt_characters: int = 200_000
    maximum_system_prompt_characters: int = 100_000
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.selection, SelectionPolicy):
            raise TypeError("selection must be a SelectionPolicy")
        required = _capabilities(self.required_capabilities, "required_capabilities")
        allowed = _capabilities(self.allowed_capabilities, "allowed_capabilities")
        if allowed and not set(required).issubset(allowed):
            raise ValueError("required_capabilities must be allowed by the policy")
        object.__setattr__(self, "required_capabilities", required)
        object.__setattr__(self, "allowed_capabilities", allowed)
        for name in ("allow_degraded", "allow_unknown", "require_model_match"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        object.__setattr__(
            self,
            "minimum_score",
            _score(self.minimum_score, "minimum_score"),
        )
        if (
            isinstance(self.max_fallbacks, bool)
            or not isinstance(self.max_fallbacks, int)
            or self.max_fallbacks < 0
        ):
            raise ValueError("max_fallbacks must be a non-negative integer")
        object.__setattr__(
            self,
            "excluded_provider_ids",
            _identifiers(self.excluded_provider_ids, "excluded_provider_ids"),
        )
        for name in (
            "maximum_prompt_characters",
            "maximum_system_prompt_characters",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def selection_policy(self) -> SelectionPolicy:
        """Return the configured ranking strategy using explicit terminology."""

        return self.selection


RequestPolicy = RoutingPolicy


@dataclass(slots=True, frozen=True)
class CapabilityMatch:
    """Explain how one provider matches all effective required capabilities."""

    provider_id: str
    required: tuple[ProviderCapability, ...]
    advertised: tuple[ProviderCapability, ...]
    matched: tuple[ProviderCapability, ...]
    missing: tuple[ProviderCapability, ...]
    score: float

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id", maximum=128)
        required = _capabilities(self.required, "required")
        advertised = _capabilities(self.advertised, "advertised")
        matched = _capabilities(self.matched, "matched")
        missing = _capabilities(self.missing, "missing")
        expected_matched = tuple(item for item in required if item in advertised)
        expected_missing = tuple(item for item in required if item not in advertised)
        if matched != expected_matched or missing != expected_missing:
            raise ValueError("matched and missing capabilities must partition required")
        expected_score = 100.0 if not required else 100.0 * len(matched) / len(required)
        normalized_score = _score(self.score, "score")
        if abs(normalized_score - expected_score) > 1e-9:
            raise ValueError(
                "capability score must match the required capability ratio"
            )
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "advertised", advertised)
        object.__setattr__(self, "matched", matched)
        object.__setattr__(self, "missing", missing)
        object.__setattr__(self, "score", normalized_score)

    @property
    def compatible(self) -> bool:
        """Return whether every effective capability was matched."""

        return not self.missing


@dataclass(slots=True, frozen=True)
class CompatibilityReport:
    """Immutable provider/request compatibility facts used before ranking."""

    provider_id: str
    request_id: str
    compatible: bool
    capability_match: CapabilityMatch
    enabled: bool
    health_compatible: bool
    model_compatible: bool
    reasons: tuple[str, ...] = ()
    validated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id", maximum=128)
        _text(self.request_id, "request_id", maximum=128)
        if not isinstance(self.capability_match, CapabilityMatch):
            raise TypeError("capability_match must be a CapabilityMatch")
        if self.capability_match.provider_id != self.provider_id:
            raise ValueError("capability match must belong to the provider")
        for name in ("compatible", "enabled", "health_compatible", "model_compatible"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        reasons = _reasons(self.reasons)
        expected = (
            self.enabled
            and self.health_compatible
            and self.model_compatible
            and self.capability_match.compatible
        )
        if self.compatible is not expected:
            raise ValueError("compatibility must agree with all validation facts")
        if not self.compatible and not reasons:
            raise ValueError("incompatible reports require at least one reason")
        if self.compatible and reasons:
            raise ValueError("compatible reports cannot contain failure reasons")
        object.__setattr__(self, "reasons", reasons)
        _time(self.validated_at, "validated_at")

    @property
    def missing_capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return capabilities absent from the provider."""

        return self.capability_match.missing


@dataclass(slots=True, frozen=True)
class ProviderScore:
    """Deterministic weighted score for one provider/request pair."""

    provider_id: str
    request_id: str
    total: float
    capability_score: float
    health_score: float
    priority_score: float
    preference_score: float
    model_score: float
    compatible: bool
    reasons: tuple[str, ...] = ()
    scored_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id", maximum=128)
        _text(self.request_id, "request_id", maximum=128)
        for name in (
            "total",
            "capability_score",
            "health_score",
            "priority_score",
            "preference_score",
            "model_score",
        ):
            object.__setattr__(self, name, _score(getattr(self, name), name))
        if not isinstance(self.compatible, bool):
            raise TypeError("compatible must be a bool")
        object.__setattr__(self, "reasons", _reasons(self.reasons))
        _time(self.scored_at, "scored_at")

    @property
    def total_score(self) -> float:
        """Return the aggregate score using explicit terminology."""

        return self.total


@dataclass(slots=True, frozen=True)
class FallbackPlan:
    """Ordered provider identifiers available after a primary routing choice."""

    request_id: str
    primary_provider_id: str
    provider_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", maximum=128)
        _text(self.primary_provider_id, "primary_provider_id", maximum=128)
        identifiers = _identifiers(self.provider_ids, "provider_ids")
        if self.primary_provider_id in identifiers:
            raise ValueError("fallback providers cannot include the primary provider")
        object.__setattr__(self, "provider_ids", identifiers)
        _time(self.created_at, "created_at")

    @property
    def chain(self) -> tuple[str, ...]:
        """Return the ordered fallback chain."""

        return self.provider_ids

    @property
    def has_fallback(self) -> bool:
        """Return whether at least one fallback was planned."""

        return bool(self.provider_ids)

    def after(self, provider_id: str | None = None) -> tuple[str, ...]:
        """Return planned identifiers following a primary or fallback provider."""

        current = self.primary_provider_id if provider_id is None else provider_id
        _text(current, "provider_id", maximum=128)
        sequence = (self.primary_provider_id, *self.provider_ids)
        if current not in sequence:
            raise ValueError("provider_id is not present in the fallback plan")
        return tuple(sequence[sequence.index(current) + 1 :])


@dataclass(slots=True, frozen=True)
class RoutingExplanation:
    """Safe, immutable explanation of one deterministic routing choice."""

    request_id: str
    selected_provider_id: str
    summary: str
    factors: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", maximum=128)
        _text(self.selected_provider_id, "selected_provider_id", maximum=128)
        if (
            not isinstance(self.summary, str)
            or not self.summary.strip()
            or len(self.summary) > 2000
        ):
            raise ValueError(
                "summary must be non-empty text of at most 2000 characters"
            )
        factors = _reasons(self.factors, "factors")
        if not factors:
            raise ValueError("routing explanations require at least one factor")
        object.__setattr__(self, "factors", factors)


@dataclass(slots=True, frozen=True)
class RoutingDecision:
    """Complete immutable result of architecture-only request routing."""

    request: AIRequest
    selected_provider: AIProvider
    selected_score: ProviderScore
    provider_scores: tuple[ProviderScore, ...]
    compatibility_reports: tuple[CompatibilityReport, ...]
    fallback_plan: FallbackPlan
    policy: RoutingPolicy
    explanation: RoutingExplanation
    decision_id: str = field(default_factory=new_id)
    routed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(self.selected_provider, AIProvider):
            raise TypeError("selected_provider must be an AIProvider")
        if not isinstance(self.selected_score, ProviderScore):
            raise TypeError("selected_score must be a ProviderScore")
        scores = tuple(self.provider_scores)
        reports = tuple(self.compatibility_reports)
        if not scores or any(not isinstance(item, ProviderScore) for item in scores):
            raise ValueError("provider_scores must contain ProviderScore values")
        if any(not isinstance(item, CompatibilityReport) for item in reports):
            raise TypeError(
                "compatibility_reports must contain CompatibilityReport values"
            )
        score_ids = tuple(item.provider_id for item in scores)
        report_ids = tuple(item.provider_id for item in reports)
        if len(set(score_ids)) != len(score_ids) or len(set(report_ids)) != len(
            report_ids
        ):
            raise ValueError("routing provider identifiers must be unique")
        if set(score_ids) != set(report_ids):
            raise ValueError(
                "scores and compatibility reports must cover the same providers"
            )
        if self.selected_provider.provider_id != self.selected_score.provider_id:
            raise ValueError("selected provider must match selected score")
        if scores[0] != self.selected_score or not self.selected_score.compatible:
            raise ValueError("selected score must be the first compatible ranked score")
        if any(item.request_id != self.request.request_id for item in scores):
            raise ValueError("provider scores must belong to the request")
        if any(item.request_id != self.request.request_id for item in reports):
            raise ValueError("compatibility reports must belong to the request")
        if not isinstance(self.fallback_plan, FallbackPlan):
            raise TypeError("fallback_plan must be a FallbackPlan")
        if (
            self.fallback_plan.request_id != self.request.request_id
            or self.fallback_plan.primary_provider_id
            != self.selected_provider.provider_id
        ):
            raise ValueError("fallback plan must belong to the routing choice")
        fallback_ids = self.fallback_plan.provider_ids
        if any(identifier not in score_ids for identifier in fallback_ids):
            raise ValueError("fallback providers must be present in provider scores")
        if any(
            not next(
                item for item in scores if item.provider_id == identifier
            ).compatible
            for identifier in fallback_ids
        ):
            raise ValueError("fallback providers must be compatible")
        if not isinstance(self.policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        if len(fallback_ids) > self.policy.max_fallbacks:
            raise ValueError("fallback plan exceeds the routing policy maximum")
        if not isinstance(self.explanation, RoutingExplanation):
            raise TypeError("explanation must be a RoutingExplanation")
        if (
            self.explanation.request_id != self.request.request_id
            or self.explanation.selected_provider_id
            != self.selected_provider.provider_id
        ):
            raise ValueError("routing explanation must belong to the routing choice")
        _text(self.decision_id, "decision_id", maximum=128)
        _time(self.routed_at, "routed_at")
        object.__setattr__(self, "provider_scores", scores)
        object.__setattr__(self, "compatibility_reports", reports)

    @property
    def request_id(self) -> str:
        """Return the routed request identifier."""

        return self.request.request_id

    @property
    def selected_provider_id(self) -> str:
        """Return the chosen provider identifier."""

        return self.selected_provider.provider_id

    @property
    def fallback_chain(self) -> tuple[str, ...]:
        """Return the ordered fallback provider identifiers."""

        return self.fallback_plan.provider_ids


RoutingResult = RoutingDecision


@dataclass(slots=True, frozen=True)
class RoutingSummary:
    """Compact export-ready facts derived from one routing decision."""

    request_id: str
    selected_provider_id: str
    candidate_count: int
    compatible_count: int
    fallback_count: int
    selected_score: float
    selection_policy: SelectionPolicy
    explanation: str
    generated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", maximum=128)
        _text(self.selected_provider_id, "selected_provider_id", maximum=128)
        for name in ("candidate_count", "compatible_count", "fallback_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.compatible_count > self.candidate_count:
            raise ValueError("compatible_count cannot exceed candidate_count")
        if self.fallback_count > max(0, self.compatible_count - 1):
            raise ValueError(
                "fallback_count cannot exceed remaining compatible providers"
            )
        object.__setattr__(
            self,
            "selected_score",
            _score(self.selected_score, "selected_score"),
        )
        if not isinstance(self.selection_policy, SelectionPolicy):
            raise TypeError("selection_policy must be a SelectionPolicy")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("explanation must be non-empty text")
        _time(self.generated_at, "generated_at")


__all__ = [
    "CapabilityMatch",
    "CompatibilityReport",
    "FallbackPlan",
    "ProviderScore",
    "RequestPolicy",
    "RoutingDecision",
    "RoutingExplanation",
    "RoutingPolicy",
    "RoutingResult",
    "RoutingSummary",
    "ScoringWeights",
    "SelectionPolicy",
]
