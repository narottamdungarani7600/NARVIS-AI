"""Clipboard management services for the NARVIS Computer package."""

from __future__ import annotations

import logging

try:
    import pyperclip
except Exception:  # pragma: no cover - optional dependency
    pyperclip = None

class ClipboardManager:
    """Manages clipboard operations."""

    def __init__(self) -> None:
        """Initialize the clipboard manager."""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Clipboard manager initialized")

    def _require_backend(self) -> None:
        """Ensure the clipboard backend is available before use."""
        if pyperclip is None:
            raise RuntimeError("pyperclip is not available")

    def copy(self, text: str) -> None:
        """
        Copy text to clipboard.
        
        Args:
            text: Text to copy
        """
        try:
            self._require_backend()
            pyperclip.copy(text)
            self.logger.debug(f"Copied to clipboard: {text[:50]}...")
        except Exception as e:
            self.logger.error(f"Failed to copy to clipboard: {e}")
            raise

    def paste(self) -> str:
        """
        Get text from clipboard.
        
        Returns:
            Text from clipboard
        """
        try:
            self._require_backend()
            text = pyperclip.paste()
            self.logger.debug(f"Pasted from clipboard: {text[:50]}...")
            return text
        except Exception as e:
            self.logger.error(f"Failed to paste from clipboard: {e}")
            raise

    def clear(self) -> None:
        """Clear the clipboard."""
        try:
            self._require_backend()
            pyperclip.copy("")
            self.logger.debug("Clipboard cleared")
        except Exception as e:
            self.logger.error(f"Failed to clear clipboard: {e}")
            raise

    def shutdown(self) -> None:
        """Shutdown clipboard manager."""
        self.logger.info("Clipboard manager shutdown")
