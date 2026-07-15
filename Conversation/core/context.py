"""Pure immutable context tracking for conversation core."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from .exceptions import ContextValidationError
from .models import ConversationContext, immutable_mapping, utc_now


class ConversationContextTracker:
    """Track topic changes, references, summaries, and immutable metadata."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Initialize the replaceable clock dependency."""

        self._clock = clock

    def create(
        self,
        conversation_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> ConversationContext:
        """Create empty context for one conversation."""

        return ConversationContext(
            conversation_id=conversation_id,
            metadata={} if metadata is None else metadata,
            updated_at=created_at or self._now(),
        )

    def update(
        self,
        context: ConversationContext,
        *,
        active_topic: str | None = None,
        referenced_memories: Iterable[str] | None = None,
        referenced_skills: Iterable[str] | None = None,
        referenced_agents: Iterable[str] | None = None,
        summary: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        replace_references: bool = False,
        updated_at: datetime | None = None,
    ) -> ConversationContext:
        """Return a new context snapshot with deterministic topic tracking."""

        if not isinstance(context, ConversationContext):
            raise TypeError("context must be a ConversationContext")
        if not isinstance(replace_references, bool):
            raise ContextValidationError("replace_references must be a bool")
        timestamp = updated_at or self._now()
        if timestamp < context.updated_at:
            raise ContextValidationError(
                "updated_at cannot precede the existing context"
            )

        next_active = context.active_topic
        next_previous = context.previous_topic
        if active_topic is not None:
            if not isinstance(active_topic, str):
                raise ContextValidationError("active_topic must be a string")
            if active_topic != active_topic.strip() or len(active_topic) > 1024:
                raise ContextValidationError("active_topic must be normalized text")
            if active_topic != context.active_topic:
                next_previous = context.active_topic
                next_active = active_topic

        memories = self._references(
            context.referenced_memories,
            referenced_memories,
            replace_existing=replace_references,
        )
        skills = self._references(
            context.referenced_skills,
            referenced_skills,
            replace_existing=replace_references,
        )
        agents = self._references(
            context.referenced_agents,
            referenced_agents,
            replace_existing=replace_references,
        )
        next_summary = context.summary if summary is None else summary
        if not isinstance(next_summary, str) or len(next_summary) > 20_000:
            raise ContextValidationError(
                "summary must be a string of at most 20000 characters"
            )
        next_metadata = dict(context.metadata)
        if metadata is not None:
            if not isinstance(metadata, Mapping):
                raise ContextValidationError("context metadata must be a mapping")
            try:
                next_metadata.update(immutable_mapping(metadata))
            except (TypeError, ValueError) as error:
                raise ContextValidationError(
                    "context metadata keys must be strings"
                ) from error

        return replace(
            context,
            active_topic=next_active,
            previous_topic=next_previous,
            referenced_memories=memories,
            referenced_skills=skills,
            referenced_agents=agents,
            summary=next_summary,
            metadata=next_metadata,
            updated_at=timestamp,
        )

    def clear(
        self,
        context: ConversationContext,
        *,
        cleared_at: datetime | None = None,
    ) -> ConversationContext:
        """Return empty context bound to the same conversation."""

        if not isinstance(context, ConversationContext):
            raise TypeError("context must be a ConversationContext")
        timestamp = cleared_at or self._now()
        if timestamp < context.updated_at:
            raise ContextValidationError(
                "cleared_at cannot precede the existing context"
            )
        return ConversationContext(
            conversation_id=context.conversation_id,
            updated_at=timestamp,
        )

    @staticmethod
    def _references(
        existing: tuple[str, ...],
        incoming: Iterable[str] | None,
        *,
        replace_existing: bool,
    ) -> tuple[str, ...]:
        """Merge normalized references in stable first-seen order."""

        if incoming is None:
            return existing
        if isinstance(incoming, (str, bytes)):
            raise ContextValidationError(
                "references must be an iterable of identifiers"
            )
        values = tuple(incoming)
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 256
            for value in values
        ):
            raise ContextValidationError(
                "references must contain normalized non-empty strings"
            )
        base = () if replace_existing else existing
        return tuple(dict.fromkeys((*base, *values)))

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ContextValidationError("context clock must return an aware datetime")
        return value


ContextTracker = ConversationContextTracker


__all__ = ["ContextTracker", "ConversationContextTracker"]
