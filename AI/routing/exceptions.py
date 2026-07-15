"""Typed failures for deterministic, non-executing AI request routing."""

from __future__ import annotations

from AI.core.exceptions import AIOrchestratorError, NoEligibleProviderError


class AIRoutingError(AIOrchestratorError):
    """Base exception for architecture-only routing services."""


class RequestValidationError(AIRoutingError, ValueError):
    """Raised when an AI request violates its immutable routing policy."""


class RoutingPolicyError(AIRoutingError, ValueError):
    """Raised when a routing policy is invalid or unsupported."""


class CapabilityMatchingError(AIRoutingError):
    """Raised when capability compatibility cannot be determined."""


class ProviderCompatibilityError(AIRoutingError):
    """Raised when provider compatibility validation cannot be completed."""


class ProviderScoringError(AIRoutingError):
    """Raised when a provider cannot be scored deterministically."""


class NoCompatibleProviderError(AIRoutingError, NoEligibleProviderError):
    """Raised when no registered provider satisfies a routing request."""


class FallbackUnavailableError(AIRoutingError, LookupError):
    """Raised when an immutable routing decision has no usable fallback."""


__all__ = [
    "AIRoutingError",
    "CapabilityMatchingError",
    "FallbackUnavailableError",
    "NoCompatibleProviderError",
    "ProviderCompatibilityError",
    "ProviderScoringError",
    "RequestValidationError",
    "RoutingPolicyError",
]
