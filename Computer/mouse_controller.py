"""Mouse control services for the NARVIS Computer package."""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    import pyautogui
except Exception:  # pragma: no cover - optional dependency
    pyautogui = None

@dataclass
class MousePosition:
    """Represents a mouse position."""
    x: int
    y: int


class MouseController:
    """Controls mouse operations on the desktop."""

    def __init__(self) -> None:
        """Initialize the mouse controller."""
        self.logger = logging.getLogger(__name__)
        if pyautogui is not None:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
        else:
            self.logger.warning("pyautogui is not available; mouse automation is disabled")
        self.logger.info("Mouse controller initialized")

    def _require_backend(self) -> None:
        """Ensure the mouse backend is available before use."""
        if pyautogui is None:
            raise RuntimeError("pyautogui is not available")

    def get_position(self) -> MousePosition:
        """Get current mouse position."""
        self._require_backend()
        x, y = pyautogui.position()
        return MousePosition(x=x, y=y)

    def move(self, x: int, y: int, duration: float = 0.5) -> None:
        """
        Move mouse to specified position.
        
        Args:
            x: X coordinate
            y: Y coordinate
            duration: Movement duration in seconds
        """
        try:
            self._require_backend()
            pyautogui.moveTo(x, y, duration=duration)
            self.logger.debug(f"Mouse moved to ({x}, {y})")
        except Exception as e:
            self.logger.error(f"Failed to move mouse: {e}")
            raise

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> None:
        """
        Click mouse button at specified position.
        
        Args:
            x: X coordinate (current position if None)
            y: Y coordinate (current position if None)
            button: Mouse button ("left", "right", "middle")
            clicks: Number of clicks
        """
        try:
            self._require_backend()
            if x is not None and y is not None:
                pyautogui.click(x, y, clicks=clicks, button=button)
            else:
                pyautogui.click(clicks=clicks, button=button)
            self.logger.debug(f"Mouse {button} clicked {clicks} times at ({x}, {y})")
        except Exception as e:
            self.logger.error(f"Failed to click mouse: {e}")
            raise

    def right_click(self, x: int | None = None, y: int | None = None) -> None:
        """Right click at specified position."""
        self.click(x, y, button="right", clicks=1)

    def double_click(self, x: int | None = None, y: int | None = None) -> None:
        """Double click at specified position."""
        self.click(x, y, button="left", clicks=2)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5, button: str = "left") -> None:
        """
        Drag mouse from start position to end position.
        
        Args:
            start_x: Starting X coordinate
            start_y: Starting Y coordinate
            end_x: Ending X coordinate
            end_y: Ending Y coordinate
            duration: Drag duration in seconds
            button: Mouse button to drag with
        """
        try:
            self._require_backend()
            pyautogui.moveTo(start_x, start_y)
            pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, button=button)
            self.logger.debug(f"Mouse dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})")
        except Exception as e:
            self.logger.error(f"Failed to drag mouse: {e}")
            raise

    def scroll(self, amount: int = 3, x: int | None = None, y: int | None = None) -> None:
        """
        Scroll mouse wheel.
        
        Args:
            amount: Number of scroll units (positive=up, negative=down)
            x: X coordinate for scroll
            y: Y coordinate for scroll
        """
        try:
            self._require_backend()
            if x is not None and y is not None:
                pyautogui.moveTo(x, y)
            pyautogui.scroll(amount)
            self.logger.debug(f"Mouse scrolled {amount} units")
        except Exception as e:
            self.logger.error(f"Failed to scroll: {e}")
            raise

    def shutdown(self) -> None:
        """Shutdown mouse controller."""
        self.logger.info("Mouse controller shutdown")
