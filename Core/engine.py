"""Core execution abstractions for NARVIS.

This module defines the foundational engine interfaces and execution context
that future modules can implement without introducing AI-specific behavior.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class EngineStatus(str, Enum):
    """States that an engine can occupy."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(slots=True)
class ExecutionContext:
    """Container for context data used during engine execution."""

    request_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class BaseEngine(ABC):
    """Abstract base class for reusable execution engines."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.status: EngineStatus = EngineStatus.IDLE

    def start(self) -> None:
        """Start the engine if it is not already running."""
        if self.status is EngineStatus.RUNNING:
            return
        self.status = EngineStatus.RUNNING
        self.initialize()

    def stop(self) -> None:
        """Stop the engine and transition it to a stopped state."""
        self.shutdown()
        self.status = EngineStatus.STOPPED

    def pause(self) -> None:
        """Pause the engine if it is currently running."""
        if self.status is EngineStatus.RUNNING:
            self.status = EngineStatus.PAUSED

    def resume(self) -> None:
        """Resume the engine from a paused state."""
        if self.status is EngineStatus.PAUSED:
            self.status = EngineStatus.RUNNING

    @abstractmethod
    def initialize(self) -> None:
        """Perform engine-specific initialization work."""

    @abstractmethod
    def shutdown(self) -> None:
        """Perform engine-specific shutdown work."""

    @abstractmethod
    def execute(self, context: ExecutionContext) -> Any:
        """Execute a unit of work using the provided context."""


class NARVISRuntimeEngine(BaseEngine):
    """Concrete runtime engine that orchestrates bootstrapping and shutdown."""

    def __init__(
        self,
        name: str,
        bootstrap: Callable[[], None] | None = None,
        teardown: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(name)
        self._bootstrap = bootstrap or (lambda: None)
        self._teardown = teardown or (lambda: None)

    def initialize(self) -> None:
        """Run the configured bootstrap callback."""
        self._bootstrap()

    def shutdown(self) -> None:
        """Run the configured teardown callback."""
        self._teardown()

    def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Return a simple execution summary for the current runtime context."""
        return {"status": self.status.value, "request_id": context.request_id}
