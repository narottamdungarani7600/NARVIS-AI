"""Interface-only desktop integration foundation for NARVIS."""

from .display import DisplayManager
from .exceptions import (
    DesktopIntegrationError,
    DesktopRequestError,
    DisplayManagerError,
    DisplayRequestError,
    KeyboardInterfaceError,
    KeyboardRequestError,
    MouseInterfaceError,
    MouseRequestError,
    WindowManagerError,
    WindowRequestError,
)
from .keyboard import KeyboardInterface
from .models import (
    DisplayInfo,
    Key,
    KeyboardKey,
    KeyboardState,
    ModifierKey,
    ModifierKeys,
    MouseButton,
    MouseButtons,
    MousePosition,
    PointerState,
    WindowInfo,
    WindowState,
)
from .mouse import MouseInterface
from .provider import (
    DesktopInspectionProvider,
    DesktopProvider,
    DisplayProvider,
    KeyboardProvider,
    MouseProvider,
    WindowProvider,
)
from .window import WindowManager

# Explicit aliases avoid ambiguity with the legacy Computer controllers.
DesktopDisplayManager = DisplayManager
DesktopKeyboardInterface = KeyboardInterface
DesktopMouseInterface = MouseInterface
DesktopWindowManager = WindowManager

__all__ = [
    "DesktopDisplayManager",
    "DesktopInspectionProvider",
    "DesktopIntegrationError",
    "DesktopKeyboardInterface",
    "DesktopMouseInterface",
    "DesktopProvider",
    "DesktopRequestError",
    "DesktopWindowManager",
    "DisplayInfo",
    "DisplayManager",
    "DisplayManagerError",
    "DisplayProvider",
    "DisplayRequestError",
    "Key",
    "KeyboardInterface",
    "KeyboardInterfaceError",
    "KeyboardKey",
    "KeyboardProvider",
    "KeyboardRequestError",
    "KeyboardState",
    "ModifierKey",
    "ModifierKeys",
    "MouseButton",
    "MouseButtons",
    "MouseInterface",
    "MouseInterfaceError",
    "MousePosition",
    "MouseProvider",
    "MouseRequestError",
    "PointerState",
    "WindowInfo",
    "WindowManager",
    "WindowManagerError",
    "WindowProvider",
    "WindowRequestError",
    "WindowState",
]
