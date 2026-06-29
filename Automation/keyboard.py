"""Keyboard control abstractions for the NARVIS Automation package.

This module defines reusable interfaces for keyboard operations and keeps the
architecture free from any specific automation library or operating system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class KeyboardController(Protocol):
    """Protocol for keyboard control services."""

    def type_text(self, text: str) -> None:
        """Type a text string."""

    def press_key(self, key: str) -> None:
        """Press a single key."""


class BaseKeyboardController(ABC):
    """Abstract base class for keyboard controller implementations."""

    @abstractmethod
    def type_text(self, text: str) -> None:
        """Type a text string."""

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Press a single key."""


class NullKeyboardController(BaseKeyboardController):
    """No-op keyboard controller used as a placeholder implementation."""

    def type_text(self, text: str) -> None:
        """Do nothing."""

    def press_key(self, key: str) -> None:
        """Do nothing."""
