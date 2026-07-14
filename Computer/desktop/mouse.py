"""Read-only mouse state interface with no cursor movement or input."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.interfaces import EventPublisher
from .exceptions import MouseRequestError
from .models import MouseButtons, MousePosition, PointerState
from .provider import MouseProvider, provider_name


_Result = TypeVar("_Result")


class MouseInterface:
    """Request pointer position and button snapshots from a provider."""

    STATE_REQUESTED_EVENT = "desktop.mouse.state_requested"

    def __init__(
        self,
        provider: MouseProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, MouseProvider):
            raise TypeError("provider must implement MouseProvider")
        self._provider = provider
        self._provider_name = provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.desktop.mouse")
        self._event_bus = event_bus

    @property
    def provider(self) -> MouseProvider:
        """Return the injected mouse-state provider."""

        return self._provider

    def get_position(self) -> MousePosition:
        """Return current pointer coordinates without moving the cursor."""

        operation = "get_position"
        self._log_request(operation)
        result = self._request(
            operation,
            self._provider.get_mouse_position,
            MousePosition,
        )
        self._publish(operation, position=result)
        return result

    def position(self) -> MousePosition:
        """Alias for :meth:`get_position`."""

        return self.get_position()

    def get_buttons(self) -> MouseButtons:
        """Return current button state without injecting mouse input."""

        operation = "get_buttons"
        self._log_request(operation)
        result = self._request(
            operation,
            self._provider.get_mouse_buttons,
            MouseButtons,
        )
        self._publish(operation, buttons=result)
        return result

    def buttons(self) -> MouseButtons:
        """Alias for :meth:`get_buttons`."""

        return self.get_buttons()

    def get_state(self) -> PointerState:
        """Return a combined position and button snapshot."""

        operation = "get_state"
        self._log_request(operation)
        position = self._request(
            operation,
            self._provider.get_mouse_position,
            MousePosition,
        )
        buttons = self._request(
            operation,
            self._provider.get_mouse_buttons,
            MouseButtons,
        )
        result = PointerState(position, buttons)
        self._publish(operation, position=position, buttons=buttons)
        return result

    def state(self) -> PointerState:
        """Alias for :meth:`get_state`."""

        return self.get_state()

    def _request(
        self,
        operation: str,
        request: Callable[[], _Result],
        expected_type: type[_Result],
    ) -> _Result:
        try:
            result = request()
            if not isinstance(result, expected_type):
                raise TypeError(f"expected {expected_type.__name__}")
            return result
        except MouseRequestError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise MouseRequestError(
                self._provider_name,
                operation,
                str(error),
            ) from error

    def _publish(
        self,
        operation: str,
        *,
        position: MousePosition | None = None,
        buttons: MouseButtons | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "operation": operation,
            "provider": self._provider_name,
        }
        if position is not None:
            payload.update(
                {
                    "x": position.x,
                    "y": position.y,
                    "display_id": position.display_id,
                }
            )
        if buttons is not None:
            payload["pressed_count"] = len(buttons.pressed)
        try:
            self._event_bus.publish(
                SystemEvent(name=self.STATE_REQUESTED_EVENT, payload=payload)
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish desktop mouse event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Desktop mouse state request",
            operation=operation,
            provider=self._provider_name,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Desktop mouse state request failed",
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


__all__ = ["MouseInterface"]
