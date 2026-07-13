"""Tests for the stable runtime service integrations added in NARVIS v1.0."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import shutil
from uuid import uuid4

from Automation import AutomationAction, build_automation_services
from AI.providers import ProviderResponse, ProviderUsage
from Core.optimization import RuntimeOptimizationService
from Internet import (
    GoogleNewsRssProvider,
    GroundedResearchResponse,
    MediaWikiWikipediaProvider,
    NewsArticle,
    NewsQuery,
    OpenMeteoWeatherProvider,
    ResearchQuery,
    SearchResult,
    WeatherReport,
    WikipediaResult,
    build_internet_services,
)
from Memory import build_memory_integration_service, build_memory_services
import narvis
from narvis import NARVISApplication


def _workspace_temp_dir() -> str:
    """Create a temporary directory inside the writable workspace."""

    root = Path.cwd() / "data" / "test_runtime_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class _FakeSearchProvider:
    """Search provider stub that records how often it is queried."""

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.calls += 1
        return [SearchResult(title=f"Result for {query}", url=f"https://example.com/{query.replace(' ', '-')}")]


class _FakeWikipediaProvider:
    """Wikipedia provider stub that records how often it is queried."""

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        self.calls += 1
        return [
            WikipediaResult(
                title=f"{query} article",
                summary=f"{query} summary",
                url=f"https://en.wikipedia.org/wiki/{query.replace(' ', '_')}",
            )
        ]


class _FakeNewsProvider:
    """News provider stub that records how often it is queried."""

    def __init__(self) -> None:
        self.calls = 0
        self.requested_topics: list[object] = []

    def fetch(self, topic=None, limit: int = 10) -> list[NewsArticle]:
        self.calls += 1
        self.requested_topics.append(topic)
        requested_topic = getattr(topic, "query_text", "") or getattr(topic, "topic", "") or str(topic or "latest")
        return [
            NewsArticle(
                title=f"{requested_topic} headline",
                url=f"https://example.com/{requested_topic.replace(' ', '-').lower()}",
                source="Example News",
            )
        ]


class _FakeWeatherProvider:
    """Weather provider stub that records how often it is queried."""

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, location: str) -> WeatherReport:
        self.calls += 1
        return WeatherReport(location=f"{location}, India", condition="clear sky", temperature_c=31.5)


class _FakeHttpClient:
    """HTTP client stub used to verify provider wiring without live network."""

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict:
        return {"status": 200, "json": {}}

    def post(
        self,
        url: str,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict:
        return {"status": 200, "json": {}}


class _QueuedFeedHttpClient:
    """HTTP client stub that returns queued RSS payloads without live network access."""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, object]:
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("Unexpected GET request")
        return self.responses.pop(0)

    def post(
        self,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        raise AssertionError("POST should not be used by the news provider")


def _grounded_research_response(topic: str, *, search_text: str | None = None) -> GroundedResearchResponse:
    """Build one deterministic grounded response for application-path tests."""

    resolved_search_text = search_text or topic
    return GroundedResearchResponse(
        query=ResearchQuery(topic, topic, resolved_search_text),
        answer=f"{topic} summary",
        sources=(),
        provider_name="stub-research",
        search_result_count=1,
        pages_read_count=1,
        search_provider_name="stub-search",
    )


class RuntimeAutomationTests(unittest.TestCase):
    """Verify automation runtime services remain safe and deterministic."""

    def test_workspace_file_actions_round_trip_text(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        services = build_automation_services(workspace_root=temp_dir)

        write_result = services.automation_service.execute(
            AutomationAction(name="file.write_text", payload={"path": "notes\\memo.txt", "content": "stable release"})
        )
        read_result = services.automation_service.execute(
            AutomationAction(name="file.read_text", payload={"path": "notes\\memo.txt"})
        )

        self.assertTrue(write_result.success)
        self.assertTrue(read_result.success)
        self.assertEqual(read_result.data["content"], "stable release")

    def test_workspace_file_actions_reject_escape_paths(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        services = build_automation_services(workspace_root=temp_dir)
        outside_path = Path(temp_dir).parent / "escape.txt"

        result = services.automation_service.execute(
            AutomationAction(name="file.write_text", payload={"path": str(outside_path), "content": "blocked"})
        )

        self.assertFalse(result.success)
        self.assertIn("outside the workspace root", result.error or "")


class RuntimeInternetTests(unittest.TestCase):
    """Verify internet runtime helpers add caching on top of providers."""

    def test_internet_service_caches_search_results(self) -> None:
        provider = _FakeSearchProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(search_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.search("narvis stable", limit=5)
        second = services.internet_service.search("narvis stable", limit=5)
        history = services.internet_service.history()

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(provider.calls, 1)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)

    def test_internet_service_caches_wikipedia_results_and_records_history(self) -> None:
        provider = _FakeWikipediaProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(wikipedia_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.search_wikipedia("Albert Einstein", limit=3)
        second = services.internet_service.search_wikipedia("Albert Einstein", limit=3)
        history = [record for record in services.internet_service.history() if record.operation == "wikipedia"]

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(history), 2)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)
        self.assertEqual(history[0].target, "Albert Einstein")
        self.assertEqual(history[0].item_count, 1)

    def test_internet_service_caches_news_results_and_records_history(self) -> None:
        provider = _FakeNewsProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(news_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.fetch_news("world news", limit=4)
        second = services.internet_service.fetch_news("world news", limit=4)
        history = [record for record in services.internet_service.history() if record.operation == "news"]

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(history), 2)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)
        self.assertEqual(history[0].target, "world news")
        self.assertEqual(history[0].item_count, 1)

    def test_internet_service_canonicalizes_equivalent_top_news_aliases_for_cache_and_history(self) -> None:
        provider = _FakeNewsProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(news_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.fetch_news(None, limit=4)
        second = services.internet_service.fetch_news("latest news", limit=4)
        third = services.internet_service.fetch_news("top news", limit=4)
        history = [record for record in services.internet_service.history() if record.operation == "news"]

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(len(third), 1)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(provider.requested_topics), 1)
        self.assertIsInstance(provider.requested_topics[0], NewsQuery)
        assert isinstance(provider.requested_topics[0], NewsQuery)
        self.assertEqual(provider.requested_topics[0].query_text, "latest news")
        self.assertEqual(provider.requested_topics[0].category, "top")
        self.assertEqual([record.target for record in history], ["latest|latest news|top"] * 3)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)
        self.assertTrue(history[2].cached)

    def test_internet_service_canonicalizes_equivalent_source_aliases_for_cache_and_history(self) -> None:
        provider = _FakeNewsProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(news_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.fetch_news("Sandesh news", limit=4)
        second = services.internet_service.fetch_news(NewsQuery(request_type="search", source="સંદેશ"), limit=4)
        third = services.internet_service.fetch_news("sandesh samachar", limit=4)
        history = [record for record in services.internet_service.history() if record.operation == "news"]

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(len(third), 1)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(provider.requested_topics), 1)
        self.assertIsInstance(provider.requested_topics[0], NewsQuery)
        assert isinstance(provider.requested_topics[0], NewsQuery)
        self.assertEqual(provider.requested_topics[0].source, "Sandesh")
        self.assertEqual(provider.requested_topics[0].query_text, "Sandesh news")
        self.assertEqual([record.target for record in history], ["search|Sandesh news|Sandesh"] * 3)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)
        self.assertTrue(history[2].cached)

    def test_internet_service_keeps_generic_topic_location_and_source_news_targets_distinct(self) -> None:
        provider = _FakeNewsProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(news_provider=provider, runtime_optimizer=runtime_optimizer)

        services.internet_service.fetch_news(None, limit=4)
        services.internet_service.fetch_news("world news", limit=4)
        services.internet_service.fetch_news(NewsQuery(request_type="search", topic="Adobe", query_text="Adobe latest news"), limit=4)
        services.internet_service.fetch_news(NewsQuery(request_type="search", location="India", query_text="India news"), limit=4)
        services.internet_service.fetch_news(NewsQuery(request_type="search", source="Reuters", query_text="Reuters news"), limit=4)
        history = [record for record in services.internet_service.history() if record.operation == "news"]

        self.assertEqual(provider.calls, 5)
        self.assertEqual(
            [record.target for record in history],
            [
                "latest|latest news|top",
                "world news",
                "search|Adobe latest news|Adobe",
                "search|India news|India",
                "search|Reuters news|Reuters",
            ],
        )

    def test_internet_service_keeps_source_topic_location_and_world_news_targets_distinct(self) -> None:
        provider = _FakeNewsProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(news_provider=provider, runtime_optimizer=runtime_optimizer)

        services.internet_service.fetch_news(NewsQuery(request_type="search", source="Sandesh"), limit=4)
        services.internet_service.fetch_news(NewsQuery(request_type="search", location="Gujarat", source="સંદેશ"), limit=4)
        services.internet_service.fetch_news(NewsQuery(request_type="search", topic="Adobe", source="sandesh news"), limit=4)
        services.internet_service.fetch_news(NewsQuery(request_type="search", source="indiatoday", category="world"), limit=4)
        history = [record for record in services.internet_service.history() if record.operation == "news"]

        self.assertEqual(provider.calls, 4)
        self.assertEqual(
            [record.target for record in history],
            [
                "search|Sandesh news|Sandesh",
                "search|Gujarat Sandesh news|Gujarat|Sandesh",
                "search|Adobe Sandesh news|Adobe|Sandesh",
                "search|India Today world news|India Today|world",
            ],
        )

    def test_internet_service_keeps_news_cache_and_history_keys_stable_after_provider_dedupe_and_ranking(self) -> None:
        http_client = _QueuedFeedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Adobe creator tools update</title>
                              <link>https://news.google.com/rss/articles/weak</link>
                              <description>Adobe update from a regional Sandesh desk.</description>
                              <source>Sandesh Gujarati Edition</source>
                            </item>
                            <item>
                              <title>Adobe creator tools update</title>
                              <link>https://news.google.com/rss/articles/exact</link>
                              <description>Adobe update from Sandesh.</description>
                              <pubDate>Tue, 07 Jul 2026 03:25:38 GMT</pubDate>
                              <source>Sandesh</source>
                            </item>
                            <item>
                              <title>Adobe creator tools update</title>
                              <link>https://news.google.com/rss/articles/exact-older</link>
                              <description>Adobe update from Sandesh.</description>
                              <pubDate>Tue, 07 Jul 2026 01:25:38 GMT</pubDate>
                              <source>Sandesh</source>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(http_client=http_client, runtime_optimizer=runtime_optimizer)
        request = NewsQuery(request_type="search", topic="Adobe", source="Sandesh", query_text="Adobe Sandesh latest news")

        with mock.patch.object(services.news_provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            first = services.internet_service.fetch_news(request, limit=5)
            second = services.internet_service.fetch_news(request, limit=5)

        history = [record for record in services.internet_service.history() if record.operation == "news"]

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual([article.source for article in first], ["Sandesh", "Sandesh Gujarati Edition"])
        self.assertEqual([record.target for record in history], ["search|Adobe Sandesh latest news|Adobe|Sandesh"] * 2)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)

    def test_internet_service_caches_weather_reports_and_records_history(self) -> None:
        provider = _FakeWeatherProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(weather_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.fetch_weather("Ahmedabad")
        second = services.internet_service.fetch_weather("Ahmedabad")
        history = [record for record in services.internet_service.history() if record.operation == "weather"]

        self.assertEqual(first.location, "Ahmedabad, India")
        self.assertEqual(second.location, "Ahmedabad, India")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(history), 2)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)
        self.assertEqual(history[0].target, "Ahmedabad")
        self.assertEqual(history[0].item_count, 1)

    def test_build_internet_services_uses_live_weather_provider_by_default(self) -> None:
        http_client = _FakeHttpClient()

        services = build_internet_services(http_client=http_client)

        self.assertIsInstance(services.weather_provider, OpenMeteoWeatherProvider)
        self.assertIs(services.weather_provider.http_client, http_client)
        self.assertIs(services.internet_service.weather_provider, services.weather_provider)

    def test_build_internet_services_preserves_explicit_weather_provider_override(self) -> None:
        provider = _FakeWeatherProvider()

        services = build_internet_services(weather_provider=provider)

        self.assertIs(services.weather_provider, provider)
        self.assertIs(services.internet_service.weather_provider, provider)

    def test_build_internet_services_uses_live_news_provider_by_default(self) -> None:
        http_client = _FakeHttpClient()

        services = build_internet_services(http_client=http_client)

        self.assertIsInstance(services.news_provider, GoogleNewsRssProvider)
        self.assertIs(services.news_provider.http_client, http_client)
        self.assertIs(services.internet_service.news_provider, services.news_provider)

    def test_build_internet_services_preserves_explicit_news_provider_override(self) -> None:
        provider = _FakeNewsProvider()

        services = build_internet_services(news_provider=provider)

        self.assertIs(services.news_provider, provider)
        self.assertIs(services.internet_service.news_provider, provider)

    def test_build_internet_services_uses_live_wikipedia_provider_by_default(self) -> None:
        http_client = _FakeHttpClient()

        services = build_internet_services(http_client=http_client)

        self.assertIsInstance(services.wikipedia_provider, MediaWikiWikipediaProvider)
        self.assertIs(services.wikipedia_provider.http_client, http_client)
        self.assertIs(services.internet_service.wikipedia_provider, services.wikipedia_provider)

    def test_build_internet_services_preserves_explicit_wikipedia_provider_override(self) -> None:
        provider = _FakeWikipediaProvider()

        services = build_internet_services(wikipedia_provider=provider)

        self.assertIs(services.wikipedia_provider, provider)
        self.assertIs(services.internet_service.wikipedia_provider, provider)


class RuntimeMemoryIntegrationTests(unittest.TestCase):
    """Verify the new memory integration service coordinates storage cleanly."""

    def test_memory_integration_tracks_scope_and_history_counts(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        memory_services = build_memory_services(database_path=Path(temp_dir) / "memory.sqlite3")
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
        )

        memory_integration.remember("favorite_drink", "tea", scope="both", metadata={"source": "user"})
        memory_integration.store_conversation_turn(
            session_id="session-1",
            conversation_id="conv-1",
            role="user",
            content="remember tea",
        )
        snapshot = memory_integration.snapshot_counts()

        self.assertEqual(snapshot.short_term_entries, 1)
        self.assertEqual(snapshot.long_term_entries, 1)
        self.assertEqual(snapshot.conversation_history_entries, 1)
        self.assertGreaterEqual(snapshot.total_entries, 3)

    def test_memory_context_summary_excludes_conversation_history_and_scopes_session_memory(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        memory_services = build_memory_services(database_path=Path(temp_dir) / "memory.sqlite3")
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
        )

        memory_integration.store_conversation_turn(
            session_id="session-a",
            conversation_id="conv-a",
            role="user",
            content="research this topic in detail on the web",
        )
        memory_integration.store_conversation_turn(
            session_id="session-b",
            conversation_id="conv-b",
            role="user",
            content="latest news about technology from India Today",
        )
        memory_services.session_memory.store("session-a", "draft", "research agenda for session a")
        memory_services.session_memory.store("session-b", "draft", "research agenda for session b")
        memory_integration.remember("research_style", "research style is detailed", scope="long_term", metadata={"source": "user"})

        summary_a = memory_integration.build_context_summary(
            query="research",
            session_id="session-a",
            conversation_id="conv-a",
            limit=10,
        )
        summary_b = memory_integration.build_context_summary(
            query="research",
            session_id="session-b",
            conversation_id="conv-b",
            limit=10,
        )

        self.assertIsNotNone(summary_a)
        self.assertIsNotNone(summary_b)
        assert summary_a is not None
        assert summary_b is not None
        self.assertNotIn("conversation_history", summary_a)
        self.assertNotIn("conversation_history", summary_b)
        self.assertIn("session session:session-a:draft", summary_a)
        self.assertNotIn("session session:session-b:draft", summary_a)
        self.assertIn("session session:session-b:draft", summary_b)
        self.assertNotIn("session session:session-a:draft", summary_b)
        self.assertIn("long_term:research_style", summary_a)
        self.assertIn("long_term:research_style", summary_b)

    def test_memory_context_summary_keeps_long_term_memory_visible_when_history_matches_dominate(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        memory_services = build_memory_services(database_path=Path(temp_dir) / "memory.sqlite3")
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
        )

        for index in range(8):
            memory_integration.store_conversation_turn(
                session_id=f"session-{index}",
                conversation_id=f"conv-{index}",
                role="user",
                content="research this topic in detail on the web",
            )
        memory_integration.remember(
            "research_style",
            "research style is detailed",
            scope="long_term",
            metadata={"source": "user", "pinned": True},
        )

        summary = memory_integration.build_context_summary(
            query="research this topic in detail on the web",
            session_id="fresh-session",
            conversation_id="fresh-conv",
            limit=1,
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertIn("long_term:research_style", summary)
        self.assertNotIn("conversation_history", summary)

    def test_memory_context_summary_excludes_prior_conversation_history_within_same_session(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        memory_services = build_memory_services(database_path=Path(temp_dir) / "memory.sqlite3")
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
        )

        memory_integration.store_conversation_turn(
            session_id="session-shared",
            conversation_id="conv-a",
            role="user",
            content="research this topic in detail on the web",
        )
        memory_integration.store_conversation_turn(
            session_id="session-shared",
            conversation_id="conv-b",
            role="user",
            content="what should I research next",
        )
        memory_services.session_memory.store("session-shared", "draft", "research agenda for the shared session")
        memory_integration.remember("research_style", "research style is detailed", scope="long_term", metadata={"source": "user"})

        summary = memory_integration.build_context_summary(
            query="research",
            session_id="session-shared",
            conversation_id="conv-b",
            limit=10,
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertNotIn("conversation_history", summary)
        self.assertNotIn("research this topic in detail on the web", summary)
        self.assertIn("session session:session-shared:draft", summary)
        self.assertIn("long_term:research_style", summary)

    def test_memory_context_summary_preserves_short_term_memory_visibility(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        memory_services = build_memory_services(database_path=Path(temp_dir) / "memory.sqlite3")
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
        )

        memory_integration.remember(
            "research_hint",
            "research hint is compare multiple sources",
            scope="short_term",
            metadata={"source": "user"},
        )

        summary = memory_integration.build_context_summary(
            query="research",
            session_id="fresh-session",
            conversation_id="fresh-conv",
            limit=10,
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertIn("short_term:research_hint", summary)
        self.assertNotIn("conversation_history", summary)


class RuntimeApplicationIntegrationTests(unittest.TestCase):
    """Verify the application exposes the new stable runtime services."""

    def _build_test_application(self) -> NARVISApplication:
        temp_dir = Path(_workspace_temp_dir())
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        data_dir = temp_dir / "data"
        log_dir = temp_dir / "logs"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        return NARVISApplication(config=narvis.NARVISConfig(data_dir=data_dir, log_dir=log_dir))

    def test_narvis_application_registers_new_runtime_services(self) -> None:
        application = self._build_test_application()
        try:
            application.start()
            health = application.health()
            dashboard = application.container.resolve("dashboard")
            skill_registry = application.container.resolve("skill_registry")
            desktop_command_skill = skill_registry.resolve("desktop.command")
            plugin_registry = application.container.resolve("plugin_registry")
            memory_service = application.container.resolve("memory_service")
            internet_service = application.container.resolve("internet_service")
            automation_service = application.container.resolve("automation_service")
            desktop_control = application.container.resolve("desktop_control")
            desktop_command_pipeline = application.container.resolve("desktop_command_pipeline")
            application_resolver = application.container.resolve("application_resolver")
            universal_open_resolver = application.container.resolve("universal_open_resolver")
            universal_open_launcher = application.container.resolve("universal_open_launcher")
            runtime_optimizer = application.container.resolve("runtime_optimizer")
            mutation_surface_registry = application.container.resolve("mutation_surface_registry")
            mutation_guard_service = application.container.resolve("mutation_guard_service")
            mutation_approval_service = application.container.resolve("mutation_approval_service")
            mutation_run_service = application.container.resolve("mutation_run_service")
        finally:
            application.shutdown()

        self.assertGreaterEqual(skill_registry.count(), 5)
        self.assertEqual(desktop_command_skill.name, "desktop.command")
        self.assertGreaterEqual(plugin_registry.loaded_count(), 4)
        self.assertIsNotNone(dashboard)
        self.assertIsNotNone(memory_service)
        self.assertIsNotNone(internet_service)
        self.assertIsNotNone(automation_service)
        self.assertIsNotNone(desktop_control)
        self.assertIsNotNone(desktop_command_pipeline)
        self.assertIsNotNone(application_resolver)
        self.assertIsNotNone(universal_open_resolver)
        self.assertIsNotNone(universal_open_launcher)
        self.assertIsNotNone(runtime_optimizer)
        self.assertIsNotNone(mutation_surface_registry)
        self.assertIsNotNone(mutation_guard_service)
        self.assertIsNotNone(mutation_approval_service)
        self.assertIsNotNone(mutation_run_service)
        self.assertEqual(internet_service.capabilities()["news_provider"], "GoogleNewsRssProvider")
        self.assertEqual(internet_service.capabilities()["weather_provider"], "OpenMeteoWeatherProvider")
        self.assertEqual(internet_service.capabilities()["wikipedia_provider"], "MediaWikiWikipediaProvider")
        self.assertIsInstance(application.container.resolve("news_provider"), GoogleNewsRssProvider)
        self.assertIsInstance(application.container.resolve("weather_provider"), OpenMeteoWeatherProvider)
        self.assertIsInstance(application.container.resolve("wikipedia_provider"), MediaWikiWikipediaProvider)
        self.assertIn("skills", health)
        self.assertIn("plugins", health)

    def test_process_text_async_launches_cmd_exactly_once(self) -> None:
        application = self._build_test_application()
        try:
            application.start()
            application_manager = application.container.resolve("application_manager")
            with mock.patch.object(application_manager, "open_app_by_name", return_value=True) as open_app:
                response = asyncio.run(application.process_text_async("Open CMD"))
        finally:
            application.shutdown()

        self.assertEqual(open_app.call_count, 1)
        open_app.assert_called_once_with("CMD")
        self.assertEqual(response, "Opened application 'CMD'.")

    def test_process_text_preserves_same_conversation_context_across_calls(self) -> None:
        application = self._build_test_application()
        try:
            application.start()
            internet_service = application.container.resolve("internet_service")
            brain_engine = application.container.resolve("brain_engine")
            context_manager = brain_engine.context_manager
            research_calls: list[tuple[ResearchQuery | str, int]] = []
            news_calls: list[tuple[NewsQuery | str | None, int]] = []

            def fake_research(query: ResearchQuery | str, limit: int = 5) -> GroundedResearchResponse:
                research_calls.append((query, limit))
                if isinstance(query, ResearchQuery):
                    return _grounded_research_response(query.topic, search_text=query.search_text)
                return _grounded_research_response(str(query))

            def fake_fetch_news(topic: NewsQuery | str | None = None, limit: int = 5) -> list[NewsArticle]:
                news_calls.append((topic, limit))
                return [
                    NewsArticle(
                        title="Adobe launches new suite",
                        source="Example News",
                        published_at="2026-07-07T01:25:38Z",
                        url="https://example.com/adobe-suite",
                    )
                ]

            with mock.patch.object(internet_service, "research", side_effect=fake_research), mock.patch.object(
                internet_service,
                "fetch_news",
                side_effect=fake_fetch_news,
            ):
                first = application.process_text("Bitcoin kya hai")
                second = application.process_text("latest news about Adobe")
                third = application.process_text("iski latest information batao")
        finally:
            application.shutdown()

        self.assertIn("Bitcoin summary", first)
        self.assertIn("Adobe launches new suite", second)
        self.assertIn("Adobe launches new suite", third)
        self.assertEqual(len(news_calls), 2)
        self.assertEqual(len(research_calls), 1)
        follow_up_query, _limit = news_calls[1]
        self.assertIsInstance(follow_up_query, NewsQuery)
        assert isinstance(follow_up_query, NewsQuery)
        self.assertEqual(follow_up_query.topic, "Adobe")
        self.assertEqual(follow_up_query.query_text, "Adobe latest news")
        self.assertNotEqual(follow_up_query.topic, "Bitcoin")
        self.assertEqual(len(context_manager.chat_history_manager.list_conversation_ids()), 1)
        self.assertEqual(len(context_manager.session_manager.list_sessions()), 1)
        history = context_manager.get_history()
        self.assertEqual(len(history), 6)

    def test_process_text_resolves_contextual_explicit_research_follow_up_in_same_session(self) -> None:
        application = self._build_test_application()
        try:
            application.start()
            internet_service = application.container.resolve("internet_service")
            research_calls: list[tuple[ResearchQuery | str, int]] = []
            news_calls: list[tuple[NewsQuery | str | None, int]] = []

            def fake_research(query: ResearchQuery | str, limit: int = 5) -> GroundedResearchResponse:
                research_calls.append((query, limit))
                if isinstance(query, ResearchQuery):
                    return _grounded_research_response(query.topic, search_text=query.search_text)
                return _grounded_research_response(str(query))

            def fake_fetch_news(topic: NewsQuery | str | None = None, limit: int = 5) -> list[NewsArticle]:
                news_calls.append((topic, limit))
                return [
                    NewsArticle(
                        title="Technology headlines",
                        source="India Today",
                        published_at="2026-07-07T01:25:38Z",
                        url="https://example.com/technology-headlines",
                    )
                ]

            with mock.patch.object(internet_service, "research", side_effect=fake_research), mock.patch.object(
                internet_service,
                "fetch_news",
                side_effect=fake_fetch_news,
            ):
                first = application.process_text("latest news about technology from India Today")
                second = application.process_text("iski latest information batao")
                third = application.process_text("research this topic in detail on the web")
        finally:
            application.shutdown()

        self.assertIn("Technology headlines", first)
        self.assertIn("Technology headlines", second)
        self.assertIn("technology summary", third.lower())
        self.assertEqual(len(news_calls), 2)
        self.assertEqual(len(research_calls), 1)
        follow_up_query, _limit = research_calls[0]
        self.assertIsInstance(follow_up_query, ResearchQuery)
        assert isinstance(follow_up_query, ResearchQuery)
        self.assertEqual(follow_up_query.intent_kind, "explicit")
        self.assertEqual(follow_up_query.topic, "technology")
        self.assertEqual(follow_up_query.search_text, "technology India Today")
        self.assertNotIn("this topic", follow_up_query.search_text.lower())

    def test_fresh_session_fallback_excludes_prior_session_conversation_history(self) -> None:
        class _EchoProvider:
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
            ):
                content = (system_prompt or "") + "\n\n" + messages[-1]["content"]
                return ProviderResponse(
                    content=content,
                    provider_name="echo-provider",
                    model="echo",
                    usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0, latency_seconds=0.0),
                )

        temp_dir = Path(_workspace_temp_dir())
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        data_dir = temp_dir / "data"
        log_dir = temp_dir / "logs"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        config = narvis.NARVISConfig(data_dir=data_dir, log_dir=log_dir)

        first_application = NARVISApplication(config=config)
        try:
            first_application.start()
            first_brain = first_application.container.resolve("brain_engine")
            first_brain.provider = None
            first_brain.response_builder.provider = None
            first_internet_service = first_application.container.resolve("internet_service")
            with mock.patch.object(
                first_internet_service,
                "fetch_news",
                return_value=[
                    NewsArticle(
                        title="Technology headlines",
                        source="India Today",
                        published_at="2026-07-07T01:25:38Z",
                        url="https://example.com/technology-headlines",
                    )
                ],
            ):
                first_output = first_application.process_text("latest news about technology from India Today")
        finally:
            first_application.shutdown()

        second_application = NARVISApplication(config=config)
        try:
            second_application.start()
            second_brain = second_application.container.resolve("brain_engine")
            echo_provider = _EchoProvider()
            second_brain.provider = echo_provider
            second_brain.response_builder.provider = echo_provider
            second_internet_service = second_application.container.resolve("internet_service")
            with mock.patch.object(
                second_internet_service,
                "research",
                side_effect=AssertionError("internet research should not run for a fresh-session ambiguous request"),
            ), mock.patch.object(
                second_internet_service,
                "fetch_news",
                side_effect=AssertionError("news fetch should not run for a fresh-session ambiguous request"),
            ):
                second_output = second_application.process_text("research this topic in detail on the web")
        finally:
            second_application.shutdown()

        self.assertIn("Technology headlines", first_output)
        self.assertIn("Detected intent: unknown.", second_output)
        self.assertIn("Current user message:", second_output)
        self.assertNotIn("latest news about technology from India Today", second_output)
        self.assertNotIn("Technology headlines", second_output)
        self.assertNotIn("conversation_history", second_output)
        self.assertNotIn("history:session-", second_output)

    def test_narvis_module_main_processes_console_commands_and_shuts_down(self) -> None:
        application = _FakeApplication()

        with mock.patch.object(narvis, "NARVISApplication", return_value=application), mock.patch(
            "builtins.input",
            side_effect=["", "status", "exit"],
        ), mock.patch("builtins.print") as print_mock:
            exit_code = asyncio.run(narvis.main())

        self.assertEqual(exit_code, 0)
        self.assertTrue(application.started)
        self.assertEqual(application.processed_commands, ["status"])
        self.assertTrue(application.shutdown_called)
        print_mock.assert_any_call("NARVIS Ready.")
        print_mock.assert_any_call("Type commands (type 'exit' to quit).")
        print_mock.assert_any_call("handled: status")

    def test_narvis_module_main_accepts_multiple_sequential_commands_once_each(self) -> None:
        application = _FakeApplication()
        console = _ScriptedConsole(["Open Photoshop", "Open CorelDRAW", "Open Calculator", "exit"])

        with mock.patch.object(narvis, "NARVISApplication", return_value=application):
            exit_code = asyncio.run(
                narvis.main(
                    input_reader=console.read_input,
                    output_writer=console.write_output,
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            application.processed_commands,
            ["Open Photoshop", "Open CorelDRAW", "Open Calculator"],
        )
        self.assertEqual(
            console.outputs,
            [
                "NARVIS Ready.",
                "Type commands (type 'exit' to quit).",
                "handled: Open Photoshop",
                "handled: Open CorelDRAW",
                "handled: Open Calculator",
            ],
        )
        self.assertEqual(console.prompts, ["> ", "> ", "> ", "> "])
        self.assertTrue(application.shutdown_called)

    def test_narvis_module_main_keeps_session_alive_until_explicit_exit(self) -> None:
        application = _FakeApplication()
        console = _ScriptedConsole(["Open Photoshop", "exit"])

        with mock.patch.object(narvis, "NARVISApplication", return_value=application):
            exit_code = asyncio.run(
                narvis.main(
                    input_reader=console.read_input,
                    output_writer=console.write_output,
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(application.processed_commands, ["Open Photoshop"])
        self.assertEqual(console.prompts, ["> ", "> "])
        self.assertTrue(application.shutdown_called)


class _FakeLogger:
    """Logger stub used by the module entry point test."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, level, message: str, **context) -> None:
        self.messages.append(message)


class _FakeApplication:
    """Application stub used to validate the narvis module entry point."""

    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False
        self.logger = _FakeLogger()
        self.processed_commands: list[str] = []

    async def async_start(self) -> None:
        self.started = True

    async def process_text_async(self, text: str) -> str:
        self.processed_commands.append(text)
        return f"handled: {text}"

    async def async_shutdown(self) -> None:
        self.shutdown_called = True


class _ScriptedConsole:
    """Console stub that records prompts and emitted output."""

    def __init__(self, inputs: list[str]) -> None:
        self._inputs = list(inputs)
        self.prompts: list[str] = []
        self.outputs: list[str] = []

    def read_input(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def write_output(self, message: str) -> None:
        self.outputs.append(message)


if __name__ == "__main__":
    unittest.main()
