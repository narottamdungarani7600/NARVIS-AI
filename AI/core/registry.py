"""Thread-safe registry of immutable AI provider descriptors."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from .exceptions import (
    AIValidationError,
    ProviderAlreadyRegisteredError,
    ProviderHealthError,
    ProviderNotFoundError,
)
from .models import (
    AIProvider,
    ProviderCapability,
    ProviderHealth,
    ProviderMetadata,
    ProviderStatus,
)


class ProviderRegistry:
    """Retain immutable descriptors behind one re-entrant lock."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._lock = RLock()

    def register(self, provider: AIProvider) -> AIProvider:
        """Register one provider snapshot under its stable identifier."""

        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        with self._lock:
            if provider.provider_id in self._providers:
                raise ProviderAlreadyRegisteredError(
                    f"provider '{provider.provider_id}' is already registered"
                )
            self._providers[provider.provider_id] = provider
            return provider

    register_provider = register

    def unregister(self, provider_id: str) -> AIProvider:
        """Remove and return one provider snapshot."""

        identifier = self._provider_id(provider_id)
        with self._lock:
            try:
                return self._providers.pop(identifier)
            except KeyError as error:
                raise ProviderNotFoundError(
                    f"provider '{identifier}' is not registered"
                ) from error

    unregister_provider = unregister

    def get(self, provider_id: str) -> AIProvider:
        """Return one immutable provider snapshot."""

        identifier = self._provider_id(provider_id)
        with self._lock:
            try:
                return self._providers[identifier]
            except KeyError as error:
                raise ProviderNotFoundError(
                    f"provider '{identifier}' is not registered"
                ) from error

    get_provider = get

    def find(self, provider_id: str) -> AIProvider | None:
        """Return a provider when registered, otherwise ``None``."""

        identifier = self._provider_id(provider_id)
        with self._lock:
            return self._providers.get(identifier)

    def list(
        self,
        *,
        capability: ProviderCapability | None = None,
        status: ProviderStatus | None = None,
        include_disabled: bool = True,
    ) -> tuple[AIProvider, ...]:
        """Return a deterministic filtered registry snapshot."""

        if capability is not None and not isinstance(capability, ProviderCapability):
            raise TypeError("capability must be a ProviderCapability or None")
        if status is not None and not isinstance(status, ProviderStatus):
            raise TypeError("status must be a ProviderStatus or None")
        if not isinstance(include_disabled, bool):
            raise TypeError("include_disabled must be a bool")
        with self._lock:
            providers = tuple(self._providers.values())
        filtered = (
            provider
            for provider in providers
            if (include_disabled or provider.metadata.enabled)
            and (capability is None or capability in provider.capabilities)
            and (status is None or provider.status is status)
        )
        return tuple(
            sorted(
                filtered,
                key=lambda provider: (
                    int(provider.priority),
                    provider.provider_id.casefold(),
                    provider.provider_id,
                ),
            )
        )

    list_providers = list

    def metadata(self, provider_id: str) -> ProviderMetadata:
        """Return immutable metadata for one provider."""

        return self.get(provider_id).metadata

    def health(self, provider_id: str) -> ProviderHealth:
        """Return immutable externally supplied health for one provider."""

        health = self.get(provider_id).health
        assert health is not None
        return health

    def update_health(self, health: ProviderHealth) -> AIProvider:
        """Atomically replace a provider's immutable health snapshot."""

        if not isinstance(health, ProviderHealth):
            raise TypeError("health must be a ProviderHealth")
        with self._lock:
            provider = self._providers.get(health.provider_id)
            if provider is None:
                raise ProviderNotFoundError(
                    f"provider '{health.provider_id}' is not registered"
                )
            if (
                not provider.metadata.enabled
                and health.status is not ProviderStatus.DISABLED
            ):
                raise ProviderHealthError("disabled providers require disabled health")
            updated = replace(provider, health=health)
            self._providers[provider.provider_id] = updated
            return updated

    def clear(self) -> tuple[AIProvider, ...]:
        """Remove and return every provider atomically."""

        with self._lock:
            removed = tuple(self._providers.values())
            self._providers.clear()
        return tuple(
            sorted(
                removed,
                key=lambda provider: (
                    int(provider.priority),
                    provider.provider_id.casefold(),
                    provider.provider_id,
                ),
            )
        )

    def __contains__(self, provider_id: object) -> bool:
        if not isinstance(provider_id, str):
            return False
        with self._lock:
            return provider_id in self._providers

    def __len__(self) -> int:
        with self._lock:
            return len(self._providers)

    @staticmethod
    def _provider_id(provider_id: object) -> str:
        if (
            not isinstance(provider_id, str)
            or not provider_id
            or provider_id != provider_id.strip()
            or len(provider_id) > 128
        ):
            raise AIValidationError("provider_id must be normalized non-empty text")
        return provider_id


AIProviderRegistry = ProviderRegistry


__all__ = ["AIProviderRegistry", "ProviderRegistry"]
