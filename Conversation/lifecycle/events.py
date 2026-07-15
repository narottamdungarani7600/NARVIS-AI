"""Safe lifecycle event publication through the existing EventBus contract."""

from __future__ import annotations

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent
from Conversation.core.events import EventPublisher

CONVERSATION_ARCHIVED_EVENT = "conversation.archived"
CONVERSATION_RESTORED_EVENT = "conversation.restored"
CONVERSATION_CLEANED_EVENT = "conversation.cleaned"
CONVERSATION_EXPIRED_EVENT = "conversation.expired"
CONVERSATION_SESSION_SWITCHED_EVENT = "conversation.session_switched"


class ConversationLifecycleEvents:
    """Publish non-sensitive archive, cleanup, expiration, and switch facts."""

    def __init__(
        self,
        event_bus: EventPublisher | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.conversation.lifecycle.events")

    def publish(
        self,
        event_name: str,
        conversation_id: str | None,
        **payload: object,
    ) -> None:
        """Publish safe lifecycle facts without conversation content or metadata."""

        if self._event_bus is None:
            return
        event_payload: dict[str, object] = {
            "conversation_id": conversation_id,
            "session_id": conversation_id,
            **payload,
        }
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=event_payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish conversation lifecycle event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "CONVERSATION_ARCHIVED_EVENT",
    "CONVERSATION_CLEANED_EVENT",
    "CONVERSATION_EXPIRED_EVENT",
    "CONVERSATION_RESTORED_EVENT",
    "CONVERSATION_SESSION_SWITCHED_EVENT",
    "ConversationLifecycleEvents",
]
