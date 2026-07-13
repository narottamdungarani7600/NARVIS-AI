"""Focused recovery tests for natural-language memory routing."""

from __future__ import annotations

import unittest

from AI.brain import BrainEngine
from AI.intent import IntentClassification, IntentType, RuleBasedIntentClassifier
from AI.router import IntentRouter
from Skills import MemorySkill, SkillRequest, build_skill_services
from Skills.memory_commands import MemoryCommandAction, MemoryCommandParser


class _MemoryEntry:
    """Minimal entry shape returned by the focused memory-service stub."""

    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class _MemoryService:
    """In-memory test double matching the existing MemoryIntegration API."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def remember(self, key: str, value: str, *, scope: str = "both", importance: float = 0.0, metadata=None):
        self.items[key] = value
        return (_MemoryEntry(key, value),)

    def recall(self, key: str):
        value = self.items.get(key)
        return _MemoryEntry(key, value) if value is not None else None

    def forget(self, key: str) -> bool:
        return self.items.pop(key, None) is not None

    def search(self, query: str, category: str | None = None, limit: int = 10):
        normalized = query.lower()
        return [
            _MemoryEntry(key, value)
            for key, value in self.items.items()
            if normalized in key.replace("_", " ").lower() or normalized in value.lower()
        ][:limit]


class _CountingSkillExecutor:
    """Count Brain skill dispatches while delegating to the real skill executor."""

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls: list[tuple[str, float]] = []

    def execute_best(self, request, minimum_confidence: float = 0.45):
        self.calls.append((request.text, minimum_confidence))
        return self.delegate.execute_best(request, minimum_confidence=minimum_confidence)


class MemoryRoutingRecoveryTests(unittest.TestCase):
    """Verify one shared intent route reaches the existing memory service."""

    def setUp(self) -> None:
        self.memory_service = _MemoryService()
        self.skill_services = build_skill_services()
        self.memory_skill = MemorySkill(memory_service=self.memory_service)
        self.skill_services.registry.register(self.memory_skill)

    def test_common_memory_verbs_classify_and_route_to_skills(self) -> None:
        classifier = RuleBasedIntentClassifier()
        router = IntentRouter()
        commands = (
            "remember my name is Narottam",
            "recall my name",
            "forget my name",
            "save my company",
            "store this",
            "note project is NARVIS",
            "delete memory my company",
        )

        for text in commands:
            with self.subTest(text=text):
                classification = classifier.classify(text)
                route = router.route(classification)
                self.assertIs(classification.intent, IntentType.MEMORY)
                self.assertEqual(route.name, "Skills")
                self.assertEqual(route.metadata["intent"], "memory")

    def test_memory_parser_extracts_addressable_key_and_value(self) -> None:
        parser = MemoryCommandParser()

        store = parser.parse("remember my name is Narottam")
        recall = parser.parse("recall my name")
        forget = parser.parse("delete memory my name")

        assert store is not None
        assert recall is not None
        assert forget is not None
        self.assertIs(store.action, MemoryCommandAction.STORE)
        self.assertEqual(store.key, "my_name")
        self.assertEqual(store.value, "Narottam")
        self.assertIs(recall.action, MemoryCommandAction.RECALL)
        self.assertEqual(recall.key, "my_name")
        self.assertIs(forget.action, MemoryCommandAction.FORGET)
        self.assertEqual(forget.key, "my_name")

    def test_brain_remember_recall_forget_flow_uses_memory_skill_once_per_turn(self) -> None:
        counting_executor = _CountingSkillExecutor(self.skill_services.executor)
        brain = BrainEngine(skill_executor=counting_executor)

        remembered = brain.receive_text(
            "remember my name is Narottam",
            conversation_id="memory-conversation",
        )
        recalled = brain.receive_text(
            "recall my name",
            conversation_id="memory-conversation",
        )
        forgotten = brain.receive_text(
            "forget my name",
            conversation_id="memory-conversation",
        )

        for response in (remembered, recalled, forgotten):
            self.assertIs(response.intent.intent, IntentType.MEMORY)
            self.assertEqual(response.route.name, "Skills")
            self.assertEqual(response.provider_name, "skills-runtime")
            self.assertEqual(response.metadata["skill_name"], "memory.manage")
        self.assertEqual(self.memory_service.items, {})
        self.assertIn("Narottam", recalled.message)
        self.assertIn("Forgot", forgotten.message)
        self.assertIn("successfully", forgotten.message)
        self.assertEqual(len(counting_executor.calls), 3)
        self.assertTrue(all(threshold == 0.35 for _, threshold in counting_executor.calls))
        history = brain.context_manager.get_history("memory-conversation")
        self.assertEqual(len(history), 6)

    def test_save_store_note_and_delete_memory_use_existing_memory_api(self) -> None:
        requests = (
            SkillRequest(text="save my company", conversation_id="conv-1"),
            SkillRequest(text="store this", conversation_id="conv-1"),
            SkillRequest(text="note project is NARVIS", conversation_id="conv-1"),
        )

        results = [self.skill_services.executor.execute_best(request, minimum_confidence=0.35) for request in requests]

        self.assertTrue(all(result is not None and result.handled for result in results))
        self.assertEqual(self.memory_service.items["my_company"], "my company")
        self.assertEqual(self.memory_service.items["this"], "this")
        self.assertEqual(self.memory_service.items["project"], "NARVIS")
        deleted = self.skill_services.executor.execute_best(
            SkillRequest(text="delete memory my company", conversation_id="conv-1"),
            minimum_confidence=0.35,
        )
        assert deleted is not None
        self.assertTrue(deleted.handled)
        self.assertTrue(deleted.data["removed"])
        self.assertNotIn("my_company", self.memory_service.items)

    def test_incomplete_memory_commands_fail_closed_without_storage(self) -> None:
        for text in ("remember", "recall", "forget", "delete memory"):
            with self.subTest(text=text):
                result = self.skill_services.executor.execute_best(
                    SkillRequest(text=text),
                    minimum_confidence=0.35,
                )
                self.assertIsNotNone(result)
                self.assertTrue(result.handled)
        self.assertEqual(self.memory_service.items, {})

    def test_unrelated_text_is_not_claimed_by_memory_skill(self) -> None:
        match = self.memory_skill.match(SkillRequest(text="open the calculator"))
        result = self.memory_skill.execute(SkillRequest(text="open the calculator"))

        self.assertEqual(match.confidence, 0.0)
        self.assertFalse(result.handled)


if __name__ == "__main__":
    unittest.main()
