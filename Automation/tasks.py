"""Task queue abstractions for the NARVIS Automation package.

This module defines reusable interfaces for queued automation work and is
intentionally generic so future implementations can support local or distributed
queues.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Protocol

from .automation import AutomationAction


class TaskQueue(Protocol):
    """Protocol for task queue services."""

    def enqueue(self, action: AutomationAction) -> None:
        """Add an automation action to the queue."""

    def dequeue(self) -> AutomationAction | None:
        """Remove and return the next automation action from the queue."""


class BaseTaskQueue(ABC):
    """Abstract base class for task queue implementations."""

    @abstractmethod
    def enqueue(self, action: AutomationAction) -> None:
        """Add an automation action to the queue."""

    @abstractmethod
    def dequeue(self) -> AutomationAction | None:
        """Remove and return the next automation action from the queue."""


class InMemoryTaskQueue(BaseTaskQueue):
    """Simple in-memory queue implementation for orchestration flows."""

    def __init__(self) -> None:
        self._queue: deque[AutomationAction] = deque()

    def enqueue(self, action: AutomationAction) -> None:
        """Append an action to the internal queue."""
        self._queue.append(action)

    def dequeue(self) -> AutomationAction | None:
        """Remove and return the next action from the queue."""
        if not self._queue:
            return None
        return self._queue.popleft()
