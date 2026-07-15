"""Typed failures for the provider-agnostic AI orchestration foundation."""

from __future__ import annotations


class AIOrchestratorError(Exception):
    """Base exception for inert AI orchestration services."""


class AIValidationError(AIOrchestratorError, ValueError):
    """Raised when an immutable AI model or operation is invalid."""


class ProviderRegistryError(AIOrchestratorError):
    """Base failure for provider registry operations."""


class ProviderAlreadyRegisteredError(ProviderRegistryError, ValueError):
    """Raised when a provider name is registered more than once."""


class ProviderNotFoundError(ProviderRegistryError, LookupError):
    """Raised when a provider is not present in the registry."""


class ProviderHealthError(AIOrchestratorError):
    """Raised when provider health cannot be inspected or updated safely."""


class ProviderUnavailableError(AIOrchestratorError):
    """Raised when a requested provider is not selectable."""


class ProviderCapabilityError(AIOrchestratorError):
    """Raised when a provider lacks required capabilities."""


class NoEligibleProviderError(ProviderUnavailableError):
    """Raised when no registered provider satisfies a selection request."""


__all__ = [
    "AIOrchestratorError",
    "AIValidationError",
    "NoEligibleProviderError",
    "ProviderAlreadyRegisteredError",
    "ProviderCapabilityError",
    "ProviderHealthError",
    "ProviderNotFoundError",
    "ProviderRegistryError",
    "ProviderUnavailableError",
]
