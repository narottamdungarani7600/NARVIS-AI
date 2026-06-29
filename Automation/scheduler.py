"""Scheduling abstractions for the NARVIS Automation package.

This module defines reusable interfaces for scheduling tasks and can later be
implemented by local schedulers, cron-like systems, or platform-specific task
services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class ScheduledTask:
    """Represents a task scheduled for execution."""

    name: str
    run_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


class Scheduler(Protocol):
    """Protocol for task scheduling services."""

    def schedule(self, task: ScheduledTask) -> None:
        """Schedule a task for future execution."""

    def cancel(self, name: str) -> None:
        """Cancel a scheduled task by name."""


class BaseScheduler(ABC):
    """Abstract base class for scheduler implementations."""

    @abstractmethod
    def schedule(self, task: ScheduledTask) -> None:
        """Schedule a task for future execution."""

    @abstractmethod
    def cancel(self, name: str) -> None:
        """Cancel a scheduled task by name."""


class NullScheduler(BaseScheduler):
    """No-op scheduler used as a placeholder implementation."""

    def schedule(self, task: ScheduledTask) -> None:
        """Do nothing."""

    def cancel(self, name: str) -> None:
        """Do nothing."""
