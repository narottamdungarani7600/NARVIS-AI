"""Comprehensive tests for Phase 12 Human Interaction Layer Sprint 1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Conversation import (
    AssistantMessage,
    ContextValidationError,
    ConversationAlreadyActiveError,
    ConversationAlreadyClosedError,
    ConversationClosedError,
    ConversationContext,
    ConversationContextTracker,
    ConversationHistory,
    ConversationHistoryManager,
    ConversationManager,
    ConversationMessage,
    ConversationNotFoundError,
    ConversationSession,
    ConversationStatistics,
    ConversationStatus,
    ConversationValidationError,
    DuplicateConversationError,
    InMemoryConversationSessionStore,
    MessageRole,
    MessageValidationError,
    SystemMessage,
    UserMessage,
)


class _Clock:
    """Mutable aware clock for deterministic conversation tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

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


class _FailingLogger:
    """Logger double proving diagnostics never alter conversation state."""

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        raise RuntimeError("logger unavailable")


class ConversationModelTests(unittest.TestCase):
    """Verify strong typing, immutability, metadata, roles, and timestamps."""

    def setUp(self) -> None:
        self.clock = _Clock()

    def test_role_specific_messages_are_typed_and_immutable(self) -> None:
        messages = (
            UserMessage("conversation-001", "hello", timestamp=self.clock.now),
            AssistantMessage("conversation-001", "hi", timestamp=self.clock.now),
            SystemMessage("conversation-001", "be concise", timestamp=self.clock.now),
        )

        self.assertEqual(
            tuple(message.role for message in messages),
            (MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM),
        )
        with self.assertRaises(FrozenInstanceError):
            messages[0].content = "changed"  # type: ignore[misc]

    def test_generic_message_factories_support_all_roles(self) -> None:
        user = ConversationMessage.user(
            "conversation-001",
            "question",
            timestamp=self.clock.now,
        )
        assistant = ConversationMessage.assistant(
            "conversation-001",
            "answer",
            timestamp=self.clock.now,
        )
        system = ConversationMessage.system(
            "conversation-001",
            "policy",
            timestamp=self.clock.now,
        )

        self.assertEqual(
            (user.role, assistant.role, system.role),
            (MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM),
        )

    def test_nested_message_metadata_is_detached_and_read_only(self) -> None:
        source = {"trace": {"steps": [1, 2]}}
        message = UserMessage(
            "conversation-001",
            "hello",
            metadata=source,
            timestamp=self.clock.now,
        )
        source["trace"]["steps"].append(3)

        self.assertEqual(message.metadata["trace"]["steps"], (1, 2))
        with self.assertRaises(TypeError):
            message.metadata["new"] = True  # type: ignore[index]

    def test_message_validation_rejects_invalid_role_content_and_time(self) -> None:
        with self.assertRaises(TypeError):
            ConversationMessage(
                "conversation-001",
                "hello",
                "user",  # type: ignore[arg-type]
                timestamp=self.clock.now,
            )
        with self.assertRaises(ValueError):
            UserMessage("conversation-001", "   ", timestamp=self.clock.now)
        with self.assertRaises(ValueError):
            UserMessage(
                "conversation-001",
                "hello",
                timestamp=datetime(2026, 7, 14),
            )

    def test_history_requires_matching_ordered_messages_and_timestamps(self) -> None:
        message = UserMessage(
            "other-conversation",
            "hello",
            timestamp=self.clock.now,
        )
        with self.assertRaises(ValueError):
            ConversationHistory(
                "conversation-001",
                messages=(message,),
                created_at=self.clock.now,
                updated_at=self.clock.now,
            )

        early = self.clock.now - timedelta(seconds=1)
        with self.assertRaises(ValueError):
            ConversationHistory(
                "conversation-001",
                messages=(
                    UserMessage(
                        "conversation-001",
                        "hello",
                        timestamp=early,
                    ),
                ),
                created_at=self.clock.now,
                updated_at=self.clock.now,
            )

    def test_context_references_are_unique_typed_sequences(self) -> None:
        with self.assertRaises(ValueError):
            ConversationContext(
                "conversation-001",
                referenced_skills=("search", "search"),
                updated_at=self.clock.now,
            )
        with self.assertRaises(TypeError):
            ConversationContext(
                "conversation-001",
                referenced_agents="planner",  # type: ignore[arg-type]
                updated_at=self.clock.now,
            )

    def test_session_requires_exact_history_and_context_bindings(self) -> None:
        history = ConversationHistory(
            "conversation-001",
            created_at=self.clock.now,
            updated_at=self.clock.now,
        )
        context = ConversationContext(
            "conversation-002",
            updated_at=self.clock.now,
        )

        with self.assertRaises(ValueError):
            ConversationSession(
                session_id="conversation-001",
                status=ConversationStatus.ACTIVE,
                history=history,
                context=context,
                created_at=self.clock.now,
                updated_at=self.clock.now,
            )
        with self.assertRaises(ValueError):
            replace(
                ConversationSession(
                    session_id="conversation-001",
                    status=ConversationStatus.ACTIVE,
                    history=history,
                    context=replace(context, conversation_id="conversation-001"),
                    created_at=self.clock.now,
                    updated_at=self.clock.now,
                ),
                status=ConversationStatus.CLOSED,
            )


