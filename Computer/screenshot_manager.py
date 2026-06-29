"""Screenshot capture services for the NARVIS Computer package."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import ImageGrab
except Exception:  # pragma: no cover - optional dependency
    ImageGrab = None

class ScreenshotManager:
    """Manages screenshot and screen recording operations."""

    def __init__(self, output_dir: str | Path = "screenshots") -> None:
        """
        Initialize the screenshot manager.
        
        Args:
            output_dir: Directory for saving screenshots
        """
        self.logger = logging.getLogger(__name__)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Screenshot manager initialized with output dir: {output_dir}")

    def _require_backend(self) -> None:
        """Ensure screenshot capture is available before use."""
        if ImageGrab is None:
            raise RuntimeError("Pillow ImageGrab is not available")

    def take_screenshot(self, filename: str | None = None) -> Path | None:
        """
        Take a screenshot of the entire screen.
        
        Args:
            filename: Optional filename (auto-generated if None)
            
        Returns:
            Path to saved screenshot or None if failed
        """
        try:
            self._require_backend()
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
            
            filepath = self.output_dir / filename
            screenshot = ImageGrab.grab()
            screenshot.save(filepath)
            self.logger.info(f"Screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {e}")
            return None

    def take_screenshot_region(self, x: int, y: int, width: int, height: int, filename: str | None = None) -> Path | None:
        """
        Take a screenshot of a specific region.
        
        Args:
            x: X coordinate
            y: Y coordinate
            width: Width of region
            height: Height of region
            filename: Optional filename
            
        Returns:
            Path to saved screenshot or None if failed
        """
        try:
            self._require_backend()
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_region_{timestamp}.png"
            
            filepath = self.output_dir / filename
            screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            screenshot.save(filepath)
            self.logger.info(f"Region screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            self.logger.error(f"Failed to take region screenshot: {e}")
            return None

    def get_screen_size(self) -> tuple[int, int]:
        """
        Get screen size.
        
        Returns:
            Tuple of (width, height)
        """
        try:
            self._require_backend()
            size = ImageGrab.grab().size
            self.logger.debug(f"Screen size: {size}")
            return size
        except Exception as e:
            self.logger.error(f"Failed to get screen size: {e}")
            return (0, 0)

    def screenshot_to_image(self) -> Any:
        """
        Get screenshot as PIL Image object.
        
        Returns:
            PIL Image object
        """
        try:
            self._require_backend()
            image = ImageGrab.grab()
            self.logger.debug("Screenshot captured as image")
            return image
        except Exception as e:
            self.logger.error(f"Failed to capture screenshot as image: {e}")
            return None

    def shutdown(self) -> None:
        """Shutdown screenshot manager."""
        self.logger.info("Screenshot manager shutdown")
