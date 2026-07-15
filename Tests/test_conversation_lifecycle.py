"""Comprehensive tests for Phase 12 Human Interaction Layer Sprint 3."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Conversation import (
    ArchiveMetadata,
    CleanupCandidate,
    CleanupReason,
    CleanupReport,
    ContextCleanupPolicy,
    ConversationAlreadyArchivedError,
    ConversationArchiveError,
    ConversationArchiveService,
    ConversationCleanupService,
    ConversationClosedError,
    ConversationContext,
    ConversationExpiredError,
    ConversationExportBuilder,
    ConversationExportError,
    ConversationHealth,
    ConversationHistory,
    ConversationManager,
    ConversationNotArchivedError,
    ConversationNotFoundError,
    ConversationSession,
    ConversationStatus,
    ExportFormat,
    HealthStatus,
    InMemoryArchiveRepository,
    MessageRole,
    NoCurrentSessionError,
    RetentionPolicy,
    RetentionPolicyError,
    SessionSwitchError,
    UserMessage,
)


class _Clock:
    """Mutable aware clock for deterministic lifecycle tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _CapturingLogger:
    """Core-compatible structured logger double."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


def _session(
    clock: _Clock,
    *,
    session_id: str = "conversation-001",
    status: ConversationStatus = ConversationStatus.ACTIVE,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    closed_at: datetime | None = None,
    archived_at: datetime | None = None,
    expires_at: datetime | None = None,
    expired_at: datetime | None = None,
) -> ConversationSession:
    created = created_at or clock.now
    updated = updated_at or created
    history = ConversationHistory(
        conversation_id=session_id,
        created_at=created,
        updated_at=updated,
    )
    context = ConversationContext(
        conversation_id=session_id,
        updated_at=updated,
    )
    return ConversationSession(
        session_id=session_id,
        status=status,
        history=history,
        context=context,
        created_at=created,
        updated_at=updated,
        closed_at=closed_at,
        archived_at=archived_at,
        expires_at=expires_at,
        expired_at=expired_at,
    )


class LifecycleModelTests(unittest.TestCase):
    """Verify lifecycle models, new statuses, retention, and immutable facts."""

    def setUp(self) -> None:
        self.clock = _Clock()

    def test_conversation_status_supports_archived_and_expired_snapshots(self) -> None:
        archived = _session(
            self.clock,
            status=ConversationStatus.ARCHIVED,
            archived_at=self.clock.now,
        )
        expired = _session(
            self.clock,
            status=ConversationStatus.EXPIRED,
            expired_at=self.clock.now,
        )

        self.assertTrue(archived.archived)
        self.assertFalse(archived.mutable)
        self.assertTrue(expired.expired)
        with self.assertRaises(ValueError):
            replace(archived, archived_at=None)
        with self.assertRaises(ValueError):
            replace(expired, expired_at=None)

    def test_archive_metadata_is_frozen_and_deeply_immutable(self) -> None:
        source = {"trace": {"steps": [1, 2]}}
        metadata = ArchiveMetadata(
            conversation_id="conversation-001",
            original_status=ConversationStatus.ACTIVE,
            archived_at=self.clock.now,
            reason="completed",
            tags=("phase-12",),
            message_count=2,
            metadata=source,
        )
        source["trace"]["steps"].append(3)

        self.assertTrue(metadata.active)
        self.assertEqual(metadata.metadata["trace"]["steps"], (1, 2))
        with self.assertRaises(FrozenInstanceError):
            metadata.reason = "changed"  # type: ignore[misc]

    def test_archive_metadata_validates_status_retention_and_restoration(self) -> None:
        with self.assertRaises(ValueError):
            ArchiveMetadata(
                conversation_id="conversation-001",
                original_status=ConversationStatus.ARCHIVED,
                archived_at=self.clock.now,
            )
        with self.assertRaises(ValueError):
            ArchiveMetadata(
                conversation_id="conversation-001",
                original_status=ConversationStatus.ACTIVE,
                archived_at=self.clock.now,
                retention_until=self.clock.now - timedelta(seconds=1),
            )

    def test_retention_policy_accepts_zero_and_rejects_invalid_values(self) -> None:
        policy = RetentionPolicy(
            max_age=timedelta(0),
            expired_retention=timedelta(0),
            max_sessions=2,
        )

        self.assertEqual(policy.max_sessions, 2)
        with self.assertRaises(RetentionPolicyError):
            RetentionPolicy(closed_retention=timedelta(seconds=-1))
        with self.assertRaises(RetentionPolicyError):
            RetentionPolicy(max_sessions=0)

    def test_cleanup_report_requires_candidates_to_match_removed_ids(self) -> None:
        candidate = CleanupCandidate(
            "conversation-001",
            CleanupReason.EXPIRED,
            self.clock.now,
        )
        report = CleanupReport(
            examined_sessions=1,
            expired_session_ids=("conversation-001",),
            removed_session_ids=("conversation-001",),
            candidates=(candidate,),
            started_at=self.clock.now,
            completed_at=self.clock.now,
        )

        self.assertEqual(report.expired_count, 1)
        self.assertEqual(report.removed_count, 1)
        with self.assertRaises(ValueError):
            replace(report, removed_session_ids=())

    def test_context_cleanup_policy_requires_at_least_one_cleanup_action(self) -> None:
        with self.assertRaises(ValueError):
            ContextCleanupPolicy(
                clear_topics=False,
                clear_summary=False,
                clear_references=False,
                clear_metadata=False,
            )


class ConversationArchiveTests(unittest.TestCase):
    """Verify in-memory archive generations and restoration metadata."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.ids = iter(("archive-001", "archive-002"))
        self.repository = InMemoryArchiveRepository()
        self.service = ConversationArchiveService(
            self.repository,
            clock=self.clock,
            id_factory=lambda: next(self.ids),
        )

    def test_archive_records_original_status_reason_tags_and_count(self) -> None:
        session = _session(self.clock)

        archive = self.service.archive(
            session,
            reason="completed",
            tags=("release", "phase-12"),
            retention_until=self.clock.now + timedelta(days=30),
            metadata={"source": "test"},
        )

        self.assertEqual(archive.archive_id, "archive-001")
        self.assertIs(archive.original_status, ConversationStatus.ACTIVE)
        self.assertEqual(archive.reason, "completed")
        self.assertEqual(archive.tags, ("release", "phase-12"))
        self.assertEqual(self.service.current(session.session_id), archive)

    def test_restore_retains_archive_history_and_allows_new_generation(self) -> None:
        session = _session(self.clock)
        first = self.service.archive(session)
        self.clock.advance(seconds=1)
        restored = self.service.restore(session.session_id)
        self.clock.advance(seconds=1)
        second = self.service.archive(session, archived_at=self.clock.now)

        self.assertEqual(restored.archive_id, first.archive_id)
        self.assertFalse(restored.active)
        self.assertTrue(second.active)
        self.assertEqual(len(self.service.history(session.session_id)), 2)

    def test_duplicate_archive_and_restore_without_archive_are_typed(self) -> None:
        session = _session(self.clock)
        self.service.archive(session)

        with self.assertRaises(ConversationAlreadyArchivedError):
            self.service.archive(
                replace(
                    session,
                    status=ConversationStatus.ARCHIVED,
                    archived_at=self.clock.now,
                )
            )
        with self.assertRaises(ConversationNotArchivedError):
            self.service.restore("missing")

    def test_expired_sessions_and_string_tags_are_rejected(self) -> None:
        expired = _session(
            self.clock,
            status=ConversationStatus.EXPIRED,
            expired_at=self.clock.now,
        )

        with self.assertRaises(ConversationExpiredError):
            self.service.archive(expired)
        with self.assertRaises(ConversationArchiveError):
            self.service.archive(_session(self.clock), tags="invalid")

    def test_repository_remove_is_in_memory_and_returns_history(self) -> None:
        session = _session(self.clock)
        self.service.archive(session)

        removed = self.service.remove(session.session_id)

        self.assertEqual(len(removed), 1)
        self.assertEqual(self.service.history(session.session_id), ())


