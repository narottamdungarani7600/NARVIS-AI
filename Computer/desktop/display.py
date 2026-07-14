"""Provider-backed display metadata management without screen capture."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.interfaces import EventPublisher
from .exceptions import DisplayRequestError
from .models import DisplayInfo
from .provider import DisplayProvider, provider_name


_Result = TypeVar("_Result")


class DisplayManager:
    """Enumerate and query display metadata through an injected provider."""

    ENUMERATED_EVENT = "desktop.displays.enumerated"

    def __init__(
        self,
        provider: DisplayProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, DisplayProvider):
            raise TypeError("provider must implement DisplayProvider")
        self._provider = provider
        self._provider_name = provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.desktop.display")
        self._event_bus = event_bus

    @property
    def provider(self) -> DisplayProvider:
        """Return the injected display provider."""

        return self._provider

    def enumerate_displays(self) -> tuple[DisplayInfo, ...]:
        """Return a deterministic display metadata snapshot."""

        return self._enumerate("enumerate_displays")

    def list_displays(self) -> tuple[DisplayInfo, ...]:
        """Alias for :meth:`enumerate_displays`."""

        return self.enumerate_displays()

    def displays(self) -> tuple[DisplayInfo, ...]:
        """Alias for :meth:`enumerate_displays`."""

        return self.enumerate_displays()

    def get_display(self, display_id: str) -> DisplayInfo | None:
        """Look up metadata for one provider display identifier."""

        operation = "get_display"
        self._log_request(operation, display_id=display_id)
        valid_id = _validate_identifier(display_id, "display_id")
        displays = self._request_displays(operation)
        result = next(
            (display for display in displays if display.display_id == valid_id),
            None,
        )
        self._publish(operation, displays, matched=result is not None)
        return result

    def display_metadata(self, display_id: str) -> DisplayInfo | None:
        """Alias for :meth:`get_display`."""

        return self.get_display(display_id)

    def primary_display(self) -> DisplayInfo | None:
        """Return the primary display, or ``None`` for an empty provider."""

        operation = "primary_display"
        self._log_request(operation)
        displays = self._request_displays(operation)
        result = next((display for display in displays if display.is_primary), None)
        self._publish(operation, displays)
        return result

    def get_primary_display(self) -> DisplayInfo | None:
        """Alias for :meth:`primary_display`."""

        return self.primary_display()

    def virtual_displays(self) -> tuple[DisplayInfo, ...]:
        """Return display models explicitly identified as virtual."""

        operation = "virtual_displays"
        self._log_request(operation)
        displays = self._request_displays(operation)
        result = tuple(display for display in displays if display.is_virtual)
        self._publish(operation, displays, matched_count=len(result))
        return result

    def enumerate_virtual_displays(self) -> tuple[DisplayInfo, ...]:
        """Alias for :meth:`virtual_displays`."""

        return self.virtual_displays()

    def _enumerate(self, operation: str) -> tuple[DisplayInfo, ...]:
        self._log_request(operation)
        displays = self._request_displays(operation)
        self._publish(operation, displays)
        return displays

    def _request_displays(self, operation: str) -> tuple[DisplayInfo, ...]:
        result = self._request(operation, self._provider.enumerate_displays)
        if not isinstance(result, tuple):
            self._raise_invalid_result(
                operation,
                "expected tuple[DisplayInfo, ...]",
            )
        if not all(isinstance(display, DisplayInfo) for display in result):
            self._raise_invalid_result(
                operation,
                "display entries must be DisplayInfo",
            )
        display_ids = [display.display_id for display in result]
        if len(display_ids) != len(set(display_ids)):
            self._raise_invalid_result(operation, "display ids must be unique")
        if sum(display.is_primary for display in result) > 1:
            self._raise_invalid_result(
                operation,
                "at most one display may be primary",
            )
        return tuple(
            sorted(
                result,
                key=lambda display: (
                    not display.is_primary,
                    display.x,
                    display.y,
                    display.display_id,
                ),
            )
        )

    def _request(self, operation: str, request: Callable[[], _Result]) -> _Result:
        try:
            return request()
        except DisplayRequestError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise DisplayRequestError(
                self._provider_name,
                operation,
                str(error),
            ) from error

    def _raise_invalid_result(self, operation: str, reason: str) -> None:
        error = TypeError(reason)
        self._log_failure(operation, error)
        raise DisplayRequestError(
            self._provider_name,
            operation,
            reason,
        ) from error

    def _publish(
        self,
        operation: str,
        displays: tuple[DisplayInfo, ...],
        **payload: object,
    ) -> None:
        if self._event_bus is None:
            return
        primary = next(
            (display.display_id for display in displays if display.is_primary),
            None,
        )
        event_payload = {
            "operation": operation,
            "provider": self._provider_name,
            "count": len(displays),
            "primary_display_id": primary,
            "virtual_count": sum(display.is_virtual for display in displays),
            **payload,
        }
        try:
            self._event_bus.publish(
                SystemEvent(name=self.ENUMERATED_EVENT, payload=event_payload)
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish desktop display event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str, **context: object) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Desktop display request",
            operation=operation,
            provider=self._provider_name,
            **context,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Desktop display request failed",
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


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


__all__ = ["DisplayManager"]
