"""Routing abstractions for the NARVIS Brain subsystem.

This module defines reusable route selection interfaces and an implementation
that maps intents to logical execution targets for future modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .intent import IntentClassification, IntentType


@dataclass(slots=True)
class ModuleRoute:
    """Describes the logical module selected for execution."""

    name: str
    confidence: float
    reason: str | None = None


class Router(Protocol):
    """Protocol for route selection services."""

    def route(self, classification: IntentClassification) -> ModuleRoute:
        """Select a module route for a given intent classification."""


class IntentRouter:
    """Default router that maps intents to placeholder module names."""

    def route(self, classification: IntentClassification) -> ModuleRoute:
        """Return the most appropriate module route for an intent."""
        if classification.intent is IntentType.GREETING:
            return ModuleRoute(name="Core", confidence=classification.confidence, reason="greeting")
        if classification.intent is IntentType.QUESTION:
            return ModuleRoute(name="AI", confidence=classification.confidence, reason="question")
        if classification.intent is IntentType.COMMAND:
            return ModuleRoute(name="Skills", confidence=classification.confidence, reason="command")
        if classification.intent is IntentType.TASK:
            return ModuleRoute(name="Automation", confidence=classification.confidence, reason="task")
        if classification.intent is IntentType.STATUS:
            return ModuleRoute(name="Core", confidence=classification.confidence, reason="status")
        if classification.intent is IntentType.HELP:
            return ModuleRoute(name="Skills", confidence=classification.confidence, reason="help")
        return ModuleRoute(name="Core", confidence=0.0, reason="unknown intent")
