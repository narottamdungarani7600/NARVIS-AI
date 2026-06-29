"""Routing abstractions for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .intent import IntentClassification, IntentType


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message through either the Core logger or stdlib logging."""
    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


@dataclass(slots=True)
class ModuleRoute:
    """Describes the logical module selected for execution."""

    name: str
    confidence: float
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Router(Protocol):
    """Protocol for route selection services."""

    def route(self, classification: IntentClassification) -> ModuleRoute:
        """Select a module route for a given intent classification."""


class IntentRouter:
    """Default router that maps intents to logical execution targets."""

    def __init__(
        self,
        routes: dict[IntentType, str] | None = None,
        logger: Any | None = None,
    ) -> None:
        """Initialize the router with optional route overrides."""
        self.logger = logger
        self._routes = routes or {
            IntentType.GREETING: "Core",
            IntentType.QUESTION: "AI",
            IntentType.COMMAND: "Skills",
            IntentType.TASK: "Automation",
            IntentType.STATUS: "Core",
            IntentType.HELP: "Skills",
            IntentType.UNKNOWN: "AI",
        }

    def route(self, classification: IntentClassification) -> ModuleRoute:
        """Return the most appropriate module route for an intent."""
        route_name = self._routes.get(classification.intent, self._routes[IntentType.UNKNOWN])
        reason = classification.reason or f"route selected from {classification.intent.value} intent"
        route = ModuleRoute(
            name=route_name,
            confidence=classification.confidence,
            reason=reason,
            metadata={"intent": classification.intent.value},
        )
        _emit_log(
            self.logger,
            "debug",
            "Selected route",
            route=route.name,
            intent=classification.intent.value,
            confidence=classification.confidence,
        )
        return route
