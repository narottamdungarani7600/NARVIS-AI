"""Provider coordination for the NARVIS Computer service foundation."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from types import MappingProxyType

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import (
    ComputerCapabilityDiscoveryError,
    ComputerProviderAlreadyInitializedError,
    ComputerProviderHealthError,
    ComputerProviderInitializationError,
    ComputerProviderNotInitializedError,
    ComputerProviderShutdownError,
)
from .interfaces import EventPublisher
from .models import ComputerCapability, ComputerHealth, ComputerProviderInfo
from .provider import ComputerProvider
from .registry import ComputerRegistry


class ComputerManager:
    """Coordinate provider registration, lifecycle, health, and discovery.

    The manager delegates only to the four inspection/lifecycle operations on
    an injected provider. It exposes no computer action or execution method.
    """

    INITIALIZED_EVENT = "computer.provider_initialized"
    HEALTH_CHECKED_EVENT = "computer.health_checked"

    def __init__(
        self,
        registry: ComputerRegistry | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if registry is not None and not isinstance(registry, ComputerRegistry):
            raise TypeError("registry must be a ComputerRegistry or None")
        self._logger = logger or NullLogger("narvis.computer.manager")
        self._event_bus = event_bus
        self._registry = (
            registry
            if registry is not None
            else ComputerRegistry(
                logger=logger,
                event_bus=event_bus,
            )
        )
        self._initialized: set[str] = set()
        self._lock = RLock()

    @property
    def registry(self) -> ComputerRegistry:
        """Return the coordinated provider registry."""

        return self._registry

    def register(self, provider: ComputerProvider) -> ComputerProvider:
        """Register one injected provider."""

        return self._registry.register(provider)

    def unregister(self, name: str) -> ComputerProvider:
        """Shut down an active provider, then remove it from the registry."""

        with self._lock:
            if name in self._initialized:
                self.shutdown_provider(name)
            return self._registry.unregister(name)

    def discover(self) -> tuple[ComputerProvider, ...]:
        """Discover registered providers without scanning or OS interaction."""

        return self._registry.discover()

    def find(self, name: str) -> ComputerProvider | None:
        """Find a registered provider."""

        return self._registry.find(name)

    def exists(self, name: str) -> bool:
        """Return whether a provider is registered."""

        return self._registry.exists(name)

    def list(self) -> tuple[ComputerProvider, ...]:
        """List registered providers."""

        return self._registry.list()

    def provider_info(self, name: str) -> ComputerProviderInfo:
        """Return immutable metadata for one registered provider."""

        return self._registry.get(name).info

    def initialize_provider(self, name: str) -> ComputerProvider:
        """Initialize a registered provider exactly once."""

        provider = self._registry.get(name)
        provider_name = provider.info.name
        with self._lock:
            if provider_name in self._initialized:
                raise ComputerProviderAlreadyInitializedError(provider_name)
            try:
                provider.initialize()
            except Exception as error:
                self._log(
                    LogLevel.ERROR,
                    "Computer provider initialization failed",
                    provider=provider_name,
                    error_type=type(error).__name__,
                )
                raise ComputerProviderInitializationError(
                    provider_name,
                    str(error),
                ) from error
            self._initialized.add(provider_name)

        self._log(
            LogLevel.INFO,
            "Computer provider initialized",
            provider=provider_name,
        )
        self._publish(
            self.INITIALIZED_EVENT,
            {
                "name": provider_name,
                "version": provider.info.version,
            },
        )
        return provider

    def initialize_all(self) -> tuple[ComputerProvider, ...]:
        """Initialize each registered provider in deterministic order."""

        initialized: list[ComputerProvider] = []
        for provider in self._registry.list():
            initialized.append(self.initialize_provider(provider.info.name))
        return tuple(initialized)

    def shutdown_provider(self, name: str) -> ComputerProvider:
        """Shut down one initialized provider while preserving retry state."""

        provider = self._registry.get(name)
        provider_name = provider.info.name
        with self._lock:
            if provider_name not in self._initialized:
                raise ComputerProviderNotInitializedError(provider_name)
            try:
                provider.shutdown()
            except Exception as error:
                self._log(
                    LogLevel.ERROR,
                    "Computer provider shutdown failed",
                    provider=provider_name,
                    error_type=type(error).__name__,
                )
                raise ComputerProviderShutdownError(
                    provider_name,
                    str(error),
                ) from error
            self._initialized.remove(provider_name)

        self._log(
            LogLevel.INFO,
            "Computer provider shut down",
            provider=provider_name,
        )
        return provider

    def shutdown_all(self) -> tuple[ComputerProvider, ...]:
        """Shut down initialized providers in reverse registration order."""

        with self._lock:
            names = tuple(
                provider.info.name
                for provider in reversed(self._registry.list())
                if provider.info.name in self._initialized
            )
        return tuple(self.shutdown_provider(name) for name in names)

    def is_initialized(self, name: str) -> bool:
        """Return whether a registered provider is currently initialized."""

        provider = self._registry.get(name)
        with self._lock:
            return provider.info.name in self._initialized

    def health(self, name: str) -> ComputerHealth:
        """Check one provider and publish the resulting health observation."""

        provider = self._registry.get(name)
        provider_name = provider.info.name
        try:
            result = provider.health()
            if not isinstance(result, ComputerHealth):
                raise TypeError("provider health() must return ComputerHealth")
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Computer provider health check failed",
                provider=provider_name,
                error_type=type(error).__name__,
            )
            raise ComputerProviderHealthError(provider_name, str(error)) from error

        self._log(
            LogLevel.INFO,
            "Computer provider health checked",
            provider=provider_name,
            status=result.status.value,
        )
        self._publish(
            self.HEALTH_CHECKED_EVENT,
            {
                "name": provider_name,
                "status": result.status.value,
                "healthy": result.is_healthy,
            },
        )
        return result

    def health_all(self) -> Mapping[str, ComputerHealth]:
        """Return a detached, read-only health snapshot for every provider."""

        results = {
            provider.info.name: self.health(provider.info.name)
            for provider in self._registry.list()
        }
        return MappingProxyType(results)

    def capabilities(self, name: str) -> tuple[ComputerCapability, ...]:
        """Return validated inert capabilities from one provider."""

        provider = self._registry.get(name)
        provider_name = provider.info.name
        try:
            result = provider.capabilities()
            if not isinstance(result, tuple):
                raise TypeError(
                    "provider capabilities() must return a tuple of "
                    "ComputerCapability values"
                )
            if not all(
                isinstance(capability, ComputerCapability)
                for capability in result
            ):
                raise TypeError(
                    "provider capabilities() must contain ComputerCapability values"
                )
        except Exception as error:
            self._log(
                LogLevel.ERROR,
                "Computer provider capability discovery failed",
                provider=provider_name,
                error_type=type(error).__name__,
            )
            raise ComputerCapabilityDiscoveryError(
                provider_name,
                str(error),
            ) from error

        self._log(
            LogLevel.INFO,
            "Computer provider capabilities discovered",
            provider=provider_name,
            capability_count=len(result),
        )
        return result

    def discover_capabilities(
        self,
    ) -> Mapping[str, tuple[ComputerCapability, ...]]:
        """Return provider-keyed capability metadata for every provider."""

        capabilities = {
            provider.info.name: self.capabilities(provider.info.name)
            for provider in self._registry.list()
        }
        return MappingProxyType(capabilities)

    # Descriptive aliases keep the public coordination API easy to discover.
    initialize = initialize_provider
    shutdown = shutdown_provider
    check_health = health
    check_all_health = health_all

    def _publish(self, event_name: str, payload: dict[str, object]) -> None:
        """Publish without allowing subscriber failures to alter state."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish computer manager event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Use the injected Core logger without changing manager behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["ComputerManager"]