class ConversationCleanupTests(unittest.TestCase):
    """Verify pure expiration, retention candidates, limits, and context cleanup."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.service = ConversationCleanupService()

    def test_explicit_max_age_and_inactivity_expiration_are_supported(self) -> None:
        old = self.clock.now - timedelta(hours=2)
        session = _session(
            self.clock,
            created_at=old,
            updated_at=old,
            expires_at=self.clock.now,
        )

        self.assertTrue(
            self.service.due_for_expiration(
                session,
                RetentionPolicy(),
                last_accessed_at=old,
                now=self.clock.now,
            )
        )
        self.assertTrue(
            self.service.due_for_expiration(
                replace(session, expires_at=None),
                RetentionPolicy(max_age=timedelta(hours=1)),
                last_accessed_at=old,
                now=self.clock.now,
            )
        )
        self.assertTrue(
            self.service.due_for_expiration(
                replace(session, expires_at=None),
                RetentionPolicy(inactive_timeout=timedelta(hours=1)),
                last_accessed_at=old,
                now=self.clock.now,
            )
        )

    def test_archived_and_expired_sessions_are_not_expired_again(self) -> None:
        archived = _session(
            self.clock,
            status=ConversationStatus.ARCHIVED,
            archived_at=self.clock.now,
            expires_at=self.clock.now,
        )

        self.assertFalse(
            self.service.due_for_expiration(
                archived,
                RetentionPolicy(max_age=timedelta(0)),
                last_accessed_at=self.clock.now,
                now=self.clock.now,
            )
        )

    def test_status_retention_generates_expected_cleanup_reasons(self) -> None:
        old = self.clock.now - timedelta(days=2)
        expired = _session(
            self.clock,
            session_id="expired",
            status=ConversationStatus.EXPIRED,
            created_at=old,
            updated_at=old,
            expired_at=old,
        )
        closed = _session(
            self.clock,
            session_id="closed",
            status=ConversationStatus.CLOSED,
            created_at=old,
            updated_at=old,
            closed_at=old,
        )
        archived = _session(
            self.clock,
            session_id="archived",
            status=ConversationStatus.ARCHIVED,
            created_at=old,
            updated_at=old,
            archived_at=old,
        )

        candidates = self.service.candidates(
            (expired, closed, archived),
            RetentionPolicy(
                expired_retention=timedelta(days=1),
                closed_retention=timedelta(days=1),
                archived_retention=timedelta(days=1),
            ),
            last_accessed={},
            archives={},
            current_session_id=None,
            now=self.clock.now,
        )

        self.assertEqual(
            {candidate.reason for candidate in candidates},
            {
                CleanupReason.EXPIRED,
                CleanupReason.CLOSED_RETENTION,
                CleanupReason.ARCHIVED_RETENTION,
            },
        )

    def test_archive_retention_until_delays_cleanup(self) -> None:
        old = self.clock.now - timedelta(days=2)
        session = _session(
            self.clock,
            status=ConversationStatus.ARCHIVED,
            created_at=old,
            updated_at=old,
            archived_at=old,
        )
        archive = ArchiveMetadata(
            conversation_id=session.session_id,
            original_status=ConversationStatus.ACTIVE,
            archived_at=old,
            retention_until=self.clock.now + timedelta(days=1),
        )

        candidates = self.service.candidates(
            (session,),
            RetentionPolicy(archived_retention=timedelta(0)),
            last_accessed={},
            archives={session.session_id: archive},
            current_session_id=None,
            now=self.clock.now,
        )

        self.assertEqual(candidates, ())

    def test_session_limit_removes_oldest_and_preserves_current(self) -> None:
        sessions = tuple(
            _session(
                self.clock,
                session_id=f"session-{index}",
                created_at=self.clock.now + timedelta(seconds=index),
                updated_at=self.clock.now + timedelta(seconds=index),
            )
            for index in range(3)
        )

        candidates = self.service.candidates(
            sessions,
            RetentionPolicy(max_sessions=2),
            last_accessed={
                session.session_id: session.updated_at for session in sessions
            },
            archives={},
            current_session_id="session-0",
            now=self.clock.now + timedelta(minutes=1),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].session_id, "session-1")
        self.assertIs(candidates[0].reason, CleanupReason.SESSION_LIMIT)

    def test_context_cleanup_is_selective_and_preserves_original_snapshot(self) -> None:
        session = _session(self.clock)
        context = replace(
            session.context,
            active_topic="testing",
            previous_topic="planning",
            summary="summary",
            referenced_memories=("memory-001",),
            referenced_skills=("skill.test",),
            referenced_agents=("planner",),
            metadata={"trace": 1},
        )
        session = replace(session, context=context)
        self.clock.advance(seconds=1)

        cleaned = self.service.cleanup_context(
            session,
            ContextCleanupPolicy(
                clear_topics=False,
                clear_summary=True,
                clear_references=True,
                clear_metadata=False,
            ),
            cleaned_at=self.clock.now,
        )

        self.assertEqual(session.context.summary, "summary")
        self.assertEqual(cleaned.context.active_topic, "testing")
        self.assertEqual(cleaned.context.summary, "")
        self.assertEqual(cleaned.context.referenced_memories, ())
        self.assertEqual(cleaned.context.metadata["trace"], 1)


class ConversationExportTests(unittest.TestCase):
    """Verify export-ready structured/text artifacts never write files."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.builder = ConversationExportBuilder(
            clock=self.clock,
            id_factory=lambda: "export-001",
        )
        history = ConversationHistory(
            conversation_id="conversation-001",
            messages=(
                UserMessage(
                    "conversation-001",
                    "Hello lifecycle",
                    metadata={"channel": "test"},
                    timestamp=self.clock.now,
                ),
            ),
            created_at=self.clock.now,
            updated_at=self.clock.now,
        )
        self.session = replace(
            _session(self.clock),
            history=history,
            metadata={"owner": "operator"},
        )

    def test_json_export_is_deeply_immutable_and_export_ready(self) -> None:
        artifact = self.builder.prepare(self.session)

        self.assertIs(artifact.format, ExportFormat.JSON)
        self.assertEqual(artifact.export_id, "export-001")
        self.assertEqual(artifact.message_count, 1)
        self.assertEqual(artifact.content["messages"][0]["content"], "Hello lifecycle")
        self.assertFalse(artifact.writes_files)
        self.assertFalse(hasattr(self.builder, "write"))
        with self.assertRaises(TypeError):
            artifact.content["status"] = "changed"  # type: ignore[index]

    def test_metadata_can_be_excluded_from_structured_export(self) -> None:
        artifact = self.builder.prepare(
            self.session,
            include_metadata=False,
        )

        self.assertNotIn("metadata", artifact.content)
        self.assertNotIn("metadata", artifact.content["messages"][0])

    def test_text_and_markdown_exports_are_in_memory_strings(self) -> None:
        text = self.builder.prepare(self.session, format=ExportFormat.TEXT)
        markdown = self.builder.prepare(self.session, format=ExportFormat.MARKDOWN)

        self.assertIn("User:", text.content)
        self.assertIn("# Conversation", markdown.content)
        self.assertEqual(text.mime_type, "text/plain")
        self.assertEqual(markdown.mime_type, "text/markdown")

    def test_archive_metadata_is_included_without_archive_mutation(self) -> None:
        archive = ArchiveMetadata(
            conversation_id=self.session.session_id,
            original_status=ConversationStatus.ACTIVE,
            archived_at=self.clock.now,
            reason="complete",
        )

        artifact = self.builder.prepare(self.session, archive=archive)

        self.assertEqual(artifact.content["archive"]["reason"], "complete")
        self.assertTrue(archive.active)

    def test_archive_binding_and_format_validation_fail_closed(self) -> None:
        archive = ArchiveMetadata(
            conversation_id="other",
            original_status=ConversationStatus.ACTIVE,
            archived_at=self.clock.now,
        )
        with self.assertRaises(ConversationExportError):
            self.builder.prepare(self.session, archive=archive)
        with self.assertRaises(ConversationExportError):
            self.builder.prepare(
                self.session,
                format="json",  # type: ignore[arg-type]
            )


