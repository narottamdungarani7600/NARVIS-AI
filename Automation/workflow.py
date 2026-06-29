"""Workflow execution abstractions for the NARVIS Automation package.

This module defines reusable interfaces for orchestration flows that combine
multiple automation actions into a single execution unit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .automation import AutomationAction


class Workflow(Protocol):
    """Protocol for workflow orchestrators."""

    def run(self, actions: list[AutomationAction]) -> list[AutomationAction]:
        """Execute an ordered list of automation actions."""


class BaseWorkflow(ABC):
    """Abstract base class for workflow implementations."""

    @abstractmethod
    def run(self, actions: list[AutomationAction]) -> list[AutomationAction]:
        """Execute an ordered list of automation actions."""


class SequentialWorkflow(BaseWorkflow):
    """A simple workflow that executes actions in order without additional logic."""

    def run(self, actions: list[AutomationAction]) -> list[AutomationAction]:
        """Return the provided actions unchanged after a placeholder execution."""
        return list(actions)
