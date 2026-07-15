"""Deterministic, provider-free conversation summarization."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Protocol

from Conversation.core.models import ConversationMessage, utc_now

from .exceptions import SummaryGenerationError
from .models import ConversationSummary


class SummaryGenerator(Protocol):
    """Replaceable contract for provider-free summary generation."""

    def generate(
        self,
        conversation_id: str,
        messages: Iterable[ConversationMessage],
        *,
        active_topic: str = "",
        max_messages: int | None = None,
    ) -> ConversationSummary:
        """Generate one immutable conversation summary."""


class ExtractiveConversationSummarizer:
    """Create bounded role-labelled summaries without AI or network providers."""

    def __init__(
        self,
        *,
        default_max_messages: int = 8,
        max_characters: int = 4000,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if isinstance(default_max_messages, bool) or not isinstance(
            default_max_messages, int
        ):
            raise SummaryGenerationError("default_max_messages must be an integer")
        if not 1 <= default_max_messages <= 10_000:
            raise SummaryGenerationError(
                "default_max_messages must be between 1 and 10000"
            )
        if isinstance(max_characters, bool) or not isinstance(max_characters, int):
            raise SummaryGenerationError("max_characters must be an integer")
        if not 64 <= max_characters <= 20_000:
            raise SummaryGenerationError("max_characters must be between 64 and 20000")
        self._default_max_messages = default_max_messages
        self._max_characters = max_characters
        self._clock = clock

    def generate(
        self,
        conversation_id: str,
        messages: Iterable[ConversationMessage],
        *,
        active_topic: str = "",
        max_messages: int | None = None,
    ) -> ConversationSummary:
        """Summarize the newest bounded messages in chronological order."""

        values = self._messages(messages, conversation_id)
        limit = self._limit(max_messages)
        selected = values[-limit:]
        if selected:
            lines = [
                f"{message.role.value.capitalize()}: {self._compact(message.content)}"
                for message in selected
            ]
            text = self._bounded("\n".join(lines))
        else:
            text = "No conversation messages available."
        return ConversationSummary(
            conversation_id=conversation_id,
            text=text,
            message_count=len(values),
            source_message_ids=tuple(
                dict.fromkeys(message.message_id for message in selected)
            ),
            active_topic=active_topic,
            metadata={
                "strategy": "extractive",
                "source_count": len(selected),
                "truncated": len(selected) < len(values),
            },
            generated_at=self._now(),
        )

    @staticmethod
    def _messages(
        messages: Iterable[ConversationMessage],
        conversation_id: str,
    ) -> tuple[ConversationMessage, ...]:
        if isinstance(messages, (str, bytes)):
            raise SummaryGenerationError(
                "messages must contain ConversationMessage values"
            )
        try:
            values = tuple(messages)
        except TypeError as error:
            raise SummaryGenerationError("messages must be iterable") from error
        if any(not isinstance(message, ConversationMessage) for message in values):
            raise SummaryGenerationError(
                "messages must contain ConversationMessage values"
            )
        if any(message.conversation_id != conversation_id for message in values):
            raise SummaryGenerationError(
                "all messages must belong to the requested conversation"
            )
        return values

    def _limit(self, value: int | None) -> int:
        limit = self._default_max_messages if value is None else value
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 10_000
        ):
            raise SummaryGenerationError("max_messages must be between 1 and 10000")
        return limit

    @staticmethod
    def _compact(content: str) -> str:
        """Collapse whitespace while retaining message wording."""

        return " ".join(content.split())

    def _bounded(self, text: str) -> str:
        if len(text) <= self._max_characters:
            return text
        marker = "…"
        return text[: self._max_characters - len(marker)].rstrip() + marker

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SummaryGenerationError("summary clock must return an aware datetime")
        return value


ConversationSummarizer = ExtractiveConversationSummarizer


__all__ = [
    "ConversationSummarizer",
    "ExtractiveConversationSummarizer",
    "SummaryGenerator",
]
