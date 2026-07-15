"""Structural contracts for provider-agnostic, non-executing AI orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .models import (
    AIProvider,
    AIRequest,
    ProviderCapability,
    ProviderHealth,
    ProviderMetadata,
    ProviderStatus,
)


class EventPublisher(Protocol):
    """Minimal contract implemented by the existing EventBus."""

    def publish(self, event: Any) -> None:
        """Publish one system event."""


class ProviderDescriptor(Protocol):
    """Read-only provider descriptor with no model-execution method."""

    @property
    def metadata(self) -> ProviderMetadata:
        """Return immutable provider metadata."""

    @property
    def health(self) -> ProviderHealth:
        """Return immutable provider health."""


class ProviderCatalog(Protocol):
    """Registry contract consumed through dependency injection."""

    def register(self, provider: AIProvider) -> AIProvider:
        """Register an immutable provider descriptor."""

    def unregister(self, provider_id: str) -> AIProvider:
        """Remove and return a provider descriptor."""

    def get(self, provider_id: str) -> AIProvider:
        """Return a provider descriptor."""

    def list(
        self,
        *,
        capability: ProviderCapability | None = None,
        status: ProviderStatus | None = None,
        include_disabled: bool = True,
    ) -> tuple[AIProvider, ...]:
        """Return a filtered immutable provider snapshot."""

    def update_health(self, health: ProviderHealth) -> AIProvider:
        """Replace only one provider's immutable health snapshot."""


class ProviderSelectionStrategy(Protocol):
    """Selection policy contract that performs no provider execution."""

    def select(
        self,
        providers: Iterable[AIProvider],
        request: AIRequest | None = None,
        *,
        required_capabilities: Iterable[ProviderCapability] = (),
        preferred_provider_id: str | None = None,
    ) -> AIProvider:
        """Select one provider descriptor from already supplied candidates."""


__all__ = [
    "EventPublisher",
    "ProviderCatalog",
    "ProviderDescriptor",
    "ProviderSelectionStrategy",
]
