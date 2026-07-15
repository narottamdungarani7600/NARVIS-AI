"""Safe orchestration lifecycle publication through the existing EventBus."""

from __future__ import annotations

from AI.core.interfaces import EventPublisher
from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

AI_SESSION_CREATED_EVENT = "ai.session_created"
AI_PLAN_GENERATED_EVENT = "ai.plan_generated"
AI_PROVIDER_NEGOTIATED_EVENT = "ai.provider_negotiated"
AI_PREFERENCES_RESOLVED_EVENT = "ai.preferences_resolved"
AI_SESSION_COMPLETED_EVENT = "ai.session_completed"


class OrchestrationEvents:
    """Publish non-sensitive orchestration facts without request content."""

    def __init__(
        self,
        event_bus: EventPublisher | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        if event_bus is not None and not callable(getattr(event_bus, "publish", None)):
            raise TypeError("event_bus must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        self._event_bus = event_bus
        self._logger = (
            logger
            if logger is not None
            else NullLogger("narvis.ai.orchestrator.events")
        )

    def publish(self, event_name: str, **payload: object) -> None:
        """Publish safe typed identifiers and aggregate facts."""

        if not isinstance(event_name, str) or not event_name:
            raise ValueError("event_name must be non-empty text")
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=dict(payload)))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish AI orchestration event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "AI_PLAN_GENERATED_EVENT",
    "AI_PREFERENCES_RESOLVED_EVENT",
    "AI_PROVIDER_NEGOTIATED_EVENT",
    "AI_SESSION_COMPLETED_EVENT",
    "AI_SESSION_CREATED_EVENT",
    "OrchestrationEvents",
]
