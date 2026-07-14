"""Provider-backed window metadata management without window control."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.interfaces import EventPublisher
from .exceptions import WindowRequestError
from .models import WindowInfo
from .provider import WindowProvider, provider_name


_Result = TypeVar("_Result")


class WindowManager:
    """Enumerate and look up immutable window metadata."""

    ENUMERATED_EVENT = "desktop.windows.enumerated"

    def __init__(
        self,
        provider: WindowProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, WindowProvider):
            raise TypeError("provider must implement WindowProvider")
        self._provider = provider
        self._provider_name = provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.desktop.window")
        self._event_bus = event_bus

    @property
    def provider(self) -> WindowProvider:
        """Return the injected window provider."""

        return self._provider

    def enumerate_windows(self) -> tuple[WindowInfo, ...]:
        """Return a deterministic window metadata snapshot."""

        return self._enumerate("enumerate_windows")

    def list_windows(self) -> tuple[WindowInfo, ...]:
        """Alias for :meth:`enumerate_windows`."""

        return self.enumerate_windows()

    def windows(self) -> tuple[WindowInfo, ...]:
        """Alias for :meth:`enumerate_windows`."""

        return self.enumerate_windows()

    def get_window(self, window_id: str) -> WindowInfo | None:
        """Look up a window by its stable provider identifier."""

        operation = "get_window"
        self._log_request(operation, window_id=window_id)
        valid_id = _validate_text(window_id, "window_id")
        windows = self._request_windows(operation)
        result = next(
            (window for window in windows if window.window_id == valid_id),
            None,
        )
        self._publish(operation, windows, matched=result is not None)
        return result

    def window_metadata(self, window_id: str) -> WindowInfo | None:
        """Alias for :meth:`get_window`."""

        return self.get_window(window_id)

    def find_by_id(self, window_id: str) -> WindowInfo | None:
        """Alias for :meth:`get_window`."""

        return self.get_window(window_id)

    def find_by_title(self, title: str) -> tuple[WindowInfo, ...]:
        """Return windows having a case-insensitive exact title match."""

        operation = "find_by_title"
        self._log_request(operation, title=title)
        valid_title = _validate_text(title, "window title")
        windows = self._request_windows(operation)
        matches = tuple(
            window
            for window in windows
            if window.title.casefold() == valid_title.casefold()
        )
        self._publish(operation, windows, matched_count=len(matches))
        return matches

    def lookup_window(self, identifier: str) -> WindowInfo | None:
        """Look up the first window matching an id or exact title."""

        operation = "lookup_window"
        self._log_request(operation, identifier=identifier)
        valid_identifier = _validate_text(identifier, "window identifier")
        windows = self._request_windows(operation)
        result = next(
            (
                window
                for window in windows
                if window.window_id == valid_identifier
                or window.title.casefold() == valid_identifier.casefold()
            ),
            None,
        )
        self._publish(operation, windows, matched=result is not None)
        return result

    def lookup(self, identifier: str) -> WindowInfo | None:
        """Alias for :meth:`lookup_window`."""

        return self.lookup_window(identifier)

    def _enumerate(self, operation: str) -> tuple[WindowInfo, ...]:
        self._log_request(operation)
        windows = self._request_windows(operation)
        self._publish(operation, windows)
        return windows

    def _request_windows(self, operation: str) -> tuple[WindowInfo, ...]:
        result = self._request(operation, self._provider.enumerate_windows)
        if not isinstance(result, tuple):
            self._raise_invalid_result(
                operation,
                "expected tuple[WindowInfo, ...]",
            )
        if not all(isinstance(window, WindowInfo) for window in result):
            self._raise_invalid_result(
                operation,
                "window entries must be WindowInfo",
            )
        window_ids = [window.window_id for window in result]
        if len(window_ids) != len(set(window_ids)):
            self._raise_invalid_result(operation, "window ids must be unique")
        return tuple(
            sorted(
                result,
                key=lambda window: (window.window_id, window.title.casefold()),
            )
        )

    def _request(self, operation: str, request: Callable[[], _Result]) -> _Result:
        try:
            return request()
        except WindowRequestError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise WindowRequestError(
                self._provider_name,
                operation,
                str(error),
            ) from error

    def _raise_invalid_result(self, operation: str, reason: str) -> None:
        error = TypeError(reason)
        self._log_failure(operation, error)
        raise WindowRequestError(
            self._provider_name,
            operation,
            reason,
        ) from error

    def _publish(
        self,
        operation: str,
        windows: tuple[WindowInfo, ...],
        **payload: object,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.ENUMERATED_EVENT,
                    payload={
                        "operation": operation,
                        "provider": self._provider_name,
                        "count": len(windows),
                        "active_count": sum(window.is_active for window in windows),
                        "visible_count": sum(
                            window.is_visible for window in windows
                        ),
                        **payload,
                    },
                )
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish desktop window event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str, **context: object) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Desktop window request",
            operation=operation,
            provider=self._provider_name,
            **context,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Desktop window request failed",
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


def _validate_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


__all__ = ["WindowManager"]
