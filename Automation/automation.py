"""Core automation abstractions for the NARVIS Automation package.

This module defines reusable contracts for automation-oriented services such as
mouse, keyboard, clipboard, file, folder, scheduling, and workflow execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class AutomationAction:
    """Represents a single automation action to be executed."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class AutomationExecutor(Protocol):
    """Protocol for executing automation actions."""

    def execute(self, action: AutomationAction) -> None:
        """Execute a single automation action."""
