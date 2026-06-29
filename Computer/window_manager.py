"""Window management services for the NARVIS Computer package."""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover - optional dependency
    gw = None

@dataclass
class WindowInfo:
    """Information about a window."""
    title: str
    x: int
    y: int
    width: int
    height: int
    is_maximized: bool
    is_minimized: bool
    is_active: bool


class WindowManager:
    """Manages window operations."""

    def __init__(self) -> None:
        """Initialize the window manager."""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Window manager initialized")

    def _backend_available(self) -> bool:
        """Return whether the window-management backend is ready."""
        if gw is None:
            self.logger.warning("pygetwindow is not available; window automation is disabled")
            return False
        return True

    def get_all_windows(self) -> list[WindowInfo]:
        """
        Get all open windows.
        
        Returns:
            List of WindowInfo objects
        """
        try:
            if not self._backend_available():
                return []
            windows = gw.getAllWindows()
            result = []
            for win in windows:
                result.append(WindowInfo(
                    title=win.title,
                    x=win.left,
                    y=win.top,
                    width=win.width,
                    height=win.height,
                    is_maximized=win.isMaximized,
                    is_minimized=win.isMinimized,
                    is_active=win.isActive
                ))
            self.logger.debug(f"Found {len(result)} windows")
            return result
        except Exception as e:
            self.logger.error(f"Failed to get windows: {e}")
            return []

    def get_window(self, title: str) -> WindowInfo | None:
        """
        Get window by title.
        
        Args:
            title: Window title
            
        Returns:
            WindowInfo or None if not found
        """
        try:
            if not self._backend_available():
                return None
            windows = gw.getWindowsWithTitle(title)
            if windows:
                win = windows[0]
                return WindowInfo(
                    title=win.title,
                    x=win.left,
                    y=win.top,
                    width=win.width,
                    height=win.height,
                    is_maximized=win.isMaximized,
                    is_minimized=win.isMinimized,
                    is_active=win.isActive
                )
            self.logger.debug(f"Window not found: {title}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get window: {e}")
            return None

    def focus_window(self, title: str) -> bool:
        """
        Focus window by title.
        
        Args:
            title: Window title
            
        Returns:
            True if successful
        """
        try:
            if not self._backend_available():
                return False
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].activate()
                self.logger.debug(f"Focused window: {title}")
                return True
            self.logger.warning(f"Window not found for focus: {title}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to focus window: {e}")
            return False

    def close_window(self, title: str) -> bool:
        """
        Close window by title.
        
        Args:
            title: Window title
            
        Returns:
            True if successful
        """
        try:
            if not self._backend_available():
                return False
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].close()
                self.logger.debug(f"Closed window: {title}")
                return True
            self.logger.warning(f"Window not found for close: {title}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to close window: {e}")
            return False

    def minimize_window(self, title: str) -> bool:
        """
        Minimize window by title.
        
        Args:
            title: Window title
            
        Returns:
            True if successful
        """
        try:
            if not self._backend_available():
                return False
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].minimize()
                self.logger.debug(f"Minimized window: {title}")
                return True
            self.logger.warning(f"Window not found for minimize: {title}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to minimize window: {e}")
            return False

    def maximize_window(self, title: str) -> bool:
        """
        Maximize window by title.
        
        Args:
            title: Window title
            
        Returns:
            True if successful
        """
        try:
            if not self._backend_available():
                return False
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].maximize()
                self.logger.debug(f"Maximized window: {title}")
                return True
            self.logger.warning(f"Window not found for maximize: {title}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to maximize window: {e}")
            return False

    def resize_window(self, title: str, width: int, height: int) -> bool:
        """
        Resize window by title.
        
        Args:
            title: Window title
            width: New width
            height: New height
            
        Returns:
            True if successful
        """
        try:
            if not self._backend_available():
                return False
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].resize(width, height)
                self.logger.debug(f"Resized window: {title} to {width}x{height}")
                return True
            self.logger.warning(f"Window not found for resize: {title}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to resize window: {e}")
            return False

    def move_window(self, title: str, x: int, y: int) -> bool:
        """
        Move window by title.
        
        Args:
            title: Window title
            x: New X position
            y: New Y position
            
        Returns:
            True if successful
        """
        try:
            if not self._backend_available():
                return False
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].moveTo(x, y)
                self.logger.debug(f"Moved window: {title} to ({x}, {y})")
                return True
            self.logger.warning(f"Window not found for move: {title}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to move window: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown window manager."""
        self.logger.info("Window manager shutdown")
