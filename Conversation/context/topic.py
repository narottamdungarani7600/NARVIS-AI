"""Deterministic topic detection and switching models."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
import re
from types import MappingProxyType
from typing import Protocol

from Conversation.core.models import ConversationMessage, MessageRole, utc_now

from .exceptions import TopicDetectionError
from .models import TopicDetection

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "let",
        "me",
        "of",
        "on",
        "or",
        "please",
        "the",
        "this",
        "to",
        "we",
        "what",
        "with",
        "you",
    }
)
_DEFAULT_TOPICS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "agents": ("agent", "agents", "planner"),
        "conversation": ("context", "conversation", "history", "message", "topic"),
        "memory": ("memory", "memories", "recall", "remember"),
        "planning": ("plan", "planning", "workflow"),
        "skills": ("capability", "skill", "skills"),
        "testing": ("pytest", "test", "tests", "testing", "unittest"),
    }
)


class TopicDetector(Protocol):
    """Replaceable contract for local conversation topic detection."""

    def detect(
        self,
        conversation_id: str,
        messages: Iterable[ConversationMessage],
        *,
        current_topic: str = "",
    ) -> TopicDetection:
        """Detect one topic from immutable messages."""


class KeywordTopicDetector:
    """Detect topics with deterministic keyword scoring and no providers."""

    def __init__(
        self,
        topic_keywords: Mapping[str, Iterable[str]] | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        source = _DEFAULT_TOPICS if topic_keywords is None else topic_keywords
        if not isinstance(source, Mapping) or not source:
            raise TopicDetectionError("topic_keywords must be a non-empty mapping")
        normalized: dict[str, tuple[str, ...]] = {}
        for topic, keywords in source.items():
            if not isinstance(topic, str) or not topic or topic != topic.strip():
                raise TopicDetectionError("topic names must be normalized strings")
            if isinstance(keywords, (str, bytes)):
                raise TopicDetectionError("topic keywords must be iterable strings")
            values = tuple(keyword.casefold() for keyword in keywords)
            if not values or any(
                not value or value != value.strip() for value in values
            ):
                raise TopicDetectionError("topic keywords must be normalized strings")
            normalized[topic] = tuple(dict.fromkeys(values))
        self._topic_keywords = MappingProxyType(normalized)
        self._clock = clock

    def detect(
        self,
        conversation_id: str,
        messages: Iterable[ConversationMessage],
        *,
        current_topic: str = "",
    ) -> TopicDetection:
        """Return the strongest configured topic or a stable lexical fallback."""

        values = self._messages(messages, conversation_id)
        relevant = tuple(
            message for message in values if message.role is not MessageRole.SYSTEM
        )
        tokens = [
            token
            for message in relevant
            for token in _TOKEN_PATTERN.findall(message.content.casefold())
        ]
        counts = Counter(token for token in tokens if token not in _STOP_WORDS)
        scores = {
            topic: sum(counts[keyword] for keyword in keywords)
            for topic, keywords in self._topic_keywords.items()
        }
        best_score = max(scores.values(), default=0)
        if best_score:
            topic = min(topic for topic, score in scores.items() if score == best_score)
            matched_keywords = tuple(
                keyword for keyword in self._topic_keywords[topic] if counts[keyword]
            )
            confidence = min(1.0, best_score / max(1, len(relevant)))
        else:
            topic, matched_keywords = self._fallback(relevant)
            confidence = 0.25 if topic else 0.0
        return TopicDetection(
            conversation_id=conversation_id,
            topic=topic or current_topic,
            previous_topic=current_topic,
            confidence=confidence,
            keywords=matched_keywords,
            source_message_ids=tuple(
                dict.fromkeys(message.message_id for message in relevant)
            ),
            detected_at=self._now(),
        )

    @staticmethod
    def _fallback(
        messages: tuple[ConversationMessage, ...],
    ) -> tuple[str, tuple[str, ...]]:
        for message in reversed(messages):
            tokens = tuple(
                token
                for token in _TOKEN_PATTERN.findall(message.content.casefold())
                if token not in _STOP_WORDS and len(token) > 2
            )
            if tokens:
                return tokens[0], (tokens[0],)
        return "", ()

    @staticmethod
    def _messages(
        messages: Iterable[ConversationMessage],
        conversation_id: str,
    ) -> tuple[ConversationMessage, ...]:
        if isinstance(messages, (str, bytes)):
            raise TopicDetectionError(
                "messages must contain ConversationMessage values"
            )
        try:
            values = tuple(messages)
        except TypeError as error:
            raise TopicDetectionError("messages must be iterable") from error
        if any(not isinstance(message, ConversationMessage) for message in values):
            raise TopicDetectionError(
                "messages must contain ConversationMessage values"
            )
        if any(message.conversation_id != conversation_id for message in values):
            raise TopicDetectionError(
                "all messages must belong to the requested conversation"
            )
        return values

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TopicDetectionError("topic clock must return an aware datetime")
        return value


ConversationTopicDetector = KeywordTopicDetector


__all__ = ["ConversationTopicDetector", "KeywordTopicDetector", "TopicDetector"]
