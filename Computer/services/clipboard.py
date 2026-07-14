"""Provider-backed, text-only clipboard information services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.exceptions import ClipboardServiceError
from ..core.interfaces import EventPublisher
from ..core.models import ClipboardMetadata


@runtime_checkable
class ClipboardProvider(Protocol):
    """Platform adapter contract for read-only text clipboard access."""

    def is_available(self) -> bool:
        """Return whether text clipboard inspection is available."""

    def read_text(self) -> str | None:
        """Return clipboard text, or ``None`` when it contains no text."""

    def get_metadata(self) -> ClipboardMetadata:
        """Return clipboard state without returning clipboard content."""


_Result = TypeVar("_Result")


class ClipboardService:
    """Read text clipboard state without exposing any write operation."""

    READ_EVENT = "computer.clipboard.read"

    def __init__(
        self,
        provider: ClipboardProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, ClipboardProvider):
            raise TypeError("provider must implement ClipboardProvider")
        self._provider = provider
        self._provider_name = _provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.clipboard")
        self._event_bus = event_bus

    @property
    def provider(self) -> ClipboardProvider:
        """Return the injected clipboard information provider."""

        return self._provider

    def is_available(self) -> bool:
        """Return whether read-only text clipboard access is available."""

        operation = "is_available"
        self._log_request(operation)
        result = self._request(operation, self._provider.is_available)
        if not isinstance(result, bool):
            self._raise_invalid_result(operation, "expected bool")
        return result

    def available(self) -> bool:
        """Alias for :meth:`is_available`."""

        return self.is_available()

    def read_text(self) -> str | None:
        """Read text only, returning ``None`` for non-text or empty state."""

        operation = "read_text"
        self._log_request(operation)
        result = self._request(operation, self._provider.read_text)
        if result is not None and not isinstance(result, str):
            self._raise_invalid_result(operation, "expected str or None")
        self._publish(result)
        return result

    def read(self) -> str | None:
        """Alias for :meth:`read_text`."""

        return self.read_text()

    def get_metadata(self) -> ClipboardMetadata:
        """Return non-content clipboard metadata."""

        operation = "get_metadata"
        self._log_request(operation)
        result = self._request(operation, self._provider.get_metadata)
        if not isinstance(result, ClipboardMetadata):
            self._raise_invalid_result(operation, "expected ClipboardMetadata")
        return result

    def metadata(self) -> ClipboardMetadata:
        """Alias for :meth:`get_metadata`."""

        return self.get_metadata()

    def _request(self, operation: str, request: Callable[[], _Result]) -> _Result:
        try:
            return request()
        except ClipboardServiceError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise ClipboardServiceError(
                self._provider_name,
                operation,
                str(error),
            ) from error

    def _raise_invalid_result(self, operation: str, reason: str) -> None:
        error = TypeError(reason)
        self._log_failure(operation, error)
        raise ClipboardServiceError(
            self._provider_name,
            operation,
            reason,
        ) from error

    def _publish(self, text: str | None) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.READ_EVENT,
                    payload={
                        "provider": self._provider_name,
                        "contains_text": text is not None,
                        "text_length": len(text) if text is not None else 0,
                    },
                )
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish clipboard read event",
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Computer clipboard request",
            operation=operation,
            provider=self._provider_name,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Computer clipboard request failed",
            operation=operation,
            provider=self._provider_name,
            error_type=type(error).__name__,
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


def _provider_name(provider: object) -> str:
    info = getattr(provider, "info", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(provider).__name__


__all__ = ["ClipboardProvider", "ClipboardService"]
