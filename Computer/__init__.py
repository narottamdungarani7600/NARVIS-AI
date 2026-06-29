"""Computer package for NARVIS.

This package provides desktop-oriented services for applications, windows,
clipboard access, keyboard and mouse control, and screenshot capture. Runtime
adapters are also exposed so the existing Automation and Vision abstractions
can consume these services through the shared dependency injection container.
"""

from .application_manager import ApplicationManager
from .clipboard_manager import ClipboardManager
from .keyboard_controller import KeyboardController
from .mouse_controller import MouseController, MousePosition
from .runtime import (
    ClipboardAutomationAdapter,
    ComputerServices,
    KeyboardAutomationAdapter,
    MouseAutomationAdapter,
    ScreenshotVisionAdapter,
)
from .screenshot_manager import ScreenshotManager
from .window_manager import WindowInfo, WindowManager

__all__ = [
    "ApplicationManager",
    "ClipboardAutomationAdapter",
    "ClipboardManager",
    "ComputerServices",
    "KeyboardAutomationAdapter",
    "KeyboardController",
    "MouseAutomationAdapter",
    "MouseController",
    "MousePosition",
    "ScreenshotManager",
    "ScreenshotVisionAdapter",
    "WindowInfo",
    "WindowManager",
]