class HistoryAndContextTests(unittest.TestCase):
    """Verify pure immutable history and context transformations."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.history_manager = ConversationHistoryManager(clock=self.clock)
        self.context_tracker = ConversationContextTracker(clock=self.clock)

    def test_append_returns_new_history_and_preserves_original(self) -> None:
        original = self.history_manager.create("conversation-001")
        message = UserMessage(
            "conversation-001",
            "hello",
            timestamp=self.clock.now,
        )

        updated = self.history_manager.append(original, message)

        self.assertEqual(original.messages, ())
        self.assertEqual(updated.messages, (message,))

    def test_history_role_filter_and_clear_count(self) -> None:
        history = self.history_manager.create("conversation-001")
        for message in (
            UserMessage("conversation-001", "one", timestamp=self.clock.now),
            AssistantMessage("conversation-001", "two", timestamp=self.clock.now),
            UserMessage("conversation-001", "three", timestamp=self.clock.now),
        ):
            history = self.history_manager.append(history, message)

        self.assertEqual(
            len(self.history_manager.messages(history, role=MessageRole.USER)),
            2,
        )
        self.clock.advance(seconds=1)
        cleared = self.history_manager.clear(history)
        self.assertEqual(cleared.messages, ())
        self.assertEqual(cleared.cleared_messages, 3)

    def test_history_rejects_mismatched_and_stale_messages(self) -> None:
        history = self.history_manager.create("conversation-001")
        with self.assertRaises(MessageValidationError):
            self.history_manager.append(
                history,
                UserMessage("other", "hello", timestamp=self.clock.now),
            )
        history = self.history_manager.append(
            history,
            UserMessage("conversation-001", "hello", timestamp=self.clock.now),
        )
        with self.assertRaises(MessageValidationError):
            self.history_manager.append(
                history,
                UserMessage(
                    "conversation-001",
                    "stale",
                    timestamp=self.clock.now - timedelta(seconds=1),
                ),
            )

    def test_topic_changes_retain_previous_topic(self) -> None:
        context = self.context_tracker.create("conversation-001")
        context = self.context_tracker.update(context, active_topic="planning")
        updated = self.context_tracker.update(context, active_topic="testing")

        self.assertEqual(context.previous_topic, "")
        self.assertEqual(updated.active_topic, "testing")
        self.assertEqual(updated.previous_topic, "planning")

    def test_context_merges_references_summary_and_metadata_immutably(self) -> None:
        context = self.context_tracker.create("conversation-001")
        context = self.context_tracker.update(
            context,
            referenced_skills=("search", "testing"),
            referenced_agents=("planner",),
            summary="Planning the feature",
            metadata={"turn": {"number": 1}},
        )
        updated = self.context_tracker.update(
            context,
            referenced_skills=("testing", "review"),
            referenced_agents=("reviewer",),
        )

        self.assertEqual(updated.referenced_skills, ("search", "testing", "review"))
        self.assertEqual(updated.referenced_agents, ("planner", "reviewer"))
        self.assertEqual(updated.summary, "Planning the feature")
        self.assertEqual(updated.metadata["turn"]["number"], 1)

    def test_context_reference_replacement_clear_and_validation(self) -> None:
        context = self.context_tracker.create("conversation-001")
        context = self.context_tracker.update(
            context,
            referenced_skills=("old",),
            referenced_agents=("old-agent",),
        )
        replaced = self.context_tracker.update(
            context,
            referenced_skills=("new",),
            referenced_agents=(),
            replace_references=True,
        )
        self.assertEqual(replaced.referenced_skills, ("new",))
        self.assertEqual(replaced.referenced_agents, ())
        self.assertEqual(self.context_tracker.clear(replaced).active_topic, "")
        with self.assertRaises(ContextValidationError):
            self.context_tracker.update(replaced, referenced_skills="invalid")


class ConversationSessionStoreTests(unittest.TestCase):
    """Verify dependency-injectable in-memory immutable session storage."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.store = InMemoryConversationSessionStore()
        self.manager = ConversationManager(
            session_store=self.store,
            clock=self.clock,
            id_factory=lambda: "conversation-001",
        )

    def test_store_get_list_and_replace_latest_snapshot(self) -> None:
        original = self.manager.create_conversation()
        updated = self.manager.add_user_message(original.session_id, "hello")

        self.assertEqual(self.store.get(original.session_id), updated)
        self.assertEqual(self.store.list(), (updated,))
        self.assertEqual(original.messages, ())

    def test_duplicate_identifier_is_rejected(self) -> None:
        self.manager.create_conversation()
        with self.assertRaises(DuplicateConversationError):
            self.manager.create_conversation()

    def test_missing_and_invalid_identifier_use_typed_lookup_error(self) -> None:
        with self.assertRaises(ConversationNotFoundError):
            self.store.get("missing")
        with self.assertRaises(ConversationNotFoundError):
            self.store.get("")


