"""Runtime integration helpers for the NARVIS Computer package.

The composition root uses these adapters to bridge the concrete desktop
implementations in :mod:`Computer` with the abstract Automation and Vision
contracts used throughout the wider runtime.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from Automation.clipboard import BaseClipboardManager
from Automation.keyboard import BaseKeyboardController
from Automation.mouse import BaseMouseController, MousePosition as AutomationMousePosition
from Vision.screenshot import BaseScreenshotCapture
from Vision.vision import ImageFrame

from .application_manager import ApplicationManager
from .clipboard_manager import ClipboardManager
from .keyboard_controller import KeyboardController
from .mouse_controller import MouseController
from .screenshot_manager import ScreenshotManager
from .window_manager import WindowManager


@dataclass(slots=True)
class ComputerServices:
    """Container for the concrete desktop services registered at runtime."""

    application_manager: ApplicationManager
    clipboard_manager: ClipboardManager
    keyboard_controller: KeyboardController
    mouse_controller: MouseController
    screenshot_manager: ScreenshotManager
    window_manager: WindowManager

    def shutdown(self) -> None:
        """Release resources held by the concrete desktop services."""
        for service in (
            self.screenshot_manager,
            self.window_manager,
            self.mouse_controller,
            self.keyboard_controller,
            self.clipboard_manager,
            self.application_manager,
        ):
            service.shutdown()


class ClipboardAutomationAdapter(BaseClipboardManager):
    """Expose the Computer clipboard through the Automation contract."""

    def __init__(self, manager: ClipboardManager) -> None:
        self._manager = manager

    def read(self) -> str:
        """Read the current clipboard text."""
        return self._manager.paste()

    def write(self, text: str) -> None:
        """Write text to the clipboard."""
        self._manager.copy(text)


class KeyboardAutomationAdapter(BaseKeyboardController):
    """Expose the Computer keyboard controller through the Automation contract."""

    def __init__(self, controller: KeyboardController) -> None:
        self._controller = controller

    def type_text(self, text: str) -> None:
        """Type a string using the concrete keyboard controller."""
        self._controller.type(text)

    def press_key(self, key: str) -> None:
        """Press a single key using the concrete keyboard controller."""
        self._controller.press(key)


class MouseAutomationAdapter(BaseMouseController):
    """Expose the Computer mouse controller through the Automation contract."""

    def __init__(self, controller: MouseController) -> None:
        self._controller = controller

    def move(self, position: AutomationMousePosition) -> None:
        """Move the pointer to the supplied position."""
        self._controller.move(position.x, position.y)

    def click(self, button: str = "left") -> None:
        """Click using the configured mouse button."""
        self._controller.click(button=button)


class ScreenshotVisionAdapter(BaseScreenshotCapture):
    """Expose Computer screenshots through the Vision screenshot contract."""

    def __init__(self, manager: ScreenshotManager) -> None:
        self._manager = manager

    def capture(self) -> ImageFrame:
        """Capture the screen and return a PNG-backed image frame."""
        image = self._manager.screenshot_to_image()
        if image is None:
            return ImageFrame(data=b"")

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ImageFrame(
            data=buffer.getvalue(),
            width=image.width,
            height=image.height,
            format="png",
            metadata={"source": "computer"},
        )
