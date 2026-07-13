"""Focused Part 2 recovery tests for profile and conversational memory."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from AI.brain import BrainEngine
from AI.intent import IntentType, RuleBasedIntentClassifier
from AI.providers import Provider, ProviderResponse
from Memory import build_memory_integration_service, build_memory_services
from Skills import MemorySkill, SkillRequest, build_skill_services
from Skills.memory_commands import MemoryCommandParser, MemoryCommandScope


class _CapturingProvider(Provider):
    """Provider double that records the memory context supplied by Brain."""

    name = "capturing-provider"

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
            content="Personalized response generated.",
            provider_name=self.name,
            model="test-model",
        )


class MemoryContextRecoveryTests(unittest.TestCase):
    """Verify the existing SQLite service powers all recovered memory paths."""

    def setUp(self) -> None:
        self.temp_dir = Path("data") / "memory_context_test_tmp" / f"case_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.memory_services = build_memory_services(
            database_path=self.temp_dir / "memory.sqlite3",
        )
        self.memory_integration = build_memory_integration_service(
            storage=self.memory_services.storage,
            short_term_memory=self.memory_services.short_term_memory,
            long_term_memory=self.memory_services.long_term_memory,
            session_memory=self.memory_services.session_memory,
            profile_memory=self.memory_services.profile_memory,
            memory_search=self.memory_services.memory_search,
        )
        self.skill_services = build_skill_services()
        self.memory_skill = MemorySkill(memory_service=self.memory_integration)
        self.skill_services.registry.register(self.memory_skill)

    def _build_brain(self, provider: Provider | None = None) -> BrainEngine:
        return BrainEngine(
            provider=provider,
            skill_executor=self.skill_services.executor,
            memory_integration=self.memory_integration,
        )

    def test_profile_and_conversation_phrases_are_memory_commands(self) -> None:
        parser = MemoryCommandParser()
        classifier = RuleBasedIntentClassifier()
        expectations = {
            "what is my name": MemoryCommandScope.PROFILE,
            "show my profile": MemoryCommandScope.PROFILE,
            "what do you know about me": MemoryCommandScope.PROFILE,
            "what did I tell you about codename": MemoryCommandScope.CONVERSATION,
            "what did we discuss about launch": MemoryCommandScope.CONVERSATION,
            "recall our conversation": MemoryCommandScope.CONVERSATION,
        }

        for text, expected_scope in expectations.items():
            with self.subTest(text=text):
                command = parser.parse(text)
                self.assertIsNotNone(command)
                assert command is not None
                self.assertIs(command.scope, expected_scope)
                self.assertIs(classifier.classify(text).intent, IntentType.MEMORY)

    def test_profile_facts_store_recall_list_and_forget_through_brain(self) -> None:
        brain = self._build_brain()
        metadata = {"user_id": "profile-user"}

        remembered = brain.receive_text(
            "remember my name is Narottam",
            conversation_id="profile-conversation",
            metadata=metadata,
        )
        recalled = brain.receive_text(
            "what is my name",
            conversation_id="profile-conversation",
            metadata=metadata,
        )
        profile = brain.receive_text(
            "show my profile",
            conversation_id="profile-conversation",
            metadata=metadata,
        )
        forgotten = brain.receive_text(
            "forget my name",
            conversation_id="profile-conversation",
            metadata=metadata,
        )

        self.assertEqual(remembered.metadata["skill_name"], "memory.manage")
        self.assertIn("Narottam", recalled.message)
        self.assertIn("Narottam", profile.message)
        self.assertIn("successfully", forgotten.message)
        stored_profile = self.memory_services.profile_memory.load_profile("profile-user")
        self.assertIsNotNone(stored_profile)
        assert stored_profile is not None
        self.assertIsNone(stored_profile.display_name)
        self.assertIsNone(self.memory_integration.recall("my_name"))

    def test_conversation_recall_reads_only_the_active_sqlite_conversation(self) -> None:
        brain = self._build_brain()
        first = brain.receive_text(
            "The launch codename is Orion.",
            conversation_id="active-conversation",
        )
        assert first.context.session_id is not None
        self.memory_integration.store_conversation_turn(
            session_id="other-session",
            conversation_id="other-conversation",
            role="user",
            content="The private codename is Atlas.",
        )
        self.assertEqual(self.memory_integration.search("codename"), [])

        recalled = brain.receive_text(
            "what did I tell you about codename",
            conversation_id="active-conversation",
        )

        self.assertEqual(recalled.metadata["skill_name"], "memory.manage")
        self.assertIn("Orion", recalled.message)
        self.assertNotIn("Atlas", recalled.message)
        snapshot = self.memory_integration.snapshot_counts()
        self.assertGreaterEqual(snapshot.conversation_history_entries, 5)

    def test_contextual_recall_resolves_the_last_memory_key(self) -> None:
        brain = self._build_brain()

        brain.receive_text("remember favorite color is blue", conversation_id="context-conversation")
        recalled = brain.receive_text("recall it", conversation_id="context-conversation")

        self.assertIn("blue", recalled.message)
        self.assertEqual(recalled.metadata["skill_data"]["key"], "long_term:favorite_color")

    def test_profile_memory_is_supplied_to_provider_backed_ai_generation(self) -> None:
        provider = _CapturingProvider()
        brain = self._build_brain(provider=provider)

        brain.receive_text("remember my name is Narottam", conversation_id="ai-conversation")
        response = brain.receive_text("How should you greet me today?", conversation_id="ai-conversation")

        self.assertEqual(response.provider_name, provider.name)
        self.assertEqual(response.message, "Personalized response generated.")
        self.assertEqual(len(provider.calls), 1)
        messages, system_prompt = provider.calls[0]
        prompt_text = "\n".join(message["content"] for message in messages)
        self.assertIn("Narottam", prompt_text)
        self.assertIn("Narottam", system_prompt or "")

    def test_conversation_recall_without_an_active_session_fails_closed(self) -> None:
        result = self.memory_skill.execute(
            SkillRequest(
                text="what did I tell you about codename",
                conversation_id="missing-session",
            )
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.data["scope"], "conversation")
        self.assertEqual(result.data["results"], [])
        self.assertIn("No active conversation memory", result.message)


if __name__ == "__main__":
    unittest.main()
