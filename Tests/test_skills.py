"""Tests for the Skills framework and built-in stable skill pack."""

from __future__ import annotations

import unittest

from Core.system import DependencyContainer
from Core.system import HealthReport
from Internet import NewsQuery
from Skills import (
    build_builtin_skills,
    build_desktop_command_services,
    build_skill_services,
    DesktopCommandSkill,
    register_desktop_command_services,
)


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

    def __init__(self) -> None:
        self.news_calls: list[tuple[object | None, int]] = []
        self.news_results: list[object] = []
        self.weather_calls: list[str] = []
        self.wikipedia_results: list[object] = []
        self.wikipedia_calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int = 5):
        return []

    def fetch_weather(self, location: str):
        self.weather_calls.append(location)
        return type("Weather", (), {"location": location, "condition": "clear", "temperature_c": 24.0})()

    def fetch_news(self, topic: str | None = None, limit: int = 5):
        self.news_calls.append((topic, limit))
        return list(self.news_results)

    def search_wikipedia(self, query: str, limit: int = 3):
        self.wikipedia_calls.append((query, limit))
        return list(self.wikipedia_results)

    def search_youtube(self, query: str, limit: int = 3):
        return []


class _DesktopControl:
    """Minimal desktop-control stub used by built-in skill tests."""

    def __init__(self) -> None:
        self.clipboard_text = ""
        self.typed_text: list[str] = []
        self.pressed_keys: list[str] = []
        self.opened_applications: list[str] = []
        self.closed_applications: list[str] = []
        self.focused_windows: list[str] = []

    def capture_screenshot(self):
        return type("Result", (), {"message": "Screenshot saved.", "data": {"path": "shot.png"}})()

    def read_clipboard(self):
        text = self.clipboard_text or "memo"
        return type("Result", (), {"message": "Clipboard read successfully.", "data": {"text": text}})()

    def write_clipboard(self, text: str):
        self.clipboard_text = text
        return type("Result", (), {"message": "Clipboard updated successfully.", "data": {"text": text}})()

    def type_text(self, text: str):
        self.typed_text.append(text)
        return type("Result", (), {"message": "Typed text successfully.", "data": {"text": text}})()

    def press_key(self, key: str):
        self.pressed_keys.append(key)
        return type("Result", (), {"message": f"Pressed key '{key}'.", "data": {"key": key}})()

    def open_application(self, app_name: str):
        self.opened_applications.append(app_name)
        return type("Result", (), {"message": f"Opened {app_name}.", "data": {"application": app_name}})()

    def close_application(self, app_name: str):
        self.closed_applications.append(app_name)
        return type("Result", (), {"message": f"Closed {app_name}.", "data": {"application": app_name}})()

    def list_windows(self):
        return type(
            "Result",
            (),
            {
                "message": "Found 2 window(s).",
                "data": {
                    "windows": [
                        {"title": "Editor", "is_active": True},
                        {"title": "Browser", "is_active": False},
                    ]
                },
            },
        )()

    def focus_window(self, title: str):
        self.focused_windows.append(title)
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

    def test_desktop_skill_handles_natural_language_question_commands(self) -> None:
        request = type(
            "Request",
            (),
            {
                "text": "Could you take a screenshot for me?",
                "route": "AI",
                "metadata": {"intent": "question", "intent_confidence": 0.59, "route_name": "AI"},
                "conversation_id": None,
                "session_id": None,
            },
        )()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.65)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "desktop.control")
        self.assertEqual(result.data["path"], "shot.png")

    def test_desktop_skill_preserves_v1_copy_command_behavior(self) -> None:
        request = type(
            "Request",
            (),
            {"text": "copy Release 1.1 notes", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None},
        )()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(self.desktop_control.clipboard_text, "Release 1.1 notes")
        self.assertEqual(result.data["text"], "Release 1.1 notes")

    def test_desktop_skill_supports_kholo_open_requests(self) -> None:
        request = type(
            "Request",
            (),
            {"text": "Photoshop kholo", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None},
        )()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(self.desktop_control.opened_applications, ["Photoshop"])
        self.assertEqual(result.data["application"], "Photoshop")

    def test_desktop_command_skill_wrapper_delegates_to_pipeline(self) -> None:
        services = build_desktop_command_services(desktop_control=self.desktop_control)
        wrapper_skill = DesktopCommandSkill(
            name="desktop.command",
            description="Natural language desktop command skill",
            desktop_control=self.desktop_control,
            command_pipeline=services.pipeline,
        )
        request = type("Request", (), {"text": "take a screenshot", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = wrapper_skill.execute(request)

        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "desktop.command")
        self.assertEqual(result.data["path"], "shot.png")
        self.assertEqual(result.data["command_skill"], "desktop.command.screenshot")

    def test_internet_skill_preserves_weather_output_formatting(self) -> None:
        request = type("Request", (), {"text": "weather today in Ahmedabad", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "internet.query")
        self.assertEqual(self.internet_service.weather_calls, ["Ahmedabad"])
        self.assertEqual(result.message, "Weather for Ahmedabad: clear, 24.0 C")
        self.assertEqual(result.data["location"], "Ahmedabad")

    def test_internet_skill_formats_news_results_with_source_and_url(self) -> None:
        self.internet_service.news_results = [
            type(
                "Article",
                (),
                {
                    "title": "Kingfisher expands habitat range",
                    "source": "The Daily Planet",
                    "published_at": "2026-07-07T01:25:38Z",
                    "url": "https://example.com/kingfisher",
                },
            )()
        ]
        request = type("Request", (), {"text": "news about Kingfisher", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "internet.query")
        self.assertEqual(self.internet_service.news_calls, [("Kingfisher", 5)])
        self.assertIn("News results:", result.message)
        self.assertIn("Kingfisher expands habitat range", result.message)
        self.assertIn("The Daily Planet", result.message)
        self.assertIn("https://example.com/kingfisher", result.message)
        self.assertEqual(
            result.data["results"],
            [
                "Kingfisher expands habitat range - The Daily Planet | 2026-07-07T01:25:38Z - https://example.com/kingfisher"
            ],
        )

    def test_internet_skill_preserves_news_no_results_behavior(self) -> None:
        request = type("Request", (), {"text": "news about Unknown Topic", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "internet.query")
        self.assertEqual(self.internet_service.news_calls, [("Unknown Topic", 5)])
        self.assertEqual(result.message, "No news articles are available for 'Unknown Topic'.")

    def test_internet_skill_parses_source_aware_direct_news_requests(self) -> None:
        cases = (
            ("latest news from Sandesh", {"source": "Sandesh", "query_text": "Sandesh latest news"}),
            ("Sandesh news", {"source": "Sandesh", "query_text": "Sandesh news"}),
            ("Divya Bhaskar news", {"source": "Divya Bhaskar", "query_text": "Divya Bhaskar news"}),
            ("Aaj Tak latest news", {"source": "Aaj Tak", "query_text": "Aaj Tak latest news"}),
            ("आज तक latest news", {"source": "Aaj Tak", "query_text": "Aaj Tak latest news"}),
            ("સંદેશ news", {"source": "Sandesh", "query_text": "Sandesh news"}),
        )

        for text, expected in cases:
            with self.subTest(text=text):
                self.internet_service.news_calls.clear()
                request = type("Request", (), {"text": text, "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

                result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

                self.assertIsNotNone(result)
                self.assertTrue(result.handled)
                self.assertEqual(result.skill_name, "internet.query")
                self.assertEqual(len(self.internet_service.news_calls), 1)
                news_request, limit = self.internet_service.news_calls[0]
                self.assertEqual(limit, 5)
                self.assertIsInstance(news_request, NewsQuery)
                assert isinstance(news_request, NewsQuery)
                self.assertEqual(news_request.source, expected["source"])
                self.assertEqual(news_request.query_text, expected["query_text"])

    def test_internet_skill_parses_scoped_source_aware_news_requests(self) -> None:
        cases = (
            ("India Today world news", {"source": "India Today", "category": "world", "query_text": "India Today world news"}),
            ("Gujarat news", {"location": "Gujarat", "query_text": "Gujarat news"}),
            ("India news", {"location": "India", "query_text": "India news"}),
            ("Gujarat news from Sandesh", {"location": "Gujarat", "source": "Sandesh", "query_text": "Gujarat Sandesh news"}),
            ("Gujarat news from સંદેશ", {"location": "Gujarat", "source": "Sandesh", "query_text": "Gujarat Sandesh news"}),
            ("India news from Aaj Tak", {"location": "India", "source": "Aaj Tak", "query_text": "India Aaj Tak news"}),
            ("world news from India Today", {"source": "India Today", "category": "world", "query_text": "India Today world news"}),
        )

        for text, expected in cases:
            with self.subTest(text=text):
                self.internet_service.news_calls.clear()
                request = type("Request", (), {"text": text, "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

                result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

                self.assertIsNotNone(result)
                self.assertTrue(result.handled)
                self.assertEqual(result.skill_name, "internet.query")
                self.assertEqual(len(self.internet_service.news_calls), 1)
                news_request, _limit = self.internet_service.news_calls[0]
                self.assertIsInstance(news_request, NewsQuery)
                assert isinstance(news_request, NewsQuery)
                self.assertEqual(news_request.query_text, expected["query_text"])
                self.assertEqual(news_request.location, expected.get("location", ""))
                self.assertEqual(news_request.source, expected.get("source", ""))
                self.assertEqual(news_request.category, expected.get("category", ""))

    def test_internet_skill_parses_topic_plus_source_news_request(self) -> None:
        request = type(
            "Request",
            (),
            {"text": "latest news about Adobe from Sandesh", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None},
        )()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "internet.query")
        self.assertEqual(len(self.internet_service.news_calls), 1)
        news_request, limit = self.internet_service.news_calls[0]
        self.assertEqual(limit, 5)
        self.assertIsInstance(news_request, NewsQuery)
        assert isinstance(news_request, NewsQuery)
        self.assertEqual(news_request.topic, "Adobe")
        self.assertEqual(news_request.source, "Sandesh")
        self.assertEqual(news_request.query_text, "Adobe Sandesh latest news")

    def test_internet_skill_formats_wikipedia_results_with_canonical_url(self) -> None:
        self.internet_service.wikipedia_results = [
            type(
                "Wiki",
                (),
                {
                    "title": "Albert Einstein",
                    "summary": "Albert Einstein was a theoretical physicist.",
                    "url": "https://en.wikipedia.org/wiki/Albert_Einstein",
                },
            )()
        ]
        request = type("Request", (), {"text": "wikipedia Albert Einstein", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "internet.query")
        self.assertEqual(self.internet_service.wikipedia_calls, [("Albert Einstein", 3)])
        self.assertIn("Wikipedia results:", result.message)
        self.assertIn("Albert Einstein - Albert Einstein was a theoretical physicist.", result.message)
        self.assertIn("https://en.wikipedia.org/wiki/Albert_Einstein", result.message)
        self.assertEqual(
            result.data["results"],
            [
                "Albert Einstein - Albert Einstein was a theoretical physicist. - https://en.wikipedia.org/wiki/Albert_Einstein"
            ],
        )

    def test_internet_skill_preserves_wikipedia_no_results_behavior(self) -> None:
        request = type("Request", (), {"text": "wikipedia Unknown Topic", "route": "Skills", "metadata": {}, "conversation_id": None, "session_id": None})()

        result = self.skill_services.executor.execute_best(request, minimum_confidence=0.2)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertEqual(result.skill_name, "internet.query")
        self.assertEqual(self.internet_service.wikipedia_calls, [("Unknown Topic", 3)])
        self.assertEqual(result.message, "No Wikipedia results are available for 'Unknown Topic'.")


class DesktopCommandRegistrationTests(unittest.TestCase):
    """Verify the natural-language desktop command services register cleanly."""

    def test_register_desktop_command_services_exposes_runtime_dependencies(self) -> None:
        container = DependencyContainer()
        services = build_desktop_command_services(desktop_control=_DesktopControl())

        register_desktop_command_services(container, services)

        self.assertIs(container.resolve("desktop_command_registry"), services.registry)
        self.assertIs(container.resolve("desktop_command_executor"), services.executor)
        self.assertIs(container.resolve("desktop_command_pipeline"), services.pipeline)
        self.assertIs(container.resolve("natural_language_command_pipeline"), services.pipeline)


if __name__ == "__main__":
    unittest.main()
