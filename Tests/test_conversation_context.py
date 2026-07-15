"""Comprehensive tests for Phase 12 Human Interaction Layer Sprint 2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Conversation import (
    ContextReferences,
    ContextStatistics,
    ConversationClosedError,
    ConversationContextManager,
    ConversationManager,
    ConversationMessage,
    ConversationSearch,
    ConversationSummary,
    ConversationWindowManager,
    ExtractiveConversationSummarizer,
    KeywordTopicDetector,
    MessageRole,
    ReferenceNotFoundError,
    ReferenceValidationError,
    SearchMode,
    SearchValidationError,
    SummaryGenerationError,
    TopicDetection,
    TopicDetectionError,
    UserMessage,
    WindowValidationError,
)


class _Clock:
    """Mutable aware clock for deterministic context tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)

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


class _ReadOnlyMemory:
    """Memory reader that fails immediately if a mutation is attempted."""

    def __init__(self, identifiers: tuple[str, ...]) -> None:
        self._values = {identifier: object() for identifier in identifiers}
        self.loads: list[str] = []
        self.mutation_calls = 0

    def load(self, key: str) -> object | None:
        self.loads.append(key)
        return self._values.get(key)

    def save(self, value: object) -> None:
        self.mutation_calls += 1
        raise AssertionError("memory mutation is forbidden")

    def delete(self, key: str) -> None:
        self.mutation_calls += 1
        raise AssertionError("memory mutation is forbidden")


class _NamedReader:
    """Read-only Skills/Agents-style named lookup double."""

    def __init__(self, identifiers: tuple[str, ...]) -> None:
        self._values = {identifier: object() for identifier in identifiers}
        self.finds: list[str] = []

    def find(self, name: str) -> object | None:
        self.finds.append(name)
        return self._values.get(name)


def _messages(
    clock: _Clock, conversation_id: str = "conversation-001"
) -> tuple[ConversationMessage, ...]:
    values: list[ConversationMessage] = []
    for index, (role, content) in enumerate(
        (
            (MessageRole.SYSTEM, "Keep responses concise."),
            (MessageRole.USER, "Please remember my memory preference."),
            (MessageRole.ASSISTANT, "The memory preference is noted."),
            (MessageRole.USER, "Search the conversation memory context."),
        )
    ):
        timestamp = clock.now + timedelta(seconds=index)
        values.append(
            ConversationMessage(
                conversation_id=conversation_id,
                content=content,
                role=role,
                message_id=f"message-{index}",
                timestamp=timestamp,
            )
        )
    return tuple(values)


class ContextModelTests(unittest.TestCase):
    """Verify Sprint 2 model typing, validation, and deep immutability."""

    def setUp(self) -> None:
        self.clock = _Clock()

    def test_summary_is_frozen_and_metadata_is_deeply_read_only(self) -> None:
        source = {"facts": {"indexes": [1, 2]}}
        summary = ConversationSummary(
            conversation_id="conversation-001",
            text="Summary",
            message_count=2,
            source_message_ids=("message-1", "message-2"),
            metadata=source,
            generated_at=self.clock.now,
        )
        source["facts"]["indexes"].append(3)

        self.assertEqual(summary.summary, "Summary")
        self.assertEqual(summary.metadata["facts"]["indexes"], (1, 2))
        with self.assertRaises(FrozenInstanceError):
            summary.text = "changed"  # type: ignore[misc]

    def test_summary_rejects_inconsistent_sources_and_naive_time(self) -> None:
        with self.assertRaises(ValueError):
            ConversationSummary(
                conversation_id="conversation-001",
                text="Summary",
                message_count=1,
                source_message_ids=("one", "two"),
                generated_at=self.clock.now,
            )
        with self.assertRaises(ValueError):
            ConversationSummary(
                conversation_id="conversation-001",
                text="Summary",
                message_count=0,
                generated_at=datetime(2026, 7, 15),
            )

    def test_topic_detection_changed_property_and_confidence_validation(self) -> None:
        detection = TopicDetection(
            conversation_id="conversation-001",
            topic="memory",
            previous_topic="testing",
            confidence=0.75,
            keywords=("memory",),
            detected_at=self.clock.now,
        )

        self.assertTrue(detection.changed)
        with self.assertRaises(ValueError):
            replace(detection, confidence=1.1)

    def test_context_references_are_immutable_unique_identifiers(self) -> None:
        references = ContextReferences(
            conversation_id="conversation-001",
            memories=("memory-001",),
            skills=("skill.search",),
            agents=("planner",),
        )

        self.assertEqual(references.total_count, 3)
        with self.assertRaises(FrozenInstanceError):
            references.memories = ()  # type: ignore[misc]
        with self.assertRaises(ValueError):
            replace(references, skills=("duplicate", "duplicate"))


