"""Provider descriptor helpers and deterministic, non-executing selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from .exceptions import AIValidationError, NoEligibleProviderError
from .interfaces import ProviderDescriptor
from .models import (
    AIProvider,
    AIRequest,
    ProviderCapability,
    ProviderMetadata,
    ProviderStatus,
    utc_now,
)


class ProviderSnapshotFactory:
    """Detach an injected provider descriptor into immutable orchestration data."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock

    def create(
        self,
        provider: AIProvider | ProviderMetadata | ProviderDescriptor,
    ) -> AIProvider:
        """Return a validated snapshot without retaining executable behavior."""

        if isinstance(provider, AIProvider):
            return provider
        if isinstance(provider, ProviderMetadata):
            return AIProvider(metadata=provider, registered_at=self._now())
        metadata = getattr(provider, "metadata", None)
        health = getattr(provider, "health", None)
        if not isinstance(metadata, ProviderMetadata):
            raise TypeError(
                "provider must be AIProvider, ProviderMetadata, or ProviderDescriptor"
            )
        return AIProvider(
            metadata=metadata,
            health=health,
            registered_at=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise AIValidationError("clock must return a timezone-aware datetime")
        return value


class PriorityProviderSelector:
    """Select an eligible descriptor using preference, priority, and health."""

    _STATUS_RANK = {
        ProviderStatus.AVAILABLE: 0,
        ProviderStatus.DEGRADED: 1,
    }

    def __init__(self, *, allow_degraded: bool = True) -> None:
        if not isinstance(allow_degraded, bool):
            raise TypeError("allow_degraded must be a bool")
        self._allow_degraded = allow_degraded

    def select(
        self,
        providers: Iterable[AIProvider],
        request: AIRequest | None = None,
        *,
        required_capabilities: Iterable[ProviderCapability] = (),
        preferred_provider_id: str | None = None,
    ) -> AIProvider:
        """Return one immutable provider descriptor without executing it."""

        candidates = self._providers(providers)
        if request is not None and not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest or None")
        required = self._required_capabilities(request, required_capabilities)
        preferred = self._preferred_provider_id(request, preferred_provider_id)
        eligible = tuple(
            provider for provider in candidates if self._eligible(provider, required)
        )
        if preferred is not None:
            for provider in eligible:
                if provider.provider_id == preferred:
                    return provider
        if not eligible:
            capability_names = ", ".join(item.value for item in required) or "none"
            raise NoEligibleProviderError(
                "no registered provider is eligible for capabilities "
                f"[{capability_names}]"
            )
        return min(
            eligible,
            key=lambda provider: (
                int(provider.priority),
                self._STATUS_RANK[provider.status],
                provider.provider_id.casefold(),
                provider.provider_id,
            ),
        )

    def _eligible(
        self,
        provider: AIProvider,
        required: tuple[ProviderCapability, ...],
    ) -> bool:
        allowed_statuses = {ProviderStatus.AVAILABLE}
        if self._allow_degraded:
            allowed_statuses.add(ProviderStatus.DEGRADED)
        return (
            provider.metadata.enabled
            and provider.status in allowed_statuses
            and set(required).issubset(provider.capabilities)
        )

    @staticmethod
    def _providers(providers: Iterable[AIProvider]) -> tuple[AIProvider, ...]:
        if isinstance(providers, (str, bytes)):
            raise TypeError("providers must contain AIProvider values")
        try:
            values = tuple(providers)
        except TypeError as error:
            raise TypeError("providers must be iterable") from error
        if any(not isinstance(provider, AIProvider) for provider in values):
            raise TypeError("providers must contain AIProvider values")
        identifiers = tuple(provider.provider_id for provider in values)
        if len(set(identifiers)) != len(identifiers):
            raise AIValidationError("providers cannot contain duplicate identifiers")
        return values

    @staticmethod
    def _required_capabilities(
        request: AIRequest | None,
        required_capabilities: Iterable[ProviderCapability],
    ) -> tuple[ProviderCapability, ...]:
        if isinstance(required_capabilities, (str, bytes)):
            raise TypeError(
                "required_capabilities must contain ProviderCapability values"
            )
        try:
            explicit = tuple(required_capabilities)
        except TypeError as error:
            raise TypeError("required_capabilities must be iterable") from error
        if any(not isinstance(item, ProviderCapability) for item in explicit):
            raise TypeError(
                "required_capabilities must contain ProviderCapability values"
            )
        combined = (
            *(() if request is None else request.required_capabilities),
            *explicit,
        )
        return tuple(dict.fromkeys(combined))

    @staticmethod
    def _preferred_provider_id(
        request: AIRequest | None,
        preferred_provider_id: str | None,
    ) -> str | None:
        value = (
            preferred_provider_id
            if preferred_provider_id is not None
            else (None if request is None else request.preferred_provider_id)
        )
        if value is not None and (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 128
        ):
            raise AIValidationError(
                "preferred_provider_id must be normalized non-empty text"
            )
        return value


DefaultProviderSelector = PriorityProviderSelector


__all__ = [
    "DefaultProviderSelector",
    "PriorityProviderSelector",
    "ProviderSnapshotFactory",
]
