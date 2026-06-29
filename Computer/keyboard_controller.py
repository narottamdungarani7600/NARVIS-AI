"""Keyboard control services for the NARVIS Computer package."""

from __future__ import annotations

import logging

try:
    import keyboard
except Exception:  # pragma: no cover - optional dependency
    keyboard = None

try:
    import pyautogui
except Exception:  # pragma: no cover - optional dependency
    pyautogui = None

class KeyboardController:
    """Controls keyboard operations on the desktop."""

    def __init__(self) -> None:
        """Initialize the keyboard controller."""
        self.logger = logging.getLogger(__name__)
        if pyautogui is not None:
            pyautogui.PAUSE = 0.05
        else:
            self.logger.warning("pyautogui is not available; keyboard automation is disabled")
        self.logger.info("Keyboard controller initialized")

    def _require_primary_backend(self) -> None:
        """Ensure the main keyboard backend is available before use."""
        if pyautogui is None:
            raise RuntimeError("pyautogui is not available")

    def type(self, text: str, interval: float = 0.05) -> None:
        """
        Type text using keyboard.
        
        Args:
            text: Text to type
            interval: Interval between keystrokes in seconds
        """
        try:
            self._require_primary_backend()
            pyautogui.typewrite(text, interval=interval)
            self.logger.debug(f"Typed: {text}")
        except Exception as e:
            self.logger.error(f"Failed to type text: {e}")
            raise

    def type_unicode(self, text: str, interval: float = 0.05) -> None:
        """
        Type text with unicode support.
        
        Args:
            text: Text to type
            interval: Interval between keystrokes
        """
        try:
            if pyautogui is not None:
                for char in text:
                    pyautogui.write(char, interval=interval)
            elif keyboard is not None:
                keyboard.write(text)
            else:
                raise RuntimeError("No keyboard backend is available")
            self.logger.debug(f"Typed unicode: {text}")
        except Exception as e:
            if keyboard is None:
                self.logger.error(f"Failed to type unicode text: {e}")
                raise
            keyboard.write(text)
            self.logger.debug(f"Typed unicode (keyboard lib): {text}")

    def press(self, key: str) -> None:
        """
        Press a single key.
        
        Args:
            key: Key name (e.g., "enter", "space", "tab")
        """
        try:
            self._require_primary_backend()
            pyautogui.press(key)
            self.logger.debug(f"Pressed key: {key}")
        except Exception as e:
            self.logger.error(f"Failed to press key: {e}")
            raise

    def hotkey(self, *keys: str) -> None:
        """
        Press a hotkey combination.
        
        Args:
            keys: Key names in sequence (e.g., "ctrl", "c")
        """
        try:
            self._require_primary_backend()
            pyautogui.hotkey(*keys)
            self.logger.debug(f"Pressed hotkey: {'+'.join(keys)}")
        except Exception as e:
            self.logger.error(f"Failed to press hotkey: {e}")
            raise

    def key_down(self, key: str) -> None:
        """
        Hold down a key.
        
        Args:
            key: Key name
        """
        try:
            self._require_primary_backend()
            pyautogui.keyDown(key)
            self.logger.debug(f"Key down: {key}")
        except Exception as e:
            self.logger.error(f"Failed to key down: {e}")
            raise

    def key_up(self, key: str) -> None:
        """
        Release a key.
        
        Args:
            key: Key name
        """
        try:
            self._require_primary_backend()
            pyautogui.keyUp(key)
            self.logger.debug(f"Key up: {key}")
        except Exception as e:
            self.logger.error(f"Failed to key up: {e}")
            raise

    def copy(self) -> None:
        """Copy to clipboard using Ctrl+C."""
        self.hotkey("ctrl", "c")
        self.logger.debug("Copy command sent")

    def paste(self) -> None:
        """Paste from clipboard using Ctrl+V."""
        self.hotkey("ctrl", "v")
        self.logger.debug("Paste command sent")

    def cut(self) -> None:
        """Cut to clipboard using Ctrl+X."""
        self.hotkey("ctrl", "x")
        self.logger.debug("Cut command sent")

    def undo(self) -> None:
        """Undo using Ctrl+Z."""
        self.hotkey("ctrl", "z")
        self.logger.debug("Undo command sent")

    def redo(self) -> None:
        """Redo using Ctrl+Y."""
        self.hotkey("ctrl", "y")
        self.logger.debug("Redo command sent")

    def select_all(self) -> None:
        """Select all using Ctrl+A."""
        self.hotkey("ctrl", "a")
        self.logger.debug("Select all command sent")

    def delete(self) -> None:
        """Press Delete key."""
        self.press("delete")

    def backspace(self) -> None:
        """Press Backspace key."""
        self.press("backspace")

    def shutdown(self) -> None:
        """Shutdown keyboard controller."""
        self.logger.info("Keyboard controller shutdown")
