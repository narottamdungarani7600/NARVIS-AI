"""Focused Part 3 regression tests for intelligent memory reasoning."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from AI.brain import BrainEngine
from AI.providers import Provider, ProviderResponse
from Core.optimization import RuntimeOptimizationService
from Memory import MemoryEntry, build_memory_integration_service, build_memory_services
from Skills import MemorySkill, build_skill_services


class _ContextCapturingProvider(Provider):
    """Capture the complete provider input used for context-fusion assertions."""

    name = "context-capturing-provider"

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[list[dict[str, str]], str | None]] = []

    async def complete_chat(
        self,
        messages,
        *,
        system_prompt=None,
        model=None,
        max_tokens=None,
        temperature=None,
        stream=False,
        context=None,
    ) -> ProviderResponse:
        self.calls.append((list(messages), system_prompt))
        return ProviderResponse(
            content="Aarav is 8 years old.",
            provider_name=self.name,
            model="test-model",
        )


class IntelligentMemoryReasoningTests(unittest.TestCase):
    """Protect ranking, fusion, pronoun, deletion, and cache behavior."""

    def setUp(self) -> None:
        self.temp_dir = Path("data") / "memory_reasoning_test_tmp" / f"case_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.optimizer = RuntimeOptimizationService()
        self.memory_services = build_memory_services(database_path=self.temp_dir / "memory.sqlite3")
        self.memory = build_memory_integration_service(
            storage=self.memory_services.storage,
            short_term_memory=self.memory_services.short_term_memory,
            long_term_memory=self.memory_services.long_term_memory,
            session_memory=self.memory_services.session_memory,
            profile_memory=self.memory_services.profile_memory,
            memory_search=self.memory_services.memory_search,
            runtime_optimizer=self.optimizer,
        )

    def _build_brain(self, provider: Provider | None = None) -> BrainEngine:
        skills = build_skill_services()
        skills.registry.register(MemorySkill(memory_service=self.memory))
        return BrainEngine(
            provider=provider,
            skill_executor=skills.executor,
            memory_integration=self.memory,
            runtime_optimizer=self.optimizer,
        )

    def _seed_memory_caches(self) -> None:
        self.optimizer.set("memory.retrieval", "sentinel", "stale")
        self.optimizer.set("brain.memory_summary", "sentinel", "stale")

    def _assert_memory_caches_invalidated(self) -> None:
        self.assertIsNone(self.optimizer.get("memory.retrieval", "sentinel"))
        self.assertIsNone(self.optimizer.get("brain.memory_summary", "sentinel"))

    def test_duplicate_scopes_merge_into_one_confident_logical_result(self) -> None:
        self.memory.remember("favorite_color", "blue", scope="both")

        results = self.memory.search("favorite color", limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, "blue")
        self.assertEqual(results[0].category, "long_term")
        self.assertGreater(results[0].metadata["confidence"], 0.0)
        summary = self.memory.build_context_summary("favorite color", limit=10)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.count("blue"), 1)

    def test_newer_memory_wins_when_scopes_conflict(self) -> None:
        self.memory.remember("home_city", "Mumbai", scope="long_term")
        self.memory.remember("home_city", "Ahmedabad", scope="short_term")

        recalled = self.memory.recall("home_city")
        results = self.memory.search("home city", limit=10)

        self.assertIsNotNone(recalled)
        assert recalled is not None
        self.assertEqual(recalled.value, "Ahmedabad")
        self.assertEqual(recalled.category, "short_term")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, "Ahmedabad")

    def test_deleted_and_forgotten_entries_are_never_retrieved(self) -> None:
        self.memory_services.storage.save(
            MemoryEntry(
                key="long_term:private_code",
                value="Atlas",
                category="long_term",
                metadata={"deleted": True},
            )
        )

        self.assertIsNone(self.memory.recall("private_code"))
        self.assertEqual(self.memory.search("private code"), [])
        self.assertIsNone(self.memory.build_context_summary("private code"))

        self.memory.remember_profile_fact("default", "my name", "Deleted Name")
        profile_entry = self.memory_services.storage.load("profile:default")
        self.assertIsNotNone(profile_entry)
        assert profile_entry is not None
        profile_entry.metadata["status"] = "forgotten"
        self.memory_services.storage.save(profile_entry)
        self.assertIsNone(self.memory.recall_profile("default"))
        self.assertIsNone(self.memory.recall_profile_fact("default", "my name"))

        self.memory.remember("private_code", "Orion", scope="both")
        self.assertTrue(self.memory.forget("private_code"))
        self.assertIsNone(self.memory.recall("private_code"))
        self.assertEqual(self.memory.search("private code"), [])

    def test_pronoun_recall_uses_only_the_active_conversation_subject(self) -> None:
        brain = self._build_brain()

        brain.receive_text("Remember my wife's name is Priya.", conversation_id="family")
        recalled = brain.receive_text("What is her name?", conversation_id="family")
        isolated = brain.receive_text("What is her name?", conversation_id="other-family")

        self.assertIn("Priya", recalled.message)
        self.assertIn("don't currently remember her name", isolated.message)

    def test_personal_fact_statements_recall_and_forget_naturally(self) -> None:
        brain = self._build_brain()
        conversation_id = "personal-facts"

        brain.receive_text("My name is Narottam.", conversation_id=conversation_id)
        name = brain.receive_text("What is my name?", conversation_id=conversation_id)
        brain.receive_text("I work at Sky Textiles.", conversation_id=conversation_id)
        company = brain.receive_text("What company do I work for?", conversation_id=conversation_id)
        brain.receive_text("My favorite color is blue.", conversation_id=conversation_id)
        color = brain.receive_text("What color do I like?", conversation_id=conversation_id)
        brain.receive_text("Forget my favorite color.", conversation_id=conversation_id)
        forgotten = brain.receive_text("What is my favorite color?", conversation_id=conversation_id)

        self.assertIn("Narottam", name.message)
        self.assertIn("Sky Textiles", company.message)
        self.assertIn("blue", color.message)
        self.assertEqual(forgotten.message, "I don't currently remember your favorite color.")

    def test_profile_fact_outranks_newer_long_and_short_term_conflicts(self) -> None:
        self.memory.remember_profile_fact("default", "my company", "Sky Textiles")
        self.memory.remember(
            "my_company",
            "Outdated Textiles",
            scope="both",
            metadata={"user_id": "default"},
        )

        results = self.memory.search("company", limit=10)
        response = self._build_brain().receive_text("What company do I work for?", conversation_id="work")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, "profile")
        self.assertEqual(results[0].metadata["confidence"], 0.99)
        self.assertIn("Sky Textiles", response.message)
        self.assertNotIn("Outdated Textiles", response.message)

    def test_retrieval_and_brain_caches_invalidate_on_every_retrievable_mutation(self) -> None:
        mutations = (
            lambda: self.memory.remember("drink", "tea", scope="long_term"),
            lambda: self.memory.remember("drink", "coffee", scope="long_term"),
            lambda: self.memory.forget("drink"),
            lambda: self.memory.remember_profile_fact("default", "my name", "Narottam"),
            lambda: self.memory.forget_profile_fact("default", "my name"),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self._seed_memory_caches()
                mutation()
                self._assert_memory_caches_invalidated()

    def test_context_fusion_supplies_conversation_profile_long_and_short_term_memory(self) -> None:
        provider = _ContextCapturingProvider()
        self.memory.remember_profile_fact("default", "my son", "Aarav")
        self.memory.remember("son_age", "Aarav is 8 years old", scope="long_term")
        self.memory.remember("age_note", "He is eight years old", scope="short_term")
        brain = self._build_brain(provider=provider)

        brain.receive_text("We are discussing Aarav's birthday.", conversation_id="fusion")
        response = brain.receive_text("How old is he?", conversation_id="fusion")

        self.assertEqual(response.message, "Aarav is 8 years old.")
        self.assertEqual(len(provider.calls), 2)
        messages, system_prompt = provider.calls[-1]
        prompt_text = "\n".join(message["content"] for message in messages)
        self.assertIn("We are discussing Aarav's birthday.", prompt_text)
        self.assertIn("profile profile:default", prompt_text)
        self.assertIn("long_term:son_age", prompt_text)
        self.assertIn("short_term:age_note", prompt_text)
        self.assertIn("confidence=", prompt_text)
        self.assertIn("one fused context", system_prompt or "")
        self.assertLess(prompt_text.index("profile profile:default"), prompt_text.index("long_term:son_age"))
        self.assertLess(prompt_text.index("long_term:son_age"), prompt_text.index("short_term:age_note"))


if __name__ == "__main__":
    unittest.main()