class ConversationSummaryTests(unittest.TestCase):
    """Verify deterministic bounded extractive summary generation."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.summarizer = ExtractiveConversationSummarizer(
            default_max_messages=3,
            clock=self.clock,
        )

    def test_summary_uses_newest_messages_in_chronological_role_order(self) -> None:
        messages = _messages(self.clock)

        summary = self.summarizer.generate(
            "conversation-001",
            messages,
            active_topic="memory",
            max_messages=2,
        )

        self.assertEqual(summary.message_count, 4)
        self.assertEqual(summary.source_message_ids, ("message-2", "message-3"))
        self.assertTrue(summary.text.startswith("Assistant:"))
        self.assertIn("User: Search the conversation", summary.text)
        self.assertEqual(summary.active_topic, "memory")
        self.assertTrue(summary.metadata["truncated"])

    def test_empty_history_produces_a_typed_summary(self) -> None:
        summary = self.summarizer.generate("conversation-001", ())

        self.assertEqual(summary.message_count, 0)
        self.assertEqual(summary.source_message_ids, ())
        self.assertEqual(summary.text, "No conversation messages available.")

    def test_summary_compacts_whitespace_and_bounds_output(self) -> None:
        summarizer = ExtractiveConversationSummarizer(
            default_max_messages=1,
            max_characters=64,
            clock=self.clock,
        )
        message = UserMessage(
            "conversation-001",
            "word   " * 30,
            timestamp=self.clock.now,
        )

        summary = summarizer.generate("conversation-001", (message,))

        self.assertLessEqual(len(summary.text), 64)
        self.assertNotIn("   ", summary.text)
        self.assertTrue(summary.text.endswith("…"))

    def test_invalid_summary_inputs_fail_with_typed_errors(self) -> None:
        with self.assertRaises(SummaryGenerationError):
            self.summarizer.generate(
                "conversation-001",
                _messages(self.clock, "other"),
            )
        with self.assertRaises(SummaryGenerationError):
            self.summarizer.generate(
                "conversation-001",
                _messages(self.clock),
                max_messages=0,
            )


class TopicDetectionTests(unittest.TestCase):
    """Verify keyword scoring, lexical fallback, switching, and validation."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.detector = KeywordTopicDetector(clock=self.clock)

    def test_configured_keyword_topic_is_detected_locally(self) -> None:
        detection = self.detector.detect(
            "conversation-001",
            _messages(self.clock),
            current_topic="testing",
        )

        self.assertEqual(detection.topic, "memory")
        self.assertEqual(detection.previous_topic, "testing")
        self.assertIn("memory", detection.keywords)
        self.assertGreater(detection.confidence, 0)
        self.assertTrue(detection.changed)

    def test_unconfigured_content_uses_stable_lexical_fallback(self) -> None:
        message = UserMessage(
            "conversation-001",
            "Kubernetes deployment details",
            timestamp=self.clock.now,
        )

        detection = self.detector.detect("conversation-001", (message,))

        self.assertEqual(detection.topic, "kubernetes")
        self.assertEqual(detection.keywords, ("kubernetes",))
        self.assertEqual(detection.confidence, 0.25)

    def test_empty_history_preserves_existing_topic(self) -> None:
        detection = self.detector.detect(
            "conversation-001",
            (),
            current_topic="existing",
        )

        self.assertEqual(detection.topic, "existing")
        self.assertFalse(detection.changed)
        self.assertEqual(detection.confidence, 0)

    def test_invalid_topic_configuration_and_message_binding_are_rejected(self) -> None:
        with self.assertRaises(TopicDetectionError):
            KeywordTopicDetector({})
        with self.assertRaises(TopicDetectionError):
            self.detector.detect(
                "conversation-001",
                _messages(self.clock, "other"),
            )


