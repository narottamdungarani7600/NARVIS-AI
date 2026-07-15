"""Pure in-memory search over immutable conversation messages."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
import re

from Conversation.core.models import ConversationMessage, MessageRole, utc_now

from .exceptions import SearchValidationError
from .models import (
    ConversationSearchResult,
    SearchMatch,
    SearchMode,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


class ConversationSearch:
    """Search retained message content without indexing, persistence, or I/O."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    def search(
        self,
        conversation_id: str,
        messages: Iterable[ConversationMessage],
        query: str,
        *,
        role: MessageRole | None = None,
        mode: SearchMode = SearchMode.ANY,
        case_sensitive: bool = False,
        limit: int = 20,
    ) -> ConversationSearchResult:
        """Return deterministic ranked matches for a normalized query."""

        values = self._messages(messages, conversation_id)
        normalized_query = self._query(query)
        if role is not None and not isinstance(role, MessageRole):
            raise SearchValidationError("role must be a MessageRole or None")
        if not isinstance(mode, SearchMode):
            raise SearchValidationError("mode must be a SearchMode")
        if not isinstance(case_sensitive, bool):
            raise SearchValidationError("case_sensitive must be a bool")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 10_000
        ):
            raise SearchValidationError("limit must be between 1 and 10000")

        eligible = tuple(
            (index, message)
            for index, message in enumerate(values)
            if role is None or message.role is role
        )
        query_text = normalized_query if case_sensitive else normalized_query.casefold()
        terms = tuple(dict.fromkeys(_TOKEN_PATTERN.findall(query_text)))
        if not terms:
            raise SearchValidationError("query must contain searchable characters")
        matches: list[SearchMatch] = []
        for index, message in eligible:
            content = message.content if case_sensitive else message.content.casefold()
            content_tokens = set(_TOKEN_PATTERN.findall(content))
            matched_terms = tuple(term for term in terms if term in content_tokens)
            phrase_match = query_text in content
            if not self._matches(mode, terms, matched_terms, phrase_match):
                continue
            coverage = len(matched_terms) / len(terms)
            score = 1.0 if phrase_match else min(0.99, coverage)
            matches.append(
                SearchMatch(
                    message=message,
                    message_index=index,
                    score=score,
                    matched_terms=matched_terms or (normalized_query,),
                )
            )
        ranked = tuple(
            sorted(
                matches,
                key=lambda match: (-match.score, -match.message_index),
            )
        )
        return ConversationSearchResult(
            conversation_id=conversation_id,
            query=normalized_query,
            matches=ranked[:limit],
            searched_message_count=len(eligible),
            total_matches=len(ranked),
            mode=mode,
            role=role,
            completed_at=self._now(),
        )

    @staticmethod
    def _matches(
        mode: SearchMode,
        terms: tuple[str, ...],
        matched_terms: tuple[str, ...],
        phrase_match: bool,
    ) -> bool:
        if mode is SearchMode.PHRASE:
            return phrase_match
        if mode is SearchMode.ALL:
            return len(matched_terms) == len(terms)
        return bool(matched_terms) or phrase_match

    @staticmethod
    def _query(value: object) -> str:
        if not isinstance(value, str):
            raise SearchValidationError("query must be a string")
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > 1000:
            raise SearchValidationError(
                "query must be non-empty and at most 1000 characters"
            )
        if any(len(term) > 256 for term in _TOKEN_PATTERN.findall(normalized)):
            raise SearchValidationError("query terms cannot exceed 256 characters")
        return normalized

    @staticmethod
    def _messages(
        messages: Iterable[ConversationMessage],
        conversation_id: str,
    ) -> tuple[ConversationMessage, ...]:
        if isinstance(messages, (str, bytes)):
            raise SearchValidationError(
                "messages must contain ConversationMessage values"
            )
        try:
            values = tuple(messages)
        except TypeError as error:
            raise SearchValidationError("messages must be iterable") from error
        if any(not isinstance(message, ConversationMessage) for message in values):
            raise SearchValidationError(
                "messages must contain ConversationMessage values"
            )
        if any(message.conversation_id != conversation_id for message in values):
            raise SearchValidationError(
                "all messages must belong to the requested conversation"
            )
        return values

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SearchValidationError("search clock must return an aware datetime")
        return value


MessageSearch = ConversationSearch


__all__ = ["ConversationSearch", "MessageSearch"]
