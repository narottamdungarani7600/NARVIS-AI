"""Provider-backed, read-only application discovery services."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.exceptions import ApplicationServiceError
from ..core.interfaces import EventPublisher
from ..core.manager import ComputerManager
from ..core.models import ApplicationInfo, ComputerProviderInfo
from ..core.provider import ComputerProvider
from ..core.registry import ComputerRegistry


@runtime_checkable
class InstalledApplicationProvider(Protocol):
    """Optional provider feature for installed-application discovery."""

    def discover_installed_applications(self) -> tuple[ApplicationInfo, ...]:
        """Return installed application metadata."""


@runtime_checkable
class RunningApplicationProvider(Protocol):
    """Optional provider feature for running-application discovery."""

    def discover_running_applications(self) -> tuple[ApplicationInfo, ...]:
        """Return running application metadata."""


@runtime_checkable
class ApplicationDiscoveryProvider(
    InstalledApplicationProvider,
    RunningApplicationProvider,
    Protocol,
):
    """Combined provider contract for both application discovery modes."""


class ApplicationService:
    """Aggregate application metadata from registered supporting providers."""

    DISCOVERED_EVENT = "computer.applications.discovered"

    def __init__(
        self,
        registry: ComputerRegistry | ComputerManager,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if isinstance(registry, ComputerManager):
            registry = registry.registry
        if not isinstance(registry, ComputerRegistry):
            raise TypeError("registry must be a ComputerRegistry or ComputerManager")
        self._registry = registry
        self._logger = logger or NullLogger("narvis.computer.applications")
        self._event_bus = event_bus

    @property
    def registry(self) -> ComputerRegistry:
        """Return the provider registry used for discovery."""

        return self._registry

    def enumerate_registered_providers(self) -> tuple[ComputerProviderInfo, ...]:
        """Return immutable metadata for all registered providers."""

        operation = "enumerate_registered_providers"
        self._log_request(operation)
        providers = tuple(provider.info for provider in self._registry.list())
        self._publish(
            operation,
            count=len(providers),
            provider_count=len(providers),
        )
        return providers

    def registered_providers(self) -> tuple[ComputerProviderInfo, ...]:
        """Alias for :meth:`enumerate_registered_providers`."""

        return self.enumerate_registered_providers()

    def discover_installed_applications(self) -> tuple[ApplicationInfo, ...]:
        """Discover installed applications from providers that support it."""

        return self._discover(
            "discover_installed_applications",
            InstalledApplicationProvider,
        )

    def discover_installed(self) -> tuple[ApplicationInfo, ...]:
        """Alias for :meth:`discover_installed_applications`."""

        return self.discover_installed_applications()

    def discover_running_applications(self) -> tuple[ApplicationInfo, ...]:
        """Discover running applications from providers that support it."""

        return self._discover(
            "discover_running_applications",
            RunningApplicationProvider,
        )

    def discover_running(self) -> tuple[ApplicationInfo, ...]:
        """Alias for :meth:`discover_running_applications`."""

        return self.discover_running_applications()

    def _discover(
        self,
        operation: str,
        provider_contract: type[InstalledApplicationProvider]
        | type[RunningApplicationProvider],
    ) -> tuple[ApplicationInfo, ...]:
        self._log_request(operation)
        applications: list[ApplicationInfo] = []
        supporting_providers = 0
        for provider in self._registry.list():
            if not isinstance(provider, provider_contract):
                continue
            supporting_providers += 1
            applications.extend(self._request_provider(provider, operation))

        discovered = tuple(
            sorted(
                applications,
                key=lambda application: (
                    application.name.casefold(),
                    application.application_id,
                    application.provider_name,
                ),
            )
        )
        self._publish(
            operation,
            count=len(discovered),
            provider_count=supporting_providers,
        )
        return discovered

    def _request_provider(
        self,
        provider: ComputerProvider,
        operation: str,
    ) -> tuple[ApplicationInfo, ...]:
        provider_name = provider.info.name
        try:
            request = getattr(provider, operation)
            result = request()
            if not isinstance(result, tuple):
                raise TypeError("expected tuple[ApplicationInfo, ...]")
            if not all(
                isinstance(application, ApplicationInfo) for application in result
            ):
                raise TypeError("application entries must be ApplicationInfo")
            return result
        except ApplicationServiceError:
            raise
        except Exception as error:
            self._safe_log(
                LogLevel.ERROR,
                "Computer application discovery request failed",
                operation=operation,
                provider=provider_name,
                error_type=type(error).__name__,
            )
            raise ApplicationServiceError(
                provider_name,
                operation,
                str(error),
            ) from error

    def _publish(self, operation: str, **payload: object) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.DISCOVERED_EVENT,
                    payload={"operation": operation, **payload},
                )
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish application discovery event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Computer application request",
            operation=operation,
        )

    def _safe_log(
        self,
        level: LogLevel,
        message: str,
        **context: object,
    ) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "ApplicationDiscoveryProvider",
    "ApplicationService",
    "InstalledApplicationProvider",
    "RunningApplicationProvider",
]
