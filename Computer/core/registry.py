"""Thread-safe provider registry for the NARVIS Computer service layer."""

from __future__ import annotations

from threading import RLock

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import (
    ComputerProviderNotFoundError,
    DuplicateComputerProviderError,
)
from .interfaces import EventPublisher
from .provider import ComputerProvider


class ComputerRegistry:
    """Store injected computer providers under unique metadata names."""

    REGISTERED_EVENT = "computer.provider_registered"

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        self._logger = logger or NullLogger("narvis.computer.registry")
        self._event_bus = event_bus
        self._providers: dict[str, ComputerProvider] = {}
        self._lock = RLock()

    def register(self, provider: ComputerProvider) -> ComputerProvider:
        """Register one provider without replacing an existing provider."""

        if not isinstance(provider, ComputerProvider):
            raise TypeError("registry entries must be ComputerProvider instances")

        name = provider.info.name
        with self._lock:
            if name in self._providers:
                raise DuplicateComputerProviderError(name)
            self._providers[name] = provider

        self._log(
            LogLevel.INFO,
            "Computer provider registered",
            provider=name,
            version=provider.info.version,
        )
        self._publish(
            self.REGISTERED_EVENT,
            {
                "name": name,
                "version": provider.info.version,
            },
        )
        return provider

    def unregister(self, name: str) -> ComputerProvider:
        """Remove and return one registered provider."""

        normalized_name = self._validate_name(name)
        with self._lock:
            try:
                provider = self._providers.pop(normalized_name)
            except KeyError as error:
                raise ComputerProviderNotFoundError(normalized_name) from error

        self._log(
            LogLevel.INFO,
            "Computer provider unregistered",
            provider=normalized_name,
        )
        return provider

    def discover(self) -> tuple[ComputerProvider, ...]:
        """Return a deterministic snapshot of all registered providers."""

        return self.list()

    def find(self, name: str) -> ComputerProvider | None:
        """Find a provider, returning ``None`` when it is absent."""

        normalized_name = self._validate_name(name)
        with self._lock:
            return self._providers.get(normalized_name)

    def get(self, name: str) -> ComputerProvider:
        """Return a provider or raise a typed not-found failure."""

        normalized_name = self._validate_name(name)
        with self._lock:
            try:
                return self._providers[normalized_name]
            except KeyError as error:
                raise ComputerProviderNotFoundError(normalized_name) from error

    def exists(self, name: str) -> bool:
        """Return whether a provider name is registered."""

        return self.find(name) is not None

    def list(self) -> tuple[ComputerProvider, ...]:
        """Return providers ordered by their stable registry names."""

        with self._lock:
            providers = tuple(self._providers.values())
        return tuple(sorted(providers, key=lambda provider: provider.info.name))

    def __len__(self) -> int:
        """Return the number of registered providers."""

        with self._lock:
            return len(self._providers)

    @staticmethod
    def _validate_name(name: object) -> str:
        """Return a normalized provider name or raise a caller error."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("provider name must be a non-empty string")
        if name != name.strip():
            raise ValueError("provider name must not contain surrounding whitespace")
        return name

    def _publish(self, event_name: str, payload: dict[str, object]) -> None:
        """Publish without allowing subscriber failures to roll back state."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish computer registry event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Use the injected Core logger without changing registry behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["ComputerRegistry"]
