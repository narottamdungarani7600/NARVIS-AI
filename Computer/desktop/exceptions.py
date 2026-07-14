"""Typed failures for the desktop integration inspection layer."""

from __future__ import annotations

from ..core.exceptions import ComputerServiceError


class DesktopIntegrationError(ComputerServiceError):
    """Base exception for desktop integration failures."""


class DesktopRequestError(DesktopIntegrationError):
    """Base failure for a provider-backed desktop state request."""

    component_name = "desktop"

    def __init__(self, provider_name: str, operation: str, reason: str) -> None:
        self.provider_name = provider_name
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"Unable to complete {self.component_name} request '{operation}' "
            f"with provider '{provider_name}': {reason}"
        )


class DisplayRequestError(DesktopRequestError):
    """Raised when display metadata cannot be requested or validated."""

    component_name = "desktop display"


class WindowRequestError(DesktopRequestError):
    """Raised when window metadata cannot be requested or validated."""

    component_name = "desktop window"


class MouseRequestError(DesktopRequestError):
    """Raised when pointer state cannot be requested or validated."""

    component_name = "desktop mouse"


class KeyboardRequestError(DesktopRequestError):
    """Raised when keyboard state cannot be requested or validated."""

    component_name = "desktop keyboard"


# Manager-oriented aliases retained for discoverability.
DisplayManagerError = DisplayRequestError
WindowManagerError = WindowRequestError
MouseInterfaceError = MouseRequestError
KeyboardInterfaceError = KeyboardRequestError


__all__ = [
    "DesktopIntegrationError",
    "DesktopRequestError",
    "DisplayManagerError",
    "DisplayRequestError",
    "KeyboardInterfaceError",
    "KeyboardRequestError",
    "MouseInterfaceError",
    "MouseRequestError",
    "WindowManagerError",
    "WindowRequestError",
]
