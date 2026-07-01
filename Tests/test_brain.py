"""Tests for Brain 2.0 planning, skill execution, and memory integration."""

from __future__ import annotations

import unittest

from AI.brain import BrainEngine
from Core.optimization import RuntimeOptimizationService


class _FakeSkillResult:
    """Simple skill result object consumed by the Brain engine."""

    def __init__(self, *, handled: bool, message: str, skill_name: str = "help.catalog", confidence: float = 0.9) -> None:
        self.handled = handled
        self.message = message
        self.skill_name = skill_name
        self.confidence = confidence
        self.data = {"source": "test"}


class _FakeSkillExecutor:
    """Skill executor stub that handles help requests."""

    def execute_best(self, request, minimum_confidence: float = 0.45):
        if "help" in request.text.lower():
            return _FakeSkillResult(handled=True, message="Available skills:\nhelp.catalog: test")
        return None


class _FakeMemoryIntegration:
    """Memory integration stub that records persisted turns."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []

    def remember(self, key: str, value, *, scope: str = "both", importance: float = 0.0, metadata=None):
        return ({"key": key, "scope": scope},)

    def forget(self, key: str) -> bool:
        return True

    def build_context_summary(self, query: str | None = None, limit: int = 5) -> str | None:
        return "profile favorite_drink: tea"

    def store_conversation_turn(self, *, session_id: str, role: str, content: str, conversation_id: str | None = None, metadata=None):
        self.turns.append((role, content))
        return {"session_id": session_id, "role": role}


class BrainEngineStableReleaseTests(unittest.TestCase):
    """Verify Brain 2.0 behavior added for the stable release."""

    def test_brain_engine_executes_matching_skill_and_persists_turns(self) -> None:
        memory_integration = _FakeMemoryIntegration()
        runtime_optimizer = RuntimeOptimizationService()
        brain = BrainEngine(
            skill_executor=_FakeSkillExecutor(),
            memory_integration=memory_integration,
            runtime_optimizer=runtime_optimizer,
        )

        response = brain.receive_text("help me with skills", conversation_id="conv-1")

        self.assertEqual(response.provider_name, "skills-runtime")
        self.assertIn("Available skills", response.message)
        self.assertEqual(len(memory_integration.turns), 2)
        self.assertEqual(memory_integration.turns[0][0], "user")
        self.assertEqual(memory_integration.turns[1][0], "assistant")
        self.assertEqual(response.metadata["skill_name"], "help.catalog")
        self.assertTrue(any(step["name"] == "persist_memory" and step["status"] == "completed" for step in response.metadata["plan"]))
        snapshot = runtime_optimizer.snapshot()
        self.assertGreaterEqual(snapshot.counters["brain.requests"], 1)
        self.assertIn("brain.process", snapshot.metrics)


if __name__ == "__main__":
    unittest.main()
