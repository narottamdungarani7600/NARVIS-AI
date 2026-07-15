"""Compatibility snapshots for legacy Brain providers and Phase 13 AI Core.

The adapters in this module deliberately expose descriptive data only.  The
legacy provider instance remains owned by :class:`AI.brain.BrainEngine`, while
the Phase 13 manager receives detached immutable provider snapshots for
selection, routing, and orchestration planning.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

from Core.logger import LogLevel, Logger, NullLogger

from .core.models import (
    AIProvider,
    ProviderCapability,
    ProviderHealth,
    ProviderMetadata,
    ProviderPriority,
    ProviderStatus,
    utc_now,
)
from .orchestrator.models import (
    ContextSizeMetadata,
    CostMetadata,
    LatencyMetadata,
)
from .providers import (
    ClaudeProvider,
    FallbackProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    Provider,
)


class LegacyProviderCompatibilityError(ValueError):
    """Raised when a legacy provider cannot be represented safely."""


class LegacyProviderRegistrationError(LegacyProviderCompatibilityError):
    """Raised when compatibility registration cannot complete atomically."""


class _ProviderManager(Protocol):
    """Manager operations required by the compatibility registrar."""

    def register_provider(self, provider: object) -> AIProvider:
        """Register one provider descriptor."""

    def unregister_provider(self, provider_id: str) -> AIProvider:
        """Remove one provider descriptor."""

    def list_providers(self) -> tuple[AIProvider, ...]:
        """Return the current immutable registry snapshot."""


@dataclass(slots=True, frozen=True)
class LegacyProviderAdapter:
    """Detached data-only descriptor for one compatible legacy provider."""

    metadata: ProviderMetadata
    health: ProviderHealth

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderMetadata):
            raise TypeError("metadata must be ProviderMetadata")
        if not isinstance(self.health, ProviderHealth):
            raise TypeError("health must be ProviderHealth")
        if self.metadata.provider_id != self.health.provider_id:
            raise ValueError("health must belong to provider metadata")

    @property
    def provider_id(self) -> str:
        """Return the stable legacy provider identifier."""

        return self.metadata.provider_id


@dataclass(slots=True, frozen=True)
class _ProviderProfile:
    """Static compatibility facts for one built-in legacy provider type."""

    provider_type: type[Provider]
    provider_id: str
    display_name: str
    description: str
    default_model: Callable[[], str]
    credential_attribute: str | None = None


_CAPABILITIES = (
    ProviderCapability.CHAT,
    ProviderCapability.TEXT_GENERATION,
)
_CHAIN_PRIORITIES = (
    ProviderPriority.HIGHEST,
    ProviderPriority.HIGH,
    ProviderPriority.NORMAL,
    ProviderPriority.LOW,
    ProviderPriority.LOWEST,
)
_PROFILES = (
    _ProviderProfile(
        OpenAIProvider,
        "openai",
        "OpenAI",
        "Legacy OpenAI-compatible chat provider",
        lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "api_key",
    ),
    _ProviderProfile(
        GeminiProvider,
        "gemini",
        "Google Gemini",
        "Legacy Google Gemini chat provider",
        lambda: "gemini-2.0-flash",
        "api_key",
    ),
    _ProviderProfile(
        ClaudeProvider,
        "claude",
        "Anthropic Claude",
        "Legacy Anthropic Claude chat provider",
        lambda: os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        "api_key",
    ),
    _ProviderProfile(
        OllamaProvider,
        "ollama",
        "Ollama",
        "Legacy local Ollama chat provider",
        lambda: os.getenv("OLLAMA_MODEL", "llama3.2"),
    ),
)
_PROFILE_BY_TYPE = {profile.provider_type: profile for profile in _PROFILES}


class LegacyProviderAdapterFactory:
    """Build safe immutable descriptors without probing or model execution."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock

    def adapt(
        self,
        provider: Provider,
        *,
        priority: ProviderPriority = ProviderPriority.NORMAL,
        fallback_order: int | None = None,
    ) -> LegacyProviderAdapter:
        """Adapt one built-in provider to a detached Phase 13 descriptor."""

        if not isinstance(provider, Provider):
            raise TypeError("provider must be a legacy Provider")
        if not isinstance(priority, ProviderPriority):
            raise TypeError("priority must be a ProviderPriority")
        if isinstance(provider, FallbackProvider):
            raise LegacyProviderCompatibilityError(
                "fallback providers must be adapted as an ordered chain"
            )
        profile = _PROFILE_BY_TYPE.get(type(provider))
        if profile is None:
            raise LegacyProviderCompatibilityError(
                f"unsupported legacy provider type '{type(provider).__name__}'"
            )
        self._validate_provider(provider, profile)
        model = profile.default_model()
        if not isinstance(model, str) or not model or model != model.strip():
            raise LegacyProviderCompatibilityError(
                f"provider '{profile.provider_id}' has an invalid default model"
            )

        checked_at = self._now()
        configured = self._configured(provider, profile)
        attributes: dict[str, object] = {
            "compatibility_adapter": "legacy_provider_v1",
            "legacy_provider_type": type(provider).__name__,
            "cost_metadata": self._cost_metadata(model),
            "latency_metadata": LatencyMetadata(),
            "context_size_metadata": ContextSizeMetadata(),
            "request_timeout_seconds": provider.timeout_seconds,
            "max_retries": provider.max_retries,
            "network_checked": False,
            "local_fallback_available": True,
        }
        if fallback_order is not None:
            if isinstance(fallback_order, bool) or not isinstance(fallback_order, int):
                raise TypeError("fallback_order must be an integer or None")
            if fallback_order < 0:
                raise ValueError("fallback_order must be non-negative")
            attributes["fallback_order"] = fallback_order

        metadata = ProviderMetadata(
            name=profile.provider_id,
            display_name=profile.display_name,
            description=profile.description,
            capabilities=_CAPABILITIES,
            priority=priority,
            supported_models=(model,),
            tags=("legacy", "compatibility", "local-fallback"),
            attributes=attributes,
        )
        health = ProviderHealth(
            provider_id=profile.provider_id,
            status=ProviderStatus.DEGRADED,
            checked_at=checked_at,
            message=self._health_message(provider, profile, configured),
            consecutive_failures=1 if provider.last_error else 0,
            details={
                "configuration_checked": True,
                "credentials_required": profile.credential_attribute is not None,
                "credentials_configured": (
                    configured if profile.credential_attribute is not None else None
                ),
                "network_checked": False,
                "local_fallback_available": True,
                "previous_failure_recorded": bool(provider.last_error),
            },
        )
        return LegacyProviderAdapter(metadata=metadata, health=health)

    def adapt_chain(self, provider: Provider) -> tuple[LegacyProviderAdapter, ...]:
        """Adapt a provider or fallback wrapper while preserving chain order."""

        if not isinstance(provider, Provider):
            raise TypeError("provider must be a legacy Provider")
        providers = self._flatten(provider, seen=set())
        if not providers:
            raise LegacyProviderCompatibilityError(
                "legacy provider chain must contain at least one provider"
            )
        if len(providers) > len(_CHAIN_PRIORITIES):
            raise LegacyProviderCompatibilityError(
                "legacy provider chain exceeds deterministic priority capacity"
            )
        identifiers = tuple(self._profile(item).provider_id for item in providers)
        if len(set(identifiers)) != len(identifiers):
            raise LegacyProviderCompatibilityError(
                "legacy provider chain contains duplicate provider identifiers"
            )
        is_chain = isinstance(provider, FallbackProvider)
        return tuple(
            self.adapt(
                item,
                priority=(
                    _CHAIN_PRIORITIES[index]
                    if is_chain
                    else ProviderPriority.NORMAL
                ),
                fallback_order=index if is_chain else None,
            )
            for index, item in enumerate(providers)
        )

    def _flatten(self, provider: Provider, *, seen: set[int]) -> tuple[Provider, ...]:
        identity = id(provider)
        if identity in seen:
            raise LegacyProviderCompatibilityError(
                "legacy provider chain contains a cycle"
            )
        if not isinstance(provider, FallbackProvider):
            self._profile(provider)
            return (provider,)
        if not isinstance(provider.providers, list) or not provider.providers:
            raise LegacyProviderCompatibilityError(
                "fallback provider must contain a non-empty provider list"
            )
        seen.add(identity)
        try:
            flattened = tuple(
                child
                for item in provider.providers
                for child in self._flatten(item, seen=seen)
            )
        finally:
            seen.remove(identity)
        return flattened

    @staticmethod
    def _profile(provider: Provider) -> _ProviderProfile:
        if not isinstance(provider, Provider):
            raise LegacyProviderCompatibilityError(
                "fallback chain entries must be legacy Provider instances"
            )
        profile = _PROFILE_BY_TYPE.get(type(provider))
        if profile is None:
            raise LegacyProviderCompatibilityError(
                f"unsupported legacy provider type '{type(provider).__name__}'"
            )
        return profile

    @staticmethod
    def _validate_provider(provider: Provider, profile: _ProviderProfile) -> None:
        if provider.name != profile.provider_id:
            raise LegacyProviderCompatibilityError(
                f"provider identity must be '{profile.provider_id}'"
            )
        if not callable(getattr(provider, "complete_chat", None)):
            raise LegacyProviderCompatibilityError(
                f"provider '{profile.provider_id}' has no chat completion method"
            )
        for name in ("timeout_seconds", "max_retries"):
            value = getattr(provider, name, None)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise LegacyProviderCompatibilityError(
                    f"provider '{profile.provider_id}' has invalid {name}"
                )
        base_url = getattr(provider, "base_url", None)
        parsed_url = urlsplit(base_url) if isinstance(base_url, str) else None
        if (
            parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
        ):
            raise LegacyProviderCompatibilityError(
                f"provider '{profile.provider_id}' has invalid base_url"
            )
        if profile.credential_attribute is not None and not isinstance(
            getattr(provider, profile.credential_attribute, None),
            str,
        ):
            raise LegacyProviderCompatibilityError(
                f"provider '{profile.provider_id}' has invalid credential state"
            )

    @staticmethod
    def _configured(provider: Provider, profile: _ProviderProfile) -> bool:
        if profile.credential_attribute is None:
            return True
        return bool(getattr(provider, profile.credential_attribute))

    @staticmethod
    def _cost_metadata(model: str) -> CostMetadata:
        normalized_model = model.casefold()
        if "gpt" in normalized_model or "o4" in normalized_model:
            price_per_1000_tokens = 0.003
        elif "claude" in normalized_model:
            price_per_1000_tokens = 0.0035
        elif "gemini" in normalized_model:
            price_per_1000_tokens = 0.0025
        else:
            price_per_1000_tokens = 0.0015
        return CostMetadata(
            input_cost_per_1000_tokens=price_per_1000_tokens,
            output_cost_per_1000_tokens=price_per_1000_tokens,
        )

    @staticmethod
    def _health_message(
        provider: Provider,
        profile: _ProviderProfile,
        configured: bool,
    ) -> str:
        if provider.last_error:
            return "Remote provider previously failed; local fallback remains available."
        if profile.credential_attribute is not None and not configured:
            return "Remote credentials are not configured; local fallback is available."
        return "Remote availability is unverified; local fallback is available."

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise LegacyProviderCompatibilityError(
                "clock must return a timezone-aware datetime"
            )
        return value


