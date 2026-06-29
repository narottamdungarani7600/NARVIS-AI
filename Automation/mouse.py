"""Mouse control abstractions for the NARVIS Automation package.

This module defines reusable interfaces for mouse input operations and is
intentionally engine-agnostic so future implementations can use platform-
specific libraries without affecting the public architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class MousePosition:
    """Represents a 2D mouse position."""

    x: int
    y: int


class MouseController(Protocol):
    """Protocol for mouse control services."""

    def move(self, position: MousePosition) -> None:
        """Move the mouse pointer to the supplied position."""

    def click(self, button: str = "left") -> None:
        """Perform a mouse click."""


class BaseMouseController(ABC):
    """Abstract base class for mouse controller implementations."""

    @abstractmethod
    def move(self, position: MousePosition) -> None:
        """Move the mouse pointer."""

    @abstractmethod
    def click(self, button: str = "left") -> None:
        """Perform a mouse click."""


class NullMouseController(BaseMouseController):
    """No-op mouse controller used as a placeholder implementation."""

    def move(self, position: MousePosition) -> None:
        """Do nothing."""

    def click(self, button: str = "left") -> None:
        """Do nothing."""