class ConversationLifecycleManagerTests(unittest.TestCase):
    """Verify manager multi-session, archive, expiration, cleanup, events, and health."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "conversation.archived",
            "conversation.restored",
            "conversation.cleaned",
            "conversation.expired",
            "conversation.session_switched",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.ids = iter(("session-001", "session-002", "session-003", "session-004"))
        self.manager = ConversationManager(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
            id_factory=lambda: next(self.ids),
        )

    def _create(self, **kwargs: object) -> ConversationSession:
        return self.manager.create_conversation(**kwargs)

    def test_multi_session_listing_and_switching_preserve_independent_history(
        self,
    ) -> None:
        first = self._create()
        self.manager.add_user_message(first.session_id, "first")
        self.clock.advance(seconds=1)
        second = self._create()
        self.manager.add_user_message(second.session_id, "second")

        selected = self.manager.switch_session(second.session_id)
        sessions = self.manager.list_sessions()

        self.assertEqual(selected.session_id, second.session_id)
        self.assertEqual(self.manager.current_session(), selected)
        self.assertEqual(
            [info.session_id for info in sessions],
            [first.session_id, second.session_id],
        )
        self.assertEqual(sum(info.current for info in sessions), 1)
        self.assertEqual(len(self.manager.get_history(first.session_id)), 1)
        self.assertEqual(len(self.manager.get_history(second.session_id)), 1)
        self.assertEqual(self.events[-1].name, "conversation.session_switched")

    def test_switch_rejects_closed_archived_and_expired_sessions(self) -> None:
        closed = self._create()
        self.manager.close_conversation(closed.session_id)
        archived = self._create()
        self.manager.archive_conversation(archived.session_id)
        expired = self._create()
        self.manager.expire_conversation(expired.session_id)

        for session in (closed, archived, expired):
            with self.subTest(session=session.session_id):
                with self.assertRaises(SessionSwitchError):
                    self.manager.switch_session(session.session_id)

    def test_archive_and_restore_active_session_preserve_metadata_and_events(
        self,
    ) -> None:
        session = self._create(metadata={"owner": "operator"})
        self.manager.add_user_message(session.session_id, "secret content")

        archived = self.manager.archive_conversation(
            session.session_id,
            reason="completed",
            tags=("release",),
            metadata={"ticket": "NARVIS-12"},
        )
        restored = self.manager.restore_conversation(session.session_id)
        archive = self.manager.archive_metadata(session.session_id)

        self.assertIs(archived.status, ConversationStatus.ARCHIVED)
        self.assertIs(restored.status, ConversationStatus.ACTIVE)
        self.assertEqual(restored.metadata["owner"], "operator")
        self.assertEqual(len(restored.messages), 1)
        self.assertIsNotNone(archive.restored_at)
        self.assertEqual(
            [event.name for event in self.events],
            ["conversation.archived", "conversation.restored"],
        )
        self.assertNotIn(
            "secret content", repr([event.payload for event in self.events])
        )

    def test_archived_closed_session_restores_closed(self) -> None:
        session = self._create()
        self.manager.close_conversation(session.session_id)

        archived = self.manager.archive_conversation(session.session_id)
        restored = self.manager.restore_conversation(session.session_id)

        self.assertIs(archived.status, ConversationStatus.ARCHIVED)
        self.assertIs(restored.status, ConversationStatus.CLOSED)
        self.assertIsNotNone(restored.closed_at)

    def test_archived_session_rejects_content_changes_and_duplicate_archive(
        self,
    ) -> None:
        session = self._create()
        self.manager.archive_conversation(session.session_id)

        with self.assertRaises(ConversationClosedError):
            self.manager.add_user_message(session.session_id, "blocked")
        with self.assertRaises(ConversationAlreadyArchivedError):
            self.manager.archive_conversation(session.session_id)

    def test_restore_non_archived_session_is_rejected(self) -> None:
        session = self._create()
        with self.assertRaises(ConversationNotArchivedError):
            self.manager.restore_conversation(session.session_id)

    def test_explicit_expiration_marks_session_and_publishes_event(self) -> None:
        session = self._create()

        expired = self.manager.expire_conversation(session.session_id)

        self.assertIs(expired.status, ConversationStatus.EXPIRED)
        self.assertIsNotNone(expired.expired_at)
        self.assertEqual(self.events[-1].name, "conversation.expired")
        with self.assertRaises(ConversationClosedError):
            self.manager.add_user_message(session.session_id, "blocked")

    def test_cleanup_expires_due_session_removes_it_and_publishes_both_events(
        self,
    ) -> None:
        session = self._create(expires_at=self.clock.now + timedelta(minutes=1))
        self.clock.advance(minutes=2)

        report = self.manager.cleanup_sessions(now=self.clock.now)

        self.assertEqual(report.expired_session_ids, (session.session_id,))
        self.assertEqual(report.removed_session_ids, (session.session_id,))
        self.assertEqual(
            [event.name for event in self.events],
            ["conversation.expired", "conversation.cleaned"],
        )
        with self.assertRaises(ConversationNotFoundError):
            self.manager.get_conversation(session.session_id)

    def test_closed_and_archived_retention_cleanup(self) -> None:
        closed = self._create()
        self.manager.close_conversation(closed.session_id)
        archived = self._create()
        self.manager.archive_conversation(archived.session_id)
        self.clock.advance(days=2)

        report = self.manager.cleanup_sessions(
            RetentionPolicy(
                closed_retention=timedelta(days=1),
                archived_retention=timedelta(days=1),
                expired_retention=None,
            ),
            now=self.clock.now,
        )

        self.assertEqual(
            set(report.removed_session_ids), {closed.session_id, archived.session_id}
        )
        self.assertIsNone(self.manager.archive_metadata(archived.session_id))

    def test_max_session_retention_preserves_current_selection(self) -> None:
        first = self._create()
        self.clock.advance(seconds=1)
        second = self._create()
        self.clock.advance(seconds=1)
        third = self._create()
        self.manager.switch_session(first.session_id)

        report = self.manager.cleanup_sessions(
            RetentionPolicy(max_sessions=2, expired_retention=None),
            now=self.clock.now,
        )

        self.assertEqual(report.removed_session_ids, (second.session_id,))
        self.assertEqual(self.manager.current_session_id, first.session_id)
        self.assertEqual(
            {info.session_id for info in self.manager.list_sessions()},
            {first.session_id, third.session_id},
        )

    def test_context_cleanup_clears_transient_fields_and_publishes_event(self) -> None:
        session = self._create()
        self.manager.update_context(
            session.session_id,
            active_topic="testing",
            referenced_memories=("memory-001",),
            referenced_skills=("skill.test",),
            referenced_agents=("planner",),
            summary="summary",
            metadata={"trace": 1},
        )

        cleaned = self.manager.cleanup_conversation_context(session.session_id)

        self.assertEqual(cleaned.context.active_topic, "")
        self.assertEqual(cleaned.context.summary, "")
        self.assertEqual(cleaned.context.referenced_memories, ())
        self.assertEqual(cleaned.context.metadata, {})
        self.assertEqual(self.events[-1].name, "conversation.cleaned")
        self.assertEqual(self.events[-1].payload["scope"], "context")

    def test_export_and_health_are_typed_and_side_effect_free(self) -> None:
        first = self._create(metadata={"owner": "operator"})
        self.manager.add_user_message(first.session_id, "hello")
        self.clock.advance(seconds=1)
        second = self._create(expires_at=self.clock.now)

        artifact = self.manager.prepare_export(first.session_id)
        health = self.manager.conversation_health(now=self.clock.now)

        self.assertFalse(artifact.writes_files)
        self.assertEqual(artifact.content["metadata"]["owner"], "operator")
        self.assertIsInstance(health, ConversationHealth)
        self.assertIs(health.status, HealthStatus.ATTENTION)
        self.assertEqual(health.total_sessions, 2)
        self.assertEqual(health.total_messages, 1)
        self.assertEqual(health.expiring_sessions, 1)
        self.assertEqual(second.status, ConversationStatus.ACTIVE)

    def test_empty_health_and_missing_current_session_are_typed(self) -> None:
        health = self.manager.conversation_health()

        self.assertIs(health.status, HealthStatus.EMPTY)
        self.assertEqual(health.health_score, 100)
        with self.assertRaises(NoCurrentSessionError):
            self.manager.current_session()

    def test_lifecycle_logging_is_structured(self) -> None:
        session = self._create()
        self.manager.archive_conversation(session.session_id)

        self.assertTrue(
            any(
                level is LogLevel.INFO
                and message == "Conversation archived"
                and context["conversation_id"] == session.session_id
                for level, message, context in self.logger.entries
            )
        )

    def test_event_subscriber_failure_does_not_change_archive_state(self) -> None:
        bus = EventBus()
        logger = _CapturingLogger()
        bus.subscribe(
            "conversation.archived",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        manager = ConversationManager(
            event_bus=bus,
            logger=logger,
            clock=self.clock,
            id_factory=lambda: "safe-session",
        )
        session = manager.create_conversation()

        archived = manager.archive_conversation(session.session_id)

        self.assertTrue(archived.archived)
        self.assertEqual(manager.get_conversation(session.session_id), archived)
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in logger.entries)
        )


if __name__ == "__main__":
    unittest.main()
