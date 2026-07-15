"""Deterministic provider routing with no model or provider execution."""

from .capabilities import (
    CapabilityMatcher,
    CompatibilityValidator,
    ProviderCompatibilityValidator,
)
from .exceptions import (
    AIRoutingError,
    CapabilityMatchingError,
    FallbackUnavailableError,
    NoCompatibleProviderError,
    ProviderCompatibilityError,
    ProviderScoringError,
    RequestValidationError,
    RoutingPolicyError,
)
from .fallback import FallbackPlanner
from .models import (
    CapabilityMatch,
    CompatibilityReport,
    FallbackPlan,
    ProviderScore,
    RequestPolicy,
    RoutingDecision,
    RoutingExplanation,
    RoutingPolicy,
    RoutingResult,
    RoutingSummary,
    ScoringWeights,
    SelectionPolicy,
)
from .policy import RequestPolicyValidator, RoutingPolicyValidator
from .router import (
    AIRouter,
    AI_PROVIDER_FALLBACK_EVENT,
    AI_PROVIDER_SCORED_EVENT,
    AI_REQUEST_ROUTED_EVENT,
    AI_VALIDATION_FAILED_EVENT,
    DeterministicRouter,
    RequestRouter,
)
from .scoring import DeterministicProviderScorer, ProviderScorer

__all__ = [
    "AIRouter",
    "AIRoutingError",
    "AI_PROVIDER_FALLBACK_EVENT",
    "AI_PROVIDER_SCORED_EVENT",
    "AI_REQUEST_ROUTED_EVENT",
    "AI_VALIDATION_FAILED_EVENT",
    "CapabilityMatch",
    "CapabilityMatcher",
    "CapabilityMatchingError",
    "CompatibilityReport",
    "CompatibilityValidator",
    "DeterministicProviderScorer",
    "DeterministicRouter",
    "FallbackPlan",
    "FallbackPlanner",
    "FallbackUnavailableError",
    "NoCompatibleProviderError",
    "ProviderCompatibilityError",
    "ProviderCompatibilityValidator",
    "ProviderScore",
    "ProviderScorer",
    "RequestPolicy",
    "RequestPolicyValidator",
    "RequestRouter",
    "RequestValidationError",
    "RoutingDecision",
    "RoutingExplanation",
    "RoutingPolicy",
    "RoutingPolicyError",
    "RoutingPolicyValidator",
    "RoutingResult",
    "RoutingSummary",
    "ScoringWeights",
    "SelectionPolicy",
]