class ConversationWindowTests(unittest.TestCase):
    """Verify immutable recent-message windows and role filtering."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.manager = ConversationWindowManager(3, clock=self.clock)

    def test_window_contains_newest_messages_and_offsets(self) -> None:
        messages = _messages(self.clock)

        window = self.manager.build(
            "conversation-001",
            messages,
            max_messages=2,
        )

        self.assertEqual(window.messages, messages[-2:])
        self.assertEqual(window.start_offset, 2)
        self.assertEqual(window.end_offset, 4)
        self.assertEqual(window.message_count, 2)
        self.assertTrue(window.truncated)

    def test_role_filtered_window_uses_eligible_message_offsets(self) -> None:
        window = self.manager.build(
            "conversation-001",
            _messages(self.clock),
            roles=(MessageRole.USER,),
            max_messages=1,
        )

        self.assertEqual(window.message_count, 1)
        self.assertIs(window.messages[0].role, MessageRole.USER)
        self.assertEqual(window.total_message_count, 2)
        self.assertEqual(window.start_offset, 1)

    def test_empty_window_is_valid_and_history_is_not_modified(self) -> None:
        messages = _messages(self.clock)
        original = tuple(messages)

        window = self.manager.build(
            "conversation-001",
            messages,
            roles=(MessageRole.ASSISTANT,),
            max_messages=5,
        )

        self.assertEqual(window.message_count, 1)
        self.assertEqual(messages, original)

    def test_invalid_window_size_roles_and_binding_are_rejected(self) -> None:
        with self.assertRaises(WindowValidationError):
            ConversationWindowManager(0)
        with self.assertRaises(WindowValidationError):
            self.manager.build(
                "conversation-001",
                _messages(self.clock),
                roles=("user",),  # type: ignore[arg-type]
            )
        with self.assertRaises(WindowValidationError):
            self.manager.build(
                "conversation-001",
                _messages(self.clock, "other"),
            )


class ConversationSearchTests(unittest.TestCase):
    """Verify in-memory ranked search, modes, filters, limits, and validation."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.search = ConversationSearch(clock=self.clock)

    def test_any_search_ranks_phrase_and_returns_match_facts(self) -> None:
        result = self.search.search(
            "conversation-001",
            _messages(self.clock),
            "memory context",
        )

        self.assertEqual(result.total_matches, 3)
        self.assertEqual(result.matches[0].message.message_id, "message-3")
        self.assertEqual(result.matches[0].score, 1.0)
        self.assertEqual(result.messages[0].role, MessageRole.USER)

    def test_all_phrase_case_and_role_filters_are_supported(self) -> None:
        messages = _messages(self.clock)
        all_result = self.search.search(
            "conversation-001",
            messages,
            "memory preference",
            mode=SearchMode.ALL,
        )
        phrase_result = self.search.search(
            "conversation-001",
            messages,
            "memory preference",
            mode=SearchMode.PHRASE,
            role=MessageRole.ASSISTANT,
        )
        case_result = self.search.search(
            "conversation-001",
            messages,
            "Memory",
            case_sensitive=True,
        )

        self.assertEqual(all_result.total_matches, 2)
        self.assertEqual(phrase_result.total_matches, 1)
        self.assertTrue(
            all(
                match.message.role is MessageRole.ASSISTANT
                for match in phrase_result.matches
            )
        )
        self.assertEqual(case_result.total_matches, 0)

    def test_search_limit_preserves_total_match_count(self) -> None:
        result = self.search.search(
            "conversation-001",
            _messages(self.clock),
            "memory",
            limit=1,
        )

        self.assertEqual(result.match_count, 1)
        self.assertEqual(result.total_matches, 3)
        self.assertEqual(result.searched_message_count, 4)

    def test_invalid_query_role_mode_limit_and_binding_are_rejected(self) -> None:
        messages = _messages(self.clock)
        invalid_calls = (
            lambda: self.search.search("conversation-001", messages, "  "),
            lambda: self.search.search(
                "conversation-001",
                messages,
                "memory",
                role="user",  # type: ignore[arg-type]
            ),
            lambda: self.search.search(
                "conversation-001",
                messages,
                "memory",
                mode="all",  # type: ignore[arg-type]
            ),
            lambda: self.search.search(
                "conversation-001",
                messages,
                "memory",
                limit=0,
            ),
            lambda: self.search.search(
                "conversation-001",
                _messages(self.clock, "other"),
                "memory",
            ),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(SearchValidationError):
                    call()


class ReadOnlyReferenceTests(unittest.TestCase):
    """Verify memory, skill, and agent integration is lookup-only."""

    def setUp(self) -> None:
        self.memory = _ReadOnlyMemory(("memory-001", "memory-002"))
        self.skills = _NamedReader(("skill.search", "skill.summary"))
        self.agents = _NamedReader(("planner", "reviewer"))
        self.context = ConversationContextManager(
            memory_reader=self.memory,
            skill_reader=self.skills,
            agent_reader=self.agents,
        )

    def test_valid_references_use_only_read_methods(self) -> None:
        references = self.context.validate_references(
            "conversation-001",
            memories=("memory-001",),
            skills=("skill.search",),
            agents=("planner",),
        )

        self.assertEqual(references.total_count, 3)
        self.assertEqual(self.memory.loads, ["memory-001"])
        self.assertEqual(self.skills.finds, ["skill.search"])
        self.assertEqual(self.agents.finds, ["planner"])
        self.assertEqual(self.memory.mutation_calls, 0)

    def test_missing_reference_fails_without_mutating_any_source(self) -> None:
        with self.assertRaises(ReferenceNotFoundError):
            self.context.validate_references(
                "conversation-001",
                memories=("missing",),
            )

        self.assertEqual(self.memory.mutation_calls, 0)

    def test_invalid_reader_contract_is_rejected_at_injection(self) -> None:
        with self.assertRaises(ReferenceValidationError):
            ConversationContextManager(memory_reader=object())
        with self.assertRaises(ReferenceValidationError):
            ConversationContextManager(skill_reader=object())


class ConversationManagerContextTests(unittest.TestCase):
    """Verify complete manager integration, state updates, events, and logs."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "conversation.summary_generated",
            "conversation.topic_changed",
            "conversation.window_updated",
            "conversation.search_completed",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.memory = _ReadOnlyMemory(("memory-001",))
        self.skills = _NamedReader(("skill.search",))
        self.agents = _NamedReader(("planner",))
        self.manager = ConversationManager(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
            id_factory=lambda: "conversation-001",
            memory_reader=self.memory,
            skill_reader=self.skills,
            agent_reader=self.agents,
        )
        self.manager.create_conversation(system_message="Keep responses concise.")
        self.manager.add_user_message(
            "conversation-001",
            "Please remember my memory preference.",
        )
        self.clock.advance(seconds=1)
        self.manager.add_assistant_message(
            "conversation-001",
            "The memory preference is noted.",
        )
        self.clock.advance(seconds=1)
        self.manager.add_user_message(
            "conversation-001",
            "Search the conversation memory context.",
        )

    def test_generate_summary_updates_context_and_publishes_safe_event(self) -> None:
        summary = self.manager.generate_summary(
            "conversation-001",
            max_messages=2,
        )
        session = self.manager.get_conversation("conversation-001")
        event = self.events[-1]

        self.assertEqual(session.context.summary, summary.text)
        self.assertEqual(session.context.metadata["summary_id"], summary.summary_id)
        self.assertEqual(event.name, "conversation.summary_generated")
        self.assertEqual(event.payload["summary_id"], summary.summary_id)
        self.assertNotIn(summary.text, repr(event.payload))
        self.assertTrue(
            any(
                message == "Conversation summary generated"
                for _, message, _ in self.logger.entries
            )
        )

    def test_topic_detection_switches_active_and_previous_topics_once(self) -> None:
        self.manager.update_context(
            "conversation-001",
            active_topic="testing",
        )
        self.events.clear()

        detection = self.manager.detect_topic("conversation-001")
        repeated = self.manager.detect_topic("conversation-001")
        session = self.manager.get_conversation("conversation-001")

        self.assertEqual(detection.topic, "memory")
        self.assertEqual(session.context.active_topic, "memory")
        self.assertEqual(session.context.previous_topic, "testing")
        self.assertFalse(repeated.changed)
        self.assertEqual(
            [event.name for event in self.events],
            ["conversation.topic_changed"],
        )

    def test_active_topic_accessor_can_read_or_trigger_detection(self) -> None:
        self.assertEqual(self.manager.active_topic("conversation-001"), "")

        topic = self.manager.active_topic("conversation-001", detect=True)

        self.assertEqual(topic, "memory")
        self.assertEqual(self.manager.active_topic("conversation-001"), "memory")

    def test_window_search_and_statistics_return_immutable_typed_results(self) -> None:
        self.manager.generate_summary("conversation-001")
        self.manager.reference_context(
            "conversation-001",
            memories=("memory-001",),
            skills=("skill.search",),
            agents=("planner",),
        )
        window = self.manager.conversation_window(
            "conversation-001",
            max_messages=2,
        )
        result = self.manager.search_messages(
            "conversation-001",
            "memory preference",
        )
        statistics = self.manager.context_statistics("conversation-001")

        self.assertEqual(window.message_count, 2)
        self.assertTrue(window.truncated)
        self.assertEqual(result.total_matches, 3)
        self.assertIsInstance(statistics, ContextStatistics)
        self.assertEqual(statistics.total_messages, 4)
        self.assertEqual(statistics.user_messages, 2)
        self.assertEqual(statistics.assistant_messages, 1)
        self.assertEqual(statistics.system_messages, 1)
        self.assertTrue(statistics.summary_available)
        self.assertEqual(statistics.referenced_total, 3)

    def test_manager_reference_integration_retains_only_immutable_identifiers(
        self,
    ) -> None:
        session = self.manager.reference_context(
            "conversation-001",
            memories=("memory-001",),
            skills=("skill.search",),
            agents=("planner",),
        )
        references = self.manager.context_references("conversation-001")

        self.assertEqual(session.context.referenced_memories, ("memory-001",))
        self.assertEqual(references.memories, ("memory-001",))
        self.assertEqual(references.skills, ("skill.search",))
        self.assertEqual(references.agents, ("planner",))
        self.assertEqual(self.memory.mutation_calls, 0)
        with self.assertRaises(FrozenInstanceError):
            references.skills = ()  # type: ignore[misc]

    def test_missing_reference_does_not_change_conversation(self) -> None:
        original = self.manager.get_conversation("conversation-001")

        with self.assertRaises(ReferenceNotFoundError):
            self.manager.reference_memories(
                "conversation-001",
                ("missing",),
            )

        self.assertEqual(
            self.manager.get_conversation("conversation-001"),
            original,
        )
        self.assertEqual(self.memory.mutation_calls, 0)

    def test_all_required_context_events_are_published_without_query_content(
        self,
    ) -> None:
        secret_query = "memory preference"
        self.manager.generate_summary("conversation-001")
        self.manager.detect_topic("conversation-001")
        self.manager.conversation_window("conversation-001", max_messages=2)
        self.manager.search_messages("conversation-001", secret_query)

        self.assertEqual(
            [event.name for event in self.events],
            [
                "conversation.summary_generated",
                "conversation.topic_changed",
                "conversation.window_updated",
                "conversation.search_completed",
            ],
        )
        search_event = self.events[-1]
        self.assertNotIn(secret_query, repr(search_event.payload))
        self.assertEqual(search_event.payload["query_length"], len(secret_query))

    def test_closed_conversation_allows_reads_but_rejects_context_mutations(
        self,
    ) -> None:
        self.manager.close_conversation("conversation-001")

        self.assertGreater(
            self.manager.search_messages("conversation-001", "memory").match_count,
            0,
        )
        self.assertGreater(
            self.manager.conversation_window("conversation-001").message_count,
            0,
        )
        self.assertEqual(
            self.manager.detect_topic("conversation-001", switch=False).topic,
            "memory",
        )
        with self.assertRaises(ConversationClosedError):
            self.manager.generate_summary("conversation-001")
        with self.assertRaises(ConversationClosedError):
            self.manager.detect_topic("conversation-001")
        with self.assertRaises(ConversationClosedError):
            self.manager.reference_skills(
                "conversation-001",
                ("skill.search",),
            )


if __name__ == "__main__":
    unittest.main()
