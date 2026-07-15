"""Bounded immutable conversation window management."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from Conversation.core.models import ConversationMessage, MessageRole, utc_now

from .exceptions import WindowValidationError
from .models import ConversationWindow


class ConversationWindowManager:
    """Build recent-message windows without changing conversation history."""

    def __init__(
        self,
        default_max_messages: int = 20,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._default_max_messages = self._size(
            default_max_messages,
            "default_max_messages",
        )
        self._clock = clock

    @property
    def default_max_messages(self) -> int:
        """Return the configured default window capacity."""

        return self._default_max_messages

    def build(
        self,
        conversation_id: str,
        messages: Iterable[ConversationMessage],
        *,
        max_messages: int | None = None,
        roles: Iterable[MessageRole] | None = None,
    ) -> ConversationWindow:
        """Return the newest eligible messages in their original order."""

        values = self._messages(messages, conversation_id)
        capacity = (
            self._default_max_messages
            if max_messages is None
            else self._size(max_messages, "max_messages")
        )
        included_roles = self._roles(roles)
        eligible = tuple(
            message for message in values if message.role in included_roles
        )
        selected = eligible[-capacity:]
        end = len(eligible)
        start = end - len(selected)
        return ConversationWindow(
            conversation_id=conversation_id,
            messages=selected,
            start_offset=start,
            end_offset=end,
            total_message_count=len(eligible),
            max_messages=capacity,
            included_roles=included_roles,
            updated_at=self._now(),
        )

    update = build

    @staticmethod
    def _size(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise WindowValidationError(f"{name} must be an integer")
        if not 1 <= value <= 10_000:
            raise WindowValidationError(f"{name} must be between 1 and 10000")
        return value

    @staticmethod
    def _roles(values: Iterable[MessageRole] | None) -> tuple[MessageRole, ...]:
        if values is None:
            return tuple(MessageRole)
        if isinstance(values, (str, bytes)):
            raise WindowValidationError("roles must contain MessageRole values")
        try:
            roles = tuple(values)
        except TypeError as error:
            raise WindowValidationError("roles must be iterable") from error
        if not roles or any(not isinstance(role, MessageRole) for role in roles):
            raise WindowValidationError("roles must contain MessageRole values")
        if len(set(roles)) != len(roles):
            raise WindowValidationError("roles cannot contain duplicates")
        return roles

    @staticmethod
    def _messages(
        messages: Iterable[ConversationMessage],
        conversation_id: str,
    ) -> tuple[ConversationMessage, ...]:
        if isinstance(messages, (str, bytes)):
            raise WindowValidationError(
                "messages must contain ConversationMessage values"
            )
        try:
            values = tuple(messages)
        except TypeError as error:
            raise WindowValidationError("messages must be iterable") from error
        if any(not isinstance(message, ConversationMessage) for message in values):
            raise WindowValidationError(
                "messages must contain ConversationMessage values"
            )
        if any(message.conversation_id != conversation_id for message in values):
            raise WindowValidationError(
                "all messages must belong to the requested conversation"
            )
        return values

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise WindowValidationError("window clock must return an aware datetime")
        return value


WindowManager = ConversationWindowManager


__all__ = ["ConversationWindowManager", "WindowManager"]
