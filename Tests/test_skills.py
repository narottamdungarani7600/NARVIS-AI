"""Tests for the Skills framework and built-in stable skill pack."""

from __future__ import annotations

import unittest

from Core.system import HealthReport
from Skills import build_builtin_skills, build_skill_services


class _MemoryService:
    """Minimal memory service stub used by the built-in memory skill tests."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def remember(self, key: str, value: str, *, scope: str = "both", importance: float = 0.0, metadata=None):
        self.items[key] = value
        return ({"key": key, "scope": scope},)

    def forget(self, key: str) -> bool:
        return self.items.pop(key, None) is not None

    def recall(self, key: str):
        value = self.items.get(key)
        if value is None:
            return None
        return type("Entry", (), {"key": key, "value": value})()

    def search(self, query: str, category: str | None = None, limit: int = 10):
        return [
            type("Entry", (), {"key": key, "value": value})()
            for key, value in self.items.items()
            if query.lower() in value.lower() or query.lower() in key.lower()
        ][:limit]


class _InternetService:
    """Minimal internet service stub used by built-in skill tests."""

    def search(self, query: str, limit: int = 5):
        return []

    def fetch_weather(self, location: str):
        return type("Weather", (), {"location": location, "condition": "clear", "temperature_c": 24.0})()

    def fetch_news(self, topic: str | None = None, limit: int = 5):
        return []

    def search_wikipedia(self, query: str, limit: int = 3):
        return []

    def search_youtube(self, query: str, limit: int = 3):
        return []


class _DesktopControl:
    """Minimal desktop-control stub used by built-in skill tests."""

    def capture_screenshot(self):
        return type("Result", (), {"message": "Screenshot saved.", "data": {"path": "shot.png"}})()

    def read_clipboard(self):
        return type("Result", (), {"message": "Clipboard read successfully.", "data": {"text": "memo"}})()

    def write_clipboard(self, text: str):
        return type("Result", (), {"message": "Clipboard updated successfully.", "data": {"text": text}})()

    def open_application(self, app_name: str):
        return type("Result", (), {"message": f"Opened {app_name}.", "data": {"application": app_name}})()

    def focus_window(self, title: str):
        return type("Result", (), {"message": f"Focused {title}.", "data": {"title": title}})()


class SkillFrameworkTests(unittest.TestCase):
    """Verify the built-in skill pack can be registered and executed."""

    def setUp(self) -> None:
        self.memory_service = _MemoryService()
        self.internet_service = _InternetService()
        self.desktop_control = _DesktopControl()
        self.skill_services = build_skill_services()
        builtin_skills = build_builtin_skills(
            memory_service=self.memory_service,
            internet_service=self.internet_service,
            desktop_control=self.desktop_control,
            health_provider=lambda: {"brain": HealthReport(name="brain", status="ok")},
            catalog_provider=lambda: [
                {"name": skill.name, "description": skill.description}
                for skill in self.skill_services.registry.list_skills()
            ],
        )
        for skill in builtin_skills:
            self.skill_services.registry.register(skill)

    def test_help_skill_lists_registered_skills(self) -> None:
        request = type("Request", (), {"text": "help me with skills", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertIn("memory.manage", result.message)

    def test_memory_skill_can_remember_and_recall(self) -> None:
        remember_request = type("Request", (), {"text": "remember favorite drink is tea", "route": "Skills", "metadata": {}, "conversation_id": "conv-1", "session_id": "session-1"})()
        recall_request = type("Request", (), {"text": "recall favorite drink", "route": "Skills", "metadata": {}, "conversation_id": "conv-1", "session_id": "session-1"})()

        remember_result = self.skill_services.executor.execute_best(remember_request, minimum_confidence=0.2)
        recall_result = self.skill_services.executor.execute_best(recall_request, minimum_confidence=0.2)

        self.assertIsNotNone(remember_result)
        self.assertIsNotNone(recall_result)
        self.assertTrue(remember_result.handled)
        self.assertTrue(recall_result.handled)
        self.assertIn("Remembered", remember_result.message)
        self.assertIn("favorite drink", recall_result.message.lower())

    def test_desktop_skill_can_capture_screenshot(self) -> None:
        request = type("Request", (), {"text": "take a screenshot", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.data["path"], "shot.png")


if __name__ == "__main__":
    unittest.main()