class LegacyProviderRegistrar:
    """Register compatibility descriptors through the existing AI manager."""

    def __init__(
        self,
        manager: _ProviderManager,
        *,
        adapter_factory: LegacyProviderAdapterFactory | None = None,
        logger: Logger | None = None,
    ) -> None:
        if not all(
            callable(getattr(manager, method, None))
            for method in (
                "register_provider",
                "unregister_provider",
                "list_providers",
            )
        ):
            raise TypeError("manager does not implement the provider manager contract")
        factory = adapter_factory or LegacyProviderAdapterFactory()
        if not callable(getattr(factory, "adapt_chain", None)):
            raise TypeError("adapter_factory must provide adapt_chain")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        self._manager = manager
        self._adapter_factory = factory
        self._logger = logger or NullLogger("narvis.ai.compatibility")

    def register(
        self,
        provider: Provider,
        *,
        strict: bool = True,
    ) -> tuple[AIProvider, ...]:
        """Register a complete compatible chain, or leave the registry unchanged."""

        if not isinstance(strict, bool):
            raise TypeError("strict must be a bool")
        try:
            adapters = self._adapter_factory.adapt_chain(provider)
            existing = {
                item.provider_id for item in self._manager.list_providers()
            }
            conflicts = tuple(
                item.provider_id
                for item in adapters
                if item.provider_id in existing
            )
            if conflicts:
                joined = ", ".join(conflicts)
                raise LegacyProviderRegistrationError(
                    f"provider identifiers already registered: {joined}"
                )
        except Exception as error:
            return self._registration_failure(error, strict=strict)

        registered: list[AIProvider] = []
        try:
            for adapter in adapters:
                registered.append(self._manager.register_provider(adapter))
        except Exception as error:
            for item in reversed(registered):
                try:
                    self._manager.unregister_provider(item.provider_id)
                except Exception:
                    pass
            return self._registration_failure(error, strict=strict)
        return tuple(registered)

    def _registration_failure(
        self,
        error: Exception,
        *,
        strict: bool,
    ) -> tuple[AIProvider, ...]:
        self._log(
            LogLevel.WARNING,
            "Legacy AI provider compatibility registration skipped",
            error_type=type(error).__name__,
        )
        if strict:
            if isinstance(error, LegacyProviderCompatibilityError):
                raise error
            raise LegacyProviderRegistrationError(
                "legacy provider compatibility registration failed"
            ) from error
        return ()

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "LegacyProviderAdapter",
    "LegacyProviderAdapterFactory",
    "LegacyProviderCompatibilityError",
    "LegacyProviderRegistrar",
    "LegacyProviderRegistrationError",
]