class ConversationManagerLifecycleTests(unittest.TestCase):
    """Verify manager lifecycle, events, logging, statistics, and validation."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "conversation.created",
            "conversation.updated",
            "conversation.closed",
            "conversation.resumed",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.manager = ConversationManager(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
            id_factory=lambda: "conversation-001",
        )

    def test_create_generates_identity_timestamp_metadata_event_and_log(self) -> None:
        source = {"channel": {"name": "test"}}
        session = self.manager.create_conversation(metadata=source)
        source["channel"]["name"] = "changed"

        self.assertEqual(session.session_id, "conversation-001")
        self.assertIs(session.status, ConversationStatus.ACTIVE)
        self.assertEqual(session.created_at, self.clock.now)
        self.assertEqual(session.metadata["channel"]["name"], "test")
        self.assertEqual(
            [event.name for event in self.events], ["conversation.created"]
        )
        self.assertTrue(
            any(
                message == "Conversation created"
                for _, message, _ in self.logger.entries
            )
        )

    def test_create_can_seed_one_system_message_without_extra_update_event(
        self,
    ) -> None:
        session = self.manager.create_conversation(system_message="Policy")

        self.assertEqual(len(session.messages), 1)
        self.assertIs(session.messages[0].role, MessageRole.SYSTEM)
        self.assertEqual(
            [event.name for event in self.events], ["conversation.created"]
        )

    def test_user_assistant_and_system_messages_preserve_order_and_metadata(
        self,
    ) -> None:
        self.manager.create_conversation()
        self.manager.add_user_message(
            "conversation-001",
            "Question",
            metadata={"source": "operator"},
        )
        self.clock.advance(seconds=1)
        self.manager.add_assistant_message("conversation-001", "Answer")
        self.clock.advance(seconds=1)
        session = self.manager.add_system_message("conversation-001", "Reminder")

        self.assertEqual(
            tuple(message.role for message in session.messages),
            (MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM),
        )
        self.assertEqual(session.messages[0].metadata["source"], "operator")
        self.assertEqual(
            [event.name for event in self.events],
            ["conversation.created"] + ["conversation.updated"] * 3,
        )

    def test_context_tracks_topics_references_and_summary(self) -> None:
        self.manager.create_conversation()
        first = self.manager.update_context(
            "conversation-001",
            active_topic="architecture",
            referenced_skills=("testing",),
            referenced_agents=("planner",),
            summary="Designing conversation core",
        )
        self.clock.advance(seconds=1)
        second = self.manager.update_context(
            "conversation-001",
            active_topic="validation",
            referenced_skills=("review",),
        )

        self.assertEqual(first.context.previous_topic, "")
        self.assertEqual(second.context.previous_topic, "architecture")
        self.assertEqual(second.context.active_topic, "validation")
        self.assertEqual(second.context.referenced_skills, ("testing", "review"))
        self.assertEqual(second.context.referenced_agents, ("planner",))
        self.assertEqual(second.context.summary, "Designing conversation core")

    def test_close_and_resume_preserve_history_and_lifecycle_timestamps(self) -> None:
        self.manager.create_conversation()
        self.manager.add_user_message("conversation-001", "hello")
        self.clock.advance(seconds=1)
        closed = self.manager.close_conversation("conversation-001")
        self.clock.advance(seconds=1)
        resumed = self.manager.resume_conversation("conversation-001")

        self.assertTrue(closed.closed)
        self.assertEqual(closed.closed_at, self.clock.now - timedelta(seconds=1))
        self.assertTrue(resumed.active)
        self.assertEqual(resumed.resumed_at, self.clock.now)
        self.assertEqual(resumed.resume_count, 1)
        self.assertEqual(len(resumed.messages), 1)
        self.assertEqual(
            [event.name for event in self.events],
            [
                "conversation.created",
                "conversation.updated",
                "conversation.closed",
                "conversation.resumed",
            ],
        )

    def test_invalid_duplicate_lifecycle_operations_are_typed(self) -> None:
        self.manager.create_conversation()
        with self.assertRaises(ConversationAlreadyActiveError):
            self.manager.resume_conversation("conversation-001")
        self.manager.close_conversation("conversation-001")
        with self.assertRaises(ConversationAlreadyClosedError):
            self.manager.close_conversation("conversation-001")

    def test_closed_conversation_rejects_all_mutating_updates(self) -> None:
        self.manager.create_conversation()
        self.manager.close_conversation("conversation-001")

        operations = (
            lambda: self.manager.add_user_message("conversation-001", "hello"),
            lambda: self.manager.clear_history("conversation-001"),
            lambda: self.manager.update_context(
                "conversation-001",
                active_topic="blocked",
            ),
            lambda: self.manager.clear_context("conversation-001"),
            lambda: self.manager.update_metadata(
                "conversation-001",
                {"blocked": True},
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(ConversationClosedError):
                    operation()

    def test_clear_history_preserves_cumulative_statistics(self) -> None:
        self.manager.create_conversation(system_message="Policy")
        self.manager.add_user_message("conversation-001", "Question")
        self.manager.add_assistant_message("conversation-001", "Answer")
        self.clock.advance(seconds=1)
        session = self.manager.clear_history("conversation-001")
        statistics = self.manager.statistics("conversation-001")

        self.assertEqual(session.messages, ())
        self.assertEqual(statistics.total_messages, 0)
        self.assertEqual(statistics.cleared_messages, 3)
        self.assertIsInstance(statistics, ConversationStatistics)

    def test_statistics_count_roles_context_and_resumes(self) -> None:
        self.manager.create_conversation(system_message="Policy")
        self.manager.add_user_message("conversation-001", "Question")
        self.manager.add_assistant_message("conversation-001", "Answer")
        self.manager.update_context(
            "conversation-001",
            active_topic="conversation",
            referenced_skills=("testing", "review"),
            referenced_agents=("planner",),
        )
        self.manager.close_conversation("conversation-001")
        self.manager.resume_conversation("conversation-001")

        statistics = self.manager.conversation_statistics("conversation-001")

        self.assertEqual(statistics.total_messages, 3)
        self.assertEqual(statistics.user_messages, 1)
        self.assertEqual(statistics.assistant_messages, 1)
        self.assertEqual(statistics.system_messages, 1)
        self.assertEqual(statistics.resume_count, 1)
        self.assertEqual(statistics.active_topic, "conversation")
        self.assertEqual(statistics.referenced_skill_count, 2)
        self.assertEqual(statistics.referenced_agent_count, 1)

    def test_clear_context_and_metadata_update_are_immutable(self) -> None:
        original = self.manager.create_conversation(metadata={"revision": 1})
        updated = self.manager.update_metadata(
            "conversation-001",
            {"revision": 2, "trace": [1, 2]},
        )
        self.manager.update_context(
            "conversation-001",
            active_topic="temporary",
        )
        cleared = self.manager.clear_context("conversation-001")

        self.assertEqual(original.metadata["revision"], 1)
        self.assertEqual(updated.metadata["revision"], 2)
        self.assertEqual(updated.metadata["trace"], (1, 2))
        self.assertEqual(cleared.context.active_topic, "")

    def test_invalid_roles_metadata_and_stale_timestamps_are_rejected(self) -> None:
        self.manager.create_conversation()
        with self.assertRaises(MessageValidationError):
            self.manager.add_message(
                "conversation-001",
                "user",  # type: ignore[arg-type]
                "hello",
            )
        with self.assertRaises(MessageValidationError):
            self.manager.add_user_message(
                "conversation-001",
                "hello",
                metadata=[],  # type: ignore[arg-type]
            )
        with self.assertRaises(ConversationValidationError):
            self.manager.close_conversation(
                "conversation-001",
                closed_at=self.clock.now - timedelta(seconds=1),
            )

    def test_event_payloads_and_logs_exclude_message_content_and_metadata(self) -> None:
        secret = "do-not-publish-or-log"
        self.manager.create_conversation(metadata={"secret": secret})
        self.manager.add_user_message(
            "conversation-001",
            secret,
            metadata={"secret": secret},
        )

        self.assertNotIn(secret, repr([event.payload for event in self.events]))
        self.assertNotIn(secret, repr(self.logger.entries))
        update = self.events[-1]
        self.assertEqual(update.payload["update_type"], "message_added")
        self.assertEqual(update.payload["role"], "user")

    def test_event_and_logger_failures_do_not_change_retained_state(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "conversation.created",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        manager = ConversationManager(
            event_bus=bus,
            logger=_FailingLogger(),
            clock=self.clock,
            id_factory=lambda: "conversation-safe",
        )

        session = manager.create_conversation()
        updated = manager.add_user_message(session.session_id, "hello")

        self.assertEqual(updated, manager.get_conversation(session.session_id))
        self.assertEqual(len(updated.messages), 1)

    def test_custom_ids_listing_and_explicit_timestamps(self) -> None:
        first = self.manager.create_conversation(session_id="custom-001")
        self.clock.advance(seconds=1)
        second = self.manager.create_conversation(session_id="custom-002")

        self.assertEqual(
            tuple(item.session_id for item in self.manager.list_conversations()),
            ("custom-001", "custom-002"),
        )
        self.assertLess(first.created_at, second.created_at)


if __name__ == "__main__":
    unittest.main()
