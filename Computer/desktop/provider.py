"""Abstract provider contracts for desktop state inspection."""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable

from ..core.provider import ComputerProvider
from .models import (
    DisplayInfo,
    KeyboardState,
    MouseButtons,
    MousePosition,
    WindowInfo,
)


@runtime_checkable
class DisplayProvider(Protocol):
    """Narrow contract for display metadata enumeration."""

    def enumerate_displays(self) -> tuple[DisplayInfo, ...]:
        """Return a display metadata snapshot."""


@runtime_checkable
class WindowProvider(Protocol):
    """Narrow contract for window metadata enumeration."""

    def enumerate_windows(self) -> tuple[WindowInfo, ...]:
        """Return a window metadata snapshot."""


@runtime_checkable
class MouseProvider(Protocol):
    """Narrow contract for read-only pointer state."""

    def get_mouse_position(self) -> MousePosition:
        """Return current pointer coordinates without moving it."""

    def get_mouse_buttons(self) -> MouseButtons:
        """Return current pointer button state without injecting input."""


@runtime_checkable
class KeyboardProvider(Protocol):
    """Narrow contract for read-only keyboard state."""

    def get_keyboard_state(self) -> KeyboardState:
        """Return current keyboard state without injecting input."""


@runtime_checkable
class DesktopInspectionProvider(
    DisplayProvider,
    WindowProvider,
    MouseProvider,
    KeyboardProvider,
    Protocol,
):
    """Structural contract combining all desktop inspection features."""


class DesktopProvider(ComputerProvider):
    """Computer provider specialization for desktop metadata and state.

    The contract is intentionally inspection-only. Platform implementations
    may report displays, windows, pointer state, and keyboard state, but this
    abstraction exposes no capture, activation, movement, resize, or input
    injection operation.
    """

    @abstractmethod
    def enumerate_displays(self) -> tuple[DisplayInfo, ...]:
        """Return display metadata only."""

    @abstractmethod
    def enumerate_windows(self) -> tuple[WindowInfo, ...]:
        """Return window metadata only."""

    @abstractmethod
    def get_mouse_position(self) -> MousePosition:
        """Return current pointer coordinates."""

    @abstractmethod
    def get_mouse_buttons(self) -> MouseButtons:
        """Return current pointer button state."""

    @abstractmethod
    def get_keyboard_state(self) -> KeyboardState:
        """Return current keyboard state."""


def provider_name(provider: object) -> str:
    """Return an injected provider's stable name when one is available."""

    info = getattr(provider, "info", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(provider).__name__


__all__ = [
    "DesktopInspectionProvider",
    "DesktopProvider",
    "DisplayProvider",
    "KeyboardProvider",
    "MouseProvider",
    "WindowProvider",
]
