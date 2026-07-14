"""Read-only keyboard state interface with no key injection."""

from __future__ import annotations

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.interfaces import EventPublisher
from .exceptions import KeyboardRequestError
from .models import KeyboardState
from .provider import KeyboardProvider, provider_name


class KeyboardInterface:
    """Request keyboard state snapshots through an injected provider."""

    STATE_REQUESTED_EVENT = "desktop.keyboard.state_requested"

    def __init__(
        self,
        provider: KeyboardProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, KeyboardProvider):
            raise TypeError("provider must implement KeyboardProvider")
        self._provider = provider
        self._provider_name = provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.desktop.keyboard")
        self._event_bus = event_bus

    @property
    def provider(self) -> KeyboardProvider:
        """Return the injected keyboard-state provider."""

        return self._provider

    def get_state(self) -> KeyboardState:
        """Return keyboard state without injecting any key input."""

        operation = "get_state"
        self._log_request(operation)
        try:
            result = self._provider.get_keyboard_state()
            if not isinstance(result, KeyboardState):
                raise TypeError("expected KeyboardState")
        except KeyboardRequestError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise KeyboardRequestError(
                self._provider_name,
                operation,
                str(error),
            ) from error
        self._publish(operation, result)
        return result

    def state(self) -> KeyboardState:
        """Alias for :meth:`get_state`."""

        return self.get_state()

    def keyboard_state(self) -> KeyboardState:
        """Alias for :meth:`get_state`."""

        return self.get_state()

    def _publish(self, operation: str, state: KeyboardState) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.STATE_REQUESTED_EVENT,
                    payload={
                        "operation": operation,
                        "provider": self._provider_name,
                        "available": state.is_available,
                        "pressed_key_count": len(state.pressed_keys),
                        "active_modifiers": tuple(
                            sorted(
                                modifier.value
                                for modifier in state.modifiers.active
                            )
                        ),
                    },
                )
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish desktop keyboard event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Desktop keyboard state request",
            operation=operation,
            provider=self._provider_name,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Desktop keyboard state request failed",
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


__all__ = ["KeyboardInterface"]
