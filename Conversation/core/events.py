"""Conversation lifecycle events published through the existing EventBus."""

from __future__ import annotations

from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .models import ConversationSession

CONVERSATION_CREATED_EVENT = "conversation.created"
CONVERSATION_UPDATED_EVENT = "conversation.updated"
CONVERSATION_CLOSED_EVENT = "conversation.closed"
CONVERSATION_RESUMED_EVENT = "conversation.resumed"
CONVERSATION_SUMMARY_GENERATED_EVENT = "conversation.summary_generated"
CONVERSATION_TOPIC_CHANGED_EVENT = "conversation.topic_changed"
CONVERSATION_WINDOW_UPDATED_EVENT = "conversation.window_updated"
CONVERSATION_SEARCH_COMPLETED_EVENT = "conversation.search_completed"


class EventPublisher(Protocol):
    """Minimal dependency-injection contract implemented by EventBus."""

    def publish(self, event: SystemEvent) -> None:
        """Publish one system event."""


class ConversationEvents:
    """Publish non-sensitive conversation lifecycle facts."""

    def __init__(
        self,
        event_bus: EventPublisher | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        """Initialize event and logger dependencies."""

        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.conversation.events")

    def publish(
        self,
        event_name: str,
        session: ConversationSession,
        **extra: object,
    ) -> None:
        """Publish lifecycle state without message content or metadata."""

        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "conversation_id": session.session_id,
            "session_id": session.session_id,
            "status": session.status.value,
            "message_count": session.history.count,
            "resume_count": session.resume_count,
        }
        payload.update(extra)
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish conversation event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failure to alter conversation state."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "CONVERSATION_CLOSED_EVENT",
    "CONVERSATION_CREATED_EVENT",
    "CONVERSATION_RESUMED_EVENT",
    "CONVERSATION_SEARCH_COMPLETED_EVENT",
    "CONVERSATION_SUMMARY_GENERATED_EVENT",
    "CONVERSATION_TOPIC_CHANGED_EVENT",
    "CONVERSATION_UPDATED_EVENT",
    "CONVERSATION_WINDOW_UPDATED_EVENT",
    "ConversationEvents",
    "EventPublisher",
]
