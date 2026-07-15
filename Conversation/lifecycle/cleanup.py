"""Pure retention evaluation and immutable conversation context cleanup."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from Conversation.core.models import (
    ConversationContext,
    ConversationSession,
    ConversationStatus,
)

from .exceptions import CleanupError
from .models import (
    ArchiveMetadata,
    CleanupCandidate,
    CleanupReason,
    ContextCleanupPolicy,
    RetentionPolicy,
)


class ConversationCleanupService:
    """Evaluate lifecycle retention and clear transient context without I/O."""

    def due_for_expiration(
        self,
        session: ConversationSession,
        policy: RetentionPolicy,
        *,
        last_accessed_at: datetime,
        now: datetime,
    ) -> bool:
        """Return whether explicit or policy expiration has become due."""

        self._inputs(session, policy, last_accessed_at, now)
        if session.status in {
            ConversationStatus.ARCHIVED,
            ConversationStatus.EXPIRED,
        }:
            return False
        deadlines = []
        if session.expires_at is not None:
            deadlines.append(session.expires_at)
        if policy.max_age is not None:
            deadlines.append(session.created_at + policy.max_age)
        if policy.inactive_timeout is not None:
            deadlines.append(last_accessed_at + policy.inactive_timeout)
        return any(deadline <= now for deadline in deadlines)

    def candidates(
        self,
        sessions: Sequence[ConversationSession],
        policy: RetentionPolicy,
        *,
        last_accessed: Mapping[str, datetime],
        archives: Mapping[str, ArchiveMetadata],
        current_session_id: str | None,
        now: datetime,
    ) -> tuple[CleanupCandidate, ...]:
        """Return deterministic cleanup decisions without modifying any store."""

        if not isinstance(policy, RetentionPolicy):
            raise TypeError("policy must be a RetentionPolicy")
        self._aware(now, "now")
        values = tuple(sessions)
        if any(not isinstance(session, ConversationSession) for session in values):
            raise TypeError("sessions must contain ConversationSession values")
        selected: dict[str, CleanupCandidate] = {}
        for session in values:
            if policy.preserve_current and session.session_id == current_session_id:
                continue
            candidate = self._retention_candidate(
                session,
                policy,
                archives.get(session.session_id),
                now,
            )
            if candidate is not None:
                selected[session.session_id] = candidate

        if policy.max_sessions is not None:
            remaining = [
                session
                for session in values
                if session.session_id not in selected
                and not (
                    policy.preserve_current and session.session_id == current_session_id
                )
            ]
            retained_count = len(values) - len(selected)
            overflow = max(0, retained_count - policy.max_sessions)
            oldest = sorted(
                remaining,
                key=lambda session: (
                    last_accessed.get(session.session_id, session.updated_at),
                    session.created_at,
                    session.session_id,
                ),
            )
            for session in oldest[:overflow]:
                selected[session.session_id] = CleanupCandidate(
                    session_id=session.session_id,
                    reason=CleanupReason.SESSION_LIMIT,
                    eligible_at=now,
                )
        return tuple(
            sorted(
                selected.values(),
                key=lambda candidate: (
                    candidate.eligible_at,
                    candidate.session_id,
                ),
            )
        )

    def cleanup_context(
        self,
        session: ConversationSession,
        policy: ContextCleanupPolicy | None = None,
        *,
        cleaned_at: datetime,
    ) -> ConversationSession:
        """Return a snapshot with selected transient context fields removed."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        resolved = policy or ContextCleanupPolicy()
        if not isinstance(resolved, ContextCleanupPolicy):
            raise TypeError("policy must be a ContextCleanupPolicy")
        timestamp = self._aware(cleaned_at, "cleaned_at")
        if timestamp < session.updated_at:
            raise CleanupError("cleaned_at cannot precede the latest session update")
        current = session.context
        context = ConversationContext(
            conversation_id=session.session_id,
            active_topic="" if resolved.clear_topics else current.active_topic,
            previous_topic="" if resolved.clear_topics else current.previous_topic,
            referenced_skills=(
                () if resolved.clear_references else current.referenced_skills
            ),
            referenced_agents=(
                () if resolved.clear_references else current.referenced_agents
            ),
            summary="" if resolved.clear_summary else current.summary,
            metadata={} if resolved.clear_metadata else current.metadata,
            updated_at=timestamp,
            referenced_memories=(
                () if resolved.clear_references else current.referenced_memories
            ),
        )
        return replace(session, context=context, updated_at=timestamp)

    @staticmethod
    def _retention_candidate(
        session: ConversationSession,
        policy: RetentionPolicy,
        archive: ArchiveMetadata | None,
        now: datetime,
    ) -> CleanupCandidate | None:
        if (
            session.status is ConversationStatus.EXPIRED
            and policy.expired_retention is not None
        ):
            assert session.expired_at is not None
            eligible = session.expired_at + policy.expired_retention
            if eligible <= now:
                return CleanupCandidate(
                    session.session_id,
                    CleanupReason.EXPIRED,
                    eligible,
                )
        if (
            session.status is ConversationStatus.CLOSED
            and policy.closed_retention is not None
        ):
            assert session.closed_at is not None
            eligible = session.closed_at + policy.closed_retention
            if eligible <= now:
                return CleanupCandidate(
                    session.session_id,
                    CleanupReason.CLOSED_RETENTION,
                    eligible,
                )
        if (
            session.status is ConversationStatus.ARCHIVED
            and policy.archived_retention is not None
        ):
            assert session.archived_at is not None
            eligible = session.archived_at + policy.archived_retention
            if archive is not None and archive.retention_until is not None:
                eligible = max(eligible, archive.retention_until)
            if eligible <= now:
                return CleanupCandidate(
                    session.session_id,
                    CleanupReason.ARCHIVED_RETENTION,
                    eligible,
                )
        return None

    @classmethod
    def _inputs(
        cls,
        session: object,
        policy: object,
        last_accessed_at: object,
        now: object,
    ) -> None:
        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        if not isinstance(policy, RetentionPolicy):
            raise TypeError("policy must be a RetentionPolicy")
        cls._aware(last_accessed_at, "last_accessed_at")
        cls._aware(now, "now")

    @staticmethod
    def _aware(value: object, name: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise CleanupError(f"{name} must be a timezone-aware datetime")
        return value


CleanupService = ConversationCleanupService


__all__ = ["CleanupService", "ConversationCleanupService"]
