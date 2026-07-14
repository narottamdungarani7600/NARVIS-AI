"""Pure immutable conversation history operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from .exceptions import MessageValidationError
from .models import (
    ConversationHistory,
    ConversationMessage,
    MessageRole,
    utc_now,
)


class ConversationHistoryManager:
    """Create, append, query, and clear immutable message histories."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Initialize the replaceable clock dependency."""

        self._clock = clock

    def create(
        self,
        conversation_id: str,
        *,
        created_at: datetime | None = None,
    ) -> ConversationHistory:
        """Create one empty immutable history."""

        timestamp = created_at or self._now()
        return ConversationHistory(
            conversation_id=conversation_id,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def append(
        self,
        history: ConversationHistory,
        message: ConversationMessage,
    ) -> ConversationHistory:
        """Return a new history snapshot containing ``message``."""

        if not isinstance(history, ConversationHistory):
            raise TypeError("history must be a ConversationHistory")
        if not isinstance(message, ConversationMessage):
            raise TypeError("message must be a ConversationMessage")
        if message.conversation_id != history.conversation_id:
            raise MessageValidationError("message belongs to a different conversation")
        if history.messages and message.timestamp < history.messages[-1].timestamp:
            raise MessageValidationError(
                "message timestamp cannot precede retained history"
            )
        updated_at = max(self._now(), message.timestamp, history.updated_at)
        return replace(
            history,
            messages=(*history.messages, message),
            updated_at=updated_at,
        )

    def clear(
        self,
        history: ConversationHistory,
        *,
        cleared_at: datetime | None = None,
    ) -> ConversationHistory:
        """Return an empty history while retaining the cumulative cleared count."""

        if not isinstance(history, ConversationHistory):
            raise TypeError("history must be a ConversationHistory")
        timestamp = cleared_at or self._now()
        if timestamp < history.updated_at:
            raise MessageValidationError(
                "cleared_at cannot precede the latest history update"
            )
        return replace(
            history,
            messages=(),
            cleared_messages=history.cleared_messages + len(history.messages),
            updated_at=timestamp,
        )

    @staticmethod
    def messages(
        history: ConversationHistory,
        *,
        role: MessageRole | None = None,
    ) -> tuple[ConversationMessage, ...]:
        """Return all messages or only messages for one typed role."""

        if not isinstance(history, ConversationHistory):
            raise TypeError("history must be a ConversationHistory")
        if role is None:
            return history.messages
        if not isinstance(role, MessageRole):
            raise TypeError("role must be a MessageRole or None")
        return tuple(message for message in history.messages if message.role is role)

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise MessageValidationError("history clock must return an aware datetime")
        return value


HistoryManager = ConversationHistoryManager


__all__ = ["ConversationHistoryManager", "HistoryManager"]
