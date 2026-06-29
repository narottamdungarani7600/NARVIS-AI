"""Startup orchestration abstractions for NARVIS Core.

This module defines reusable startup hooks and a manager that can coordinate
initialization flows for future subsystems such as Voice, Vision, Memory, and
Automation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class StartupHook(Protocol):
    """Protocol for components that should run during startup."""

    name: str

    def execute(self, context: "StartupContext") -> None:
        """Run the startup action for the current context."""


@dataclass(slots=True)
class StartupContext:
    """Context passed to startup hooks during initialization."""

    config: Any
    logger: Any
    metadata: dict[str, str] = field(default_factory=dict)


class StartupManager:
    """Coordinates initialization hooks in a predictable order."""

    def __init__(self, hooks: list[StartupHook] | None = None) -> None:
        self._hooks: list[StartupHook] = list(hooks or [])

    def register(self, hook: StartupHook) -> None:
        """Register a startup hook."""
        self._hooks.append(hook)

    def run(self, context: StartupContext) -> None:
        """Execute all registered hooks with the provided startup context."""
        for hook in self._hooks:
            if hasattr(hook, "execute"):
                hook.execute(context)
            elif callable(hook):
                hook(context)
            else:
                raise TypeError(f"Unsupported startup hook type: {type(hook)!r}")

    def clear(self) -> None:
        """Remove all registered startup hooks."""
        self._hooks.clear()
