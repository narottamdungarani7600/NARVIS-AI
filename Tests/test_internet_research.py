"""Tests for grounded web research added in NARVIS Internet Phase 1."""

from __future__ import annotations

import unittest
from email.message import Message

from AI.brain import BrainEngine
from Internet import (
    BingSearchProvider,
    DeterministicResearchSynthesizer,
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
    FetchedPage,
    GroundedResearchResponse,
    HtmlContentExtractor,
    InternetResearchIntentParser,
    InternetResearchService,
    NewsQuery,
    ProviderBackedResearchSynthesizer,
    ResearchQuery,
    SafePageFetcher,
    SearchExecutionResult,
    SearchProviderConnectionError,
    SearchProviderDiagnostic,
    SearchProviderParseError,
    SearchProviderTimeoutError,
    SearchProviderUnavailableError,
    SearchResult,
    UnsafeUrlError,
    execute_search,
    normalize_public_url,
)
from Skills import DesktopSkill, InternetSkill, build_desktop_command_services, build_skill_services


class _StaticSearchProvider:
    """Deterministic search-provider stub used by research-service tests."""

    def __init__(self, results: list[SearchResult], *, available: bool = True, error: Exception | None = None) -> None:
        self.results = list(results)
        self.available = available
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def is_available(self) -> bool:
        return self.available

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return list(self.results[:limit])


class _OutcomeSearchProvider:
    """Search-provider stub that returns a prebuilt diagnostic outcome."""

    def __init__(self, outcome_factory, *, provider_name: str, available: bool = True) -> None:  # noqa: ANN001 - test helper
        self.outcome_factory = outcome_factory
        self.provider_name = provider_name
        self.available = available
        self.calls: list[tuple[str, int]] = []

    def is_available(self) -> bool:
        return self.available

    def search_diagnostics(self, query: str, limit: int = 10) -> SearchExecutionResult:
        self.calls.append((query, limit))
        return self.outcome_factory(query, limit)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:  # pragma: no cover - guardrail
        raise AssertionError("search() should not be used when search_diagnostics() is available")


def _success_outcome(provider_name: str, results: list[SearchResult]):  # noqa: ANN202 - test helper
    def _factory(query: str, limit: int) -> SearchExecutionResult:
        bounded = tuple(results[:limit])
        status = "results" if bounded else "zero_results"
        return SearchExecutionResult(
            query=query,
            status=status,
            results=bounded,
            attempts=(
                SearchProviderDiagnostic(
                    provider_name=provider_name,
                    status=status,
                    result_count=len(bounded),
                ),
            ),
            provider_name=provider_name,
        )

    return _factory


def _failure_outcome(provider_name: str, status: str, *, error_message: str | None = None, http_status: int | None = None):  # noqa: ANN202 - test helper
    def _factory(query: str, limit: int) -> SearchExecutionResult:
        return SearchExecutionResult(
            query=query,
            status=status,
            attempts=(
                SearchProviderDiagnostic(
                    provider_name=provider_name,
                    status=status,
                    result_count=0,
                    error_message=error_message or status,
                    http_status=http_status,
                ),
            ),
            error_message=error_message or status,
        )

    return _factory


class _StaticPageFetcher:
    """Deterministic page-fetcher stub used by research-service tests."""

    def __init__(self, pages: list[FetchedPage]) -> None:
        self.pages = list(pages)
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        if self.pages:
            return self.pages.pop(0)
        return FetchedPage(url=url, final_url=url, success=False, error="no stub page configured")


class _FakeResponse:
    """Small response object compatible with the safe page fetcher."""

    def __init__(self, *, url: str, body: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200, headers=None) -> None:
        self._url = url
        self._body = body
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        for key, value in dict(headers or {}).items():
            self.headers[key] = value

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _StaticOpener:
    """Return one preconstructed response from a fake opener."""

    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    def open(self, req, timeout=None):  # noqa: ANN001 - urllib-compatible signature
        return self.response


class _UnsafeRedirectOpener:
    """Trigger one unsafe redirect before a response can be read."""

    def __init__(self, redirect_handler) -> None:  # noqa: ANN001 - test helper
        self.redirect_handler = redirect_handler

    def open(self, req, timeout=None):  # noqa: ANN001 - urllib-compatible signature
        self.redirect_handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/blocked")
        return _FakeResponse(url=req.full_url, body=b"")


class _InternetServiceStub:
    """Minimal internet-service stub for skill and Brain integration tests."""

    def __init__(
        self,
        response: GroundedResearchResponse,
        *,
        news_results: list[object] | None = None,
        wikipedia_results: list[object] | None = None,
    ) -> None:
        self.response = response
        self.calls: list[tuple[ResearchQuery | str, int]] = []
        self.news_calls: list[tuple[NewsQuery | str | None, int]] = []
        self.news_results = list(news_results or [])
        self.weather_calls: list[str] = []
        self.wikipedia_calls: list[tuple[str, int]] = []
        self.wikipedia_results = list(wikipedia_results or [])

    def research(self, query: ResearchQuery | str, limit: int = 5) -> GroundedResearchResponse:
        self.calls.append((query, limit))
        if isinstance(query, ResearchQuery):
            self.response.query = query
        return self.response

    def fetch_weather(self, location: str):
        self.weather_calls.append(location)
        return type("Weather", (), {"location": location, "condition": "clear", "temperature_c": 24.0})()

    def fetch_news(self, topic: NewsQuery | str | None = None, limit: int = 5):
        self.news_calls.append((topic, limit))
        return list(self.news_results)

    def search_wikipedia(self, query: str, limit: int = 3):
        self.wikipedia_calls.append((query, limit))
        return list(self.wikipedia_results)

    def search_youtube(self, query: str, limit: int = 3):
        return []


class _DesktopControl:
    """Minimal desktop-control stub used to protect Universal Open behavior."""

    def __init__(self) -> None:
        self.opened_applications: list[str] = []

    def open_application(self, app_name: str):
        self.opened_applications.append(app_name)
        return type("Result", (), {"message": f"Opened {app_name}.", "data": {"application": app_name}})()

    def capture_screenshot(self):
        return type("Result", (), {"message": "Screenshot saved.", "data": {"path": "shot.png"}})()

    def read_clipboard(self):
        return type("Result", (), {"message": "Clipboard read.", "data": {"text": "memo"}})()

    def write_clipboard(self, text: str):
        return type("Result", (), {"message": "Clipboard written.", "data": {"text": text}})()

    def type_text(self, text: str):
        return type("Result", (), {"message": "Typed text.", "data": {"text": text}})()

    def press_key(self, key: str):
        return type("Result", (), {"message": f"Pressed {key}.", "data": {"key": key}})()

    def close_application(self, app_name: str):
        return type("Result", (), {"message": f"Closed {app_name}.", "data": {"application": app_name}})()

    def list_windows(self):
        return type("Result", (), {"message": "No windows.", "data": {"windows": []}})()

    def focus_window(self, title: str):
        return type("Result", (), {"message": f"Focused {title}.", "data": {"title": title}})()


def _research_response(topic: str, *, search_text: str | None = None, answer: str | None = None) -> GroundedResearchResponse:
    """Build one deterministic grounded response for Brain/skill routing tests."""

    resolved_search_text = search_text or topic
    return GroundedResearchResponse(
        query=ResearchQuery(topic, topic, resolved_search_text),
        answer=answer or f"{topic} summary",
        sources=(type("Source", (), {"title": f"{topic} source", "url": f"https://example.com/{topic.lower().replace(' ', '-')}", "domain": "example.com"})(),),
        provider_name="deterministic-fallback",
        search_result_count=1,
        pages_read_count=1,
    )


class InternetResearchIntentTests(unittest.TestCase):
    """Verify internet-research intent detection and query extraction."""

    def setUp(self) -> None:
        self.parser = InternetResearchIntentParser()

    def test_parse_english_internet_search_command(self) -> None:
        query = self.parser.parse("Search the internet for Kingfisher and tell me what it is")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Kingfisher")
        self.assertEqual(query.search_text, "Kingfisher")

    def test_parse_hinglish_internet_search_command(self) -> None:
        query = self.parser.parse("Internet me search karo Kingfisher naam se kya kya hai aur mujhe batao")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Kingfisher")
        self.assertEqual(query.search_text, "Kingfisher")

    def test_parse_latest_news_request_preserves_freshness(self) -> None:
        query = self.parser.parse("Latest news about Adobe")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Adobe")
        self.assertIn("latest", query.freshness_terms)
        self.assertIn("news", query.freshness_terms)
        self.assertEqual(query.search_text, "Adobe latest news")

    def test_parse_current_information_request_preserves_freshness(self) -> None:
        query = self.parser.parse("Current information about Microsoft")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Microsoft")
        self.assertIn("current", query.freshness_terms)
        self.assertEqual(query.search_text, "Microsoft current information")

    def test_parse_cleanup_handles_kya_hai_queries(self) -> None:
        query = self.parser.parse("Internet se pata karo Bitcoin kya hai")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Bitcoin")

    def test_parse_topic_first_explicit_internet_request(self) -> None:
        query = self.parser.parse("Artificial intelligence kya hai internet se batao")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Artificial intelligence")
        self.assertEqual(query.intent_kind, "explicit")

    def test_parse_natural_hinglish_topic_request(self) -> None:
        query = self.parser.parse("Kingfisher ke bare me batao")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Kingfisher")
        self.assertEqual(query.search_text, "Kingfisher")
        self.assertEqual(query.intent_kind, "natural_research")

    def test_parse_natural_freshness_request(self) -> None:
        query = self.parser.parse("Aaj Adobe ki latest news")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "Adobe")
        self.assertEqual(query.search_text, "Adobe latest news")
        self.assertIn("today", query.freshness_terms)
        self.assertIn("latest", query.freshness_terms)
        self.assertIn("news", query.freshness_terms)

    def test_parse_short_semantic_query(self) -> None:
        query = self.parser.parse("World Best Game Popular")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "World Best Game Popular")
        self.assertEqual(query.intent_kind, "natural_research")

    def test_local_system_identity_terms_stay_outside_internet(self) -> None:
        self.assertIsNone(self.parser.parse("Status kya hai"))
        self.assertIsNone(self.parser.parse("Health kya hai"))
        self.assertIsNone(self.parser.parse("Runtime kya hai"))

    def test_valid_identity_queries_still_route_to_internet(self) -> None:
        kingfisher = self.parser.parse("Kingfisher kya hai")
        bitcoin = self.parser.parse("Bitcoin kya hai")
        microsoft = self.parser.parse("Microsoft ka current CEO kaun hai")

        self.assertIsNotNone(kingfisher)
        self.assertIsNotNone(bitcoin)
        self.assertIsNotNone(microsoft)
        assert kingfisher is not None
        assert bitcoin is not None
        assert microsoft is not None
        self.assertEqual(kingfisher.topic, "Kingfisher")
        self.assertEqual(bitcoin.topic, "Bitcoin")
        self.assertIn("Microsoft", microsoft.search_text)
        self.assertIn("current", microsoft.search_text.lower())
        self.assertIn("ceo", microsoft.search_text.lower())

    def test_parse_desktop_commands_are_not_stolen(self) -> None:
        self.assertIsNone(self.parser.parse("Take screenshot"))
        self.assertIsNone(self.parser.parse("Type hello"))
        self.assertIsNone(self.parser.parse("Press enter"))

    def test_parse_research_on_the_web_command(self) -> None:
        query = self.parser.parse("Research electric vehicles on the web and summarize it")

        self.assertIsNotNone(query)
        assert query is not None
        self.assertEqual(query.topic, "electric vehicles")

    def test_open_app_commands_are_not_stolen(self) -> None:
        self.assertIsNone(self.parser.parse("Open Instagram"))
        self.assertIsNone(self.parser.parse("Open YouTube"))
        self.assertIsNone(self.parser.parse("Open Chrome"))

    def test_personal_memory_and_conversation_requests_stay_outside_internet(self) -> None:
        self.assertIsNone(self.parser.parse("What is my name?"))
        self.assertIsNone(self.parser.parse("What did I tell you before?"))
        self.assertIsNone(self.parser.parse("Remember that my favorite color is blue"))
        self.assertIsNone(self.parser.parse("Hello"))
        self.assertIsNone(self.parser.parse("Help"))
        self.assertIsNone(self.parser.parse("Exit"))
        self.assertIsNone(self.parser.parse("Thank you"))

    def test_ambiguous_unknown_text_stays_outside_internet(self) -> None:
        self.assertIsNone(self.parser.parse("Do the thing"))


class InternetSearchProviderTests(unittest.TestCase):
    """Verify structured result normalization for the search provider layer."""

    def test_search_provider_normalizes_results_and_deduplicates_urls(self) -> None:
        html = """
        <html><body>
        <div class="result">
          <a class="result__a" href="https://example.com/alpha">Alpha Result</a>
          <div class="result__snippet">Alpha snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha">Duplicate Alpha</a>
          <div class="result__snippet">Duplicate snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="javascript:alert(1)">Bad Result</a>
          <div class="result__snippet">Ignore me</div>
        </div>
        <div class="result">
          <a class="result__a" href="https://example.org/beta">Beta Result</a>
          <div class="result__snippet">Beta snippet</div>
        </div>
        </body></html>
        """
        provider = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: html)

        results = provider.search("kingfisher", limit=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "Alpha Result")
        self.assertEqual(results[0].url, "https://example.com/alpha")
        self.assertEqual(results[0].source, "example.com")
        self.assertEqual(results[0].rank, 1)
        self.assertEqual(results[1].url, "https://example.org/beta")
        self.assertEqual(results[1].rank, 2)

    def test_search_provider_timeout_is_reported(self) -> None:
        provider = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: (_ for _ in ()).throw(TimeoutError("slow")))

        with self.assertRaises(SearchProviderTimeoutError):
            provider.search("kingfisher")

    def test_search_provider_unavailable_error_is_reported(self) -> None:
        provider = DuckDuckGoSearchProvider(
            html_fetcher=lambda query, endpoint, timeout: (_ for _ in ()).throw(SearchProviderUnavailableError("offline"))
        )

        with self.assertRaises(SearchProviderUnavailableError):
            provider.search("kingfisher")

    def test_search_provider_handles_empty_results(self) -> None:
        provider = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: "<html><body>No results found</body></html>")

        self.assertEqual(provider.search("kingfisher"), [])

    def test_search_provider_marks_challenge_pages_as_blocked_not_empty(self) -> None:
        provider = DuckDuckGoSearchProvider(
            html_fetcher=lambda query, endpoint, timeout: "<html><body>Please verify you are human before continuing.</body></html>"
        )

        outcome = execute_search(provider, "kingfisher")

        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(len(outcome.results), 0)

    def test_search_provider_marks_unrecognized_zero_parse_as_failure(self) -> None:
        provider = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: "<html><body><div>Unexpected response body</div></body></html>")

        outcome = execute_search(provider, "kingfisher")

        self.assertEqual(outcome.status, "parse_failure")

    def test_bing_provider_normalizes_results(self) -> None:
        html = """
        <html><body>
        <li class="b_algo">
          <h2><a href="https://example.com/alpha">Alpha Result</a></h2>
          <div class="b_caption"><p>Alpha snippet</p></div>
        </li>
        <li class="b_algo">
          <h2><a href="https://example.org/beta">Beta Result</a></h2>
          <div class="b_caption"><p>Beta snippet</p></div>
        </li>
        </body></html>
        """
        provider = BingSearchProvider(html_fetcher=lambda query, endpoint, timeout: html)

        results = provider.search("kingfisher", limit=5)

        self.assertEqual([result.title for result in results], ["Alpha Result", "Beta Result"])
        self.assertEqual(results[0].url, "https://example.com/alpha")


class InternetSearchFallbackTests(unittest.TestCase):
    """Verify fallback behavior across multiple live-search providers."""

    def test_primary_provider_succeeds_without_fallback_when_limit_is_met(self) -> None:
        primary = _OutcomeSearchProvider(
            _success_outcome("primary", [SearchResult(title="Alpha", url="https://example.com/alpha", snippet="Alpha")]),
            provider_name="primary",
        )
        fallback = _OutcomeSearchProvider(
            _success_outcome("fallback", [SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta")]),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "kingfisher", limit=1)

        self.assertEqual(outcome.status, "results")
        self.assertEqual([result.url for result in outcome.results], ["https://example.com/alpha"])
        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(fallback.calls, [])

    def test_primary_provider_failure_uses_fallback_results(self) -> None:
        primary = _OutcomeSearchProvider(_failure_outcome("primary", "connection_failure"), provider_name="primary")
        fallback = _OutcomeSearchProvider(
            _success_outcome("fallback", [SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta")]),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "kingfisher", limit=3)

        self.assertEqual(outcome.status, "results")
        self.assertEqual([attempt.status for attempt in outcome.attempts], ["connection_failure", "results"])
        self.assertEqual(outcome.results[0].url, "https://example.org/beta")

    def test_challenge_response_falls_back_to_secondary_provider(self) -> None:
        primary = DuckDuckGoSearchProvider(
            html_fetcher=lambda query, endpoint, timeout: "<html><body>Please verify you are human before continuing.</body></html>"
        )
        fallback = _OutcomeSearchProvider(
            _success_outcome("fallback", [SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta")]),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "kingfisher", limit=3)

        self.assertEqual(outcome.status, "results")
        self.assertEqual([attempt.status for attempt in outcome.attempts], ["blocked", "results"])

    def test_parse_failure_falls_back_to_secondary_provider(self) -> None:
        primary = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: "<html><body><div>Unexpected body</div></body></html>")
        fallback = _OutcomeSearchProvider(
            _success_outcome("fallback", [SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta")]),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "kingfisher", limit=3)

        self.assertEqual(outcome.status, "results")
        self.assertEqual([attempt.status for attempt in outcome.attempts], ["parse_failure", "results"])

    def test_timeout_falls_back_to_secondary_provider(self) -> None:
        primary = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: (_ for _ in ()).throw(TimeoutError("slow")))
        fallback = _OutcomeSearchProvider(
            _success_outcome("fallback", [SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta")]),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "kingfisher", limit=3)

        self.assertEqual(outcome.status, "results")
        self.assertEqual([attempt.status for attempt in outcome.attempts], ["timeout", "results"])

    def test_genuine_zero_results_do_not_fall_through_to_secondary_provider(self) -> None:
        primary = DuckDuckGoSearchProvider(html_fetcher=lambda query, endpoint, timeout: "<html><body>No results found</body></html>")
        fallback = _OutcomeSearchProvider(
            _success_outcome("fallback", [SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta")]),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "missing entity", limit=3)

        self.assertEqual(outcome.status, "zero_results")
        self.assertEqual(fallback.calls, [])

    def test_results_are_deduplicated_across_providers_when_filling_limit(self) -> None:
        primary = _OutcomeSearchProvider(
            _success_outcome("primary", [SearchResult(title="Alpha", url="https://example.com/alpha", snippet="Alpha")]),
            provider_name="primary",
        )
        fallback = _OutcomeSearchProvider(
            _success_outcome(
                "fallback",
                [
                    SearchResult(title="Alpha duplicate", url="https://example.com/alpha", snippet="Duplicate"),
                    SearchResult(title="Beta", url="https://example.org/beta", snippet="Beta"),
                ],
            ),
            provider_name="fallback",
        )
        provider = FallbackSearchProvider((primary, fallback))

        outcome = execute_search(provider, "kingfisher", limit=3)

        self.assertEqual(outcome.status, "results")
        self.assertEqual([result.url for result in outcome.results], ["https://example.com/alpha", "https://example.org/beta"])
        self.assertEqual([result.rank for result in outcome.results], [1, 2])


class InternetSafetyAndFetchingTests(unittest.TestCase):
    """Verify URL safety checks and bounded page fetching."""

    def test_invalid_url_scheme_is_rejected(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            normalize_public_url("javascript:alert(1)")

    def test_localhost_is_rejected(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            normalize_public_url("http://localhost:8000/test", resolve_host=True)

    def test_private_ip_is_rejected(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            normalize_public_url("http://192.168.1.10/test", resolve_host=True)

    def test_unsafe_redirect_target_is_rejected(self) -> None:
        fetcher = SafePageFetcher(opener_factory=lambda redirect_handler: _UnsafeRedirectOpener(redirect_handler))

        result = fetcher.fetch("https://example.com/start")

        self.assertFalse(result.success)
        self.assertIn("blocked", result.error or "")

    def test_oversized_response_is_handled_safely(self) -> None:
        response = _FakeResponse(
            url="https://example.com/large",
            body=b"<html><body>too big</body></html>",
            headers={"Content-Length": "999999"},
        )
        fetcher = SafePageFetcher(max_response_bytes=100, opener_factory=lambda redirect_handler: _StaticOpener(response))

        result = fetcher.fetch("https://example.com/large")

        self.assertFalse(result.success)
        self.assertIn("size limit", result.error or "")

    def test_unsupported_content_type_is_rejected(self) -> None:
        response = _FakeResponse(url="https://example.com/file", body=b"pdf", content_type="application/pdf")
        fetcher = SafePageFetcher(opener_factory=lambda redirect_handler: _StaticOpener(response))

        result = fetcher.fetch("https://example.com/file")

        self.assertFalse(result.success)
        self.assertIn("unsupported content type", result.error or "")

    def test_valid_html_text_extraction_removes_scripts_and_styles(self) -> None:
        html = b"""
        <html>
          <head>
            <title>Example Title</title>
            <style>.hidden { display:none; }</style>
            <script>window.alert('ignore me')</script>
          </head>
          <body>
            <nav>Navigation should disappear</nav>
            <main>
              <p>Example text for grounded extraction.</p>
            </main>
          </body>
        </html>
        """
        response = _FakeResponse(url="https://example.com/page", body=html)
        fetcher = SafePageFetcher(opener_factory=lambda redirect_handler: _StaticOpener(response))

        result = fetcher.fetch("https://example.com/page")

        self.assertTrue(result.success)
        self.assertEqual(result.title, "Example Title")
        self.assertIn("Example text for grounded extraction", result.text)
        self.assertNotIn("Navigation should disappear", result.text)
        self.assertNotIn("ignore me", result.text)

    def test_html_content_extractor_handles_plain_text(self) -> None:
        extractor = HtmlContentExtractor(max_chars=100)

        content = extractor.extract("This is a plain text response.", content_type="text/plain")

        self.assertEqual(content.text, "This is a plain text response.")
        self.assertEqual(content.excerpt, "This is a plain text response.")


class InternetSynthesisTests(unittest.TestCase):
    """Verify grounded answer synthesis and service orchestration."""

    def setUp(self) -> None:
        self.synthesizer = DeterministicResearchSynthesizer()

    def test_multiple_meanings_can_be_represented(self) -> None:
        query = ResearchQuery("Kingfisher", "Kingfisher", "Kingfisher")
        results = [
            SearchResult(title="Kingfisher birds", url="https://example.com/bird", snippet="Kingfisher is a family of colorful birds."),
            SearchResult(title="Kingfisher plc", url="https://example.com/plc", snippet="Kingfisher plc is an international home improvement company."),
            SearchResult(title="Kingfisher Airlines", url="https://example.com/airline", snippet="Kingfisher Airlines was an Indian airline."),
        ]

        response = self.synthesizer.synthesize(query, results, [])

        self.assertTrue(response.ambiguous)
        self.assertIn("ambiguous", response.answer.lower())
        self.assertIn("Which meaning do you want to explore further?", response.follow_up_question or "")
        self.assertEqual(len(response.sources), 3)

    def test_answer_uses_supplied_evidence(self) -> None:
        query = ResearchQuery("Microsoft", "Microsoft", "Microsoft")
        results = [
            SearchResult(
                title="Microsoft overview",
                url="https://example.com/microsoft",
                snippet="Microsoft is a technology company that develops software and cloud services.",
            )
        ]

        response = self.synthesizer.synthesize(query, results, [])

        self.assertIn("technology company", response.answer.lower())
        self.assertEqual(response.provider_name, "deterministic-fallback")

    def test_source_list_is_real_and_deduplicated(self) -> None:
        query = ResearchQuery("Adobe", "Adobe", "Adobe")
        results = [
            SearchResult(title="Adobe news", url="https://example.com/adobe", snippet="Adobe is a software company."),
            SearchResult(title="Adobe duplicate", url="https://example.com/adobe", snippet="Duplicate URL should collapse."),
        ]

        response = self.synthesizer.synthesize(query, results, [])

        self.assertEqual(len(response.sources), 1)
        self.assertEqual(response.sources[0].url, "https://example.com/adobe")

    def test_no_results_response_is_useful(self) -> None:
        service = InternetResearchService(
            search_provider=_StaticSearchProvider([]),
            page_fetcher=_StaticPageFetcher([]),
            synthesizer=self.synthesizer,
        )

        response = service.research(ResearchQuery("Adobe", "Adobe", "Adobe"))

        self.assertEqual(response.search_result_count, 0)
        self.assertIn("couldn't find public web results", response.answer.lower())

    def test_partial_results_response_survives_failed_page_reads(self) -> None:
        service = InternetResearchService(
            search_provider=_StaticSearchProvider(
                [
                    SearchResult(title="Adobe article", url="https://example.com/adobe", snippet="Adobe is a software company."),
                    SearchResult(title="Adobe report", url="https://example.org/adobe", snippet="Adobe offers creative tools."),
                ]
            ),
            page_fetcher=_StaticPageFetcher(
                [
                    FetchedPage(url="https://example.com/adobe", final_url="https://example.com/adobe", success=False, error="timeout"),
                    FetchedPage(
                        url="https://example.org/adobe",
                        final_url="https://example.org/adobe",
                        success=True,
                        title="Adobe report",
                        text="Adobe offers creative tools and cloud services.",
                        excerpt="Adobe offers creative tools and cloud services.",
                    ),
                ]
            ),
            synthesizer=self.synthesizer,
        )

        response = service.research(ResearchQuery("Adobe", "Adobe", "Adobe"))

        self.assertEqual(response.search_result_count, 2)
        self.assertEqual(response.pages_read_count, 1)
        self.assertIn("relies on search-result snippets", response.answer)

    def test_provider_unavailable_behavior_returns_useful_error(self) -> None:
        service = InternetResearchService(
            search_provider=_StaticSearchProvider([], error=SearchProviderUnavailableError("offline")),
            page_fetcher=_StaticPageFetcher([]),
            synthesizer=self.synthesizer,
        )

        response = service.research(ResearchQuery("Adobe", "Adobe", "Adobe"))

        self.assertIn("couldn't complete a live web search", response.answer.lower())
        self.assertEqual(response.search_status, "all_failed")
        self.assertIn("provider_unavailable", response.error or "")

    def test_all_providers_fail_returns_live_search_unavailable_message(self) -> None:
        provider = FallbackSearchProvider(
            (
                _OutcomeSearchProvider(_failure_outcome("primary", "timeout"), provider_name="primary"),
                _OutcomeSearchProvider(_failure_outcome("fallback", "connection_failure"), provider_name="fallback"),
            )
        )
        service = InternetResearchService(
            search_provider=provider,
            page_fetcher=_StaticPageFetcher([]),
            synthesizer=self.synthesizer,
        )

        response = service.research(ResearchQuery("Kingfisher", "Kingfisher", "Kingfisher"))

        self.assertEqual(response.search_status, "all_failed")
        self.assertEqual(response.search_result_count, 0)
        self.assertIn("couldn't complete a live web search", response.answer.lower())
        self.assertNotIn("couldn't find public web results", response.answer.lower())

    def test_provider_failure_is_not_reported_as_genuine_zero_results(self) -> None:
        service = InternetResearchService(
            search_provider=DuckDuckGoSearchProvider(
                html_fetcher=lambda query, endpoint, timeout: "<html><body>Please verify you are human before continuing.</body></html>"
            ),
            page_fetcher=_StaticPageFetcher([]),
            synthesizer=self.synthesizer,
        )

        response = service.research(ResearchQuery("Kingfisher", "Kingfisher", "Kingfisher"))

        self.assertEqual(response.search_status, "all_failed")
        self.assertIn("couldn't complete a live web search", response.answer.lower())
        self.assertNotIn("couldn't find public web results", response.answer.lower())

    def test_deterministic_fallback_works_without_ai_provider(self) -> None:
        service = InternetResearchService(
            search_provider=_StaticSearchProvider(
                [SearchResult(title="Microsoft", url="https://example.com/microsoft", snippet="Microsoft is a technology company.")]
            ),
            page_fetcher=_StaticPageFetcher([]),
            synthesizer=ProviderBackedResearchSynthesizer(provider=None, fallback=self.synthesizer),
        )

        response = service.research(ResearchQuery("Microsoft", "Microsoft", "Microsoft"))

        self.assertEqual(response.provider_name, "deterministic-fallback")
        self.assertIn("technology company", response.answer.lower())


class InternetRuntimeIntegrationTests(unittest.TestCase):
    """Verify Brain/skills integration for the new grounded research path."""

    def _build_brain(
        self,
        internet_service: _InternetServiceStub,
        *,
        desktop_control: _DesktopControl | None = None,
    ) -> BrainEngine:
        skill_services = build_skill_services()
        skill_services.registry.register(InternetSkill(internet_service=internet_service))
        if desktop_control is not None:
            desktop_services = build_desktop_command_services(desktop_control=desktop_control)
            skill_services.registry.register(
                DesktopSkill(
                    desktop_control=desktop_control,
                    desktop_command_pipeline=desktop_services.pipeline,
                )
            )
        return BrainEngine(skill_executor=skill_services.executor)

    def test_internet_research_command_routes_exactly_once(self) -> None:
        query = ResearchQuery("Search the internet for artificial intelligence", "artificial intelligence", "artificial intelligence")
        response = GroundedResearchResponse(
            query=query,
            answer="Artificial intelligence refers to computer systems that perform tasks associated with human intelligence.",
            sources=(type("Source", (), {"title": "AI source", "url": "https://example.com/ai", "domain": "example.com"})(),),
            provider_name="deterministic-fallback",
            search_result_count=1,
            pages_read_count=1,
        )
        internet_service = _InternetServiceStub(response)
        brain = self._build_brain(internet_service)

        result = brain.receive_text("Search the internet for artificial intelligence", conversation_id="conv-research")

        self.assertEqual(len(internet_service.calls), 1)
        self.assertEqual(result.provider_name, "skills-runtime")
        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertIn("Research summary for 'artificial intelligence':", result.message)

    def test_natural_topic_research_routes_exactly_once(self) -> None:
        internet_service = _InternetServiceStub(_research_response("Kingfisher"))
        brain = self._build_brain(internet_service)

        result = brain.receive_text("Kingfisher ke bare me batao", conversation_id="conv-kingfisher")

        self.assertEqual(len(internet_service.calls), 1)
        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(result.metadata["skill_data"]["intent_kind"], "natural_research")
        request_query, _limit = internet_service.calls[0]
        assert isinstance(request_query, ResearchQuery)
        self.assertEqual(request_query.topic, "Kingfisher")

    def test_short_semantic_query_routes_to_internet(self) -> None:
        internet_service = _InternetServiceStub(_research_response("World Best Game Popular"))
        brain = self._build_brain(internet_service)

        result = brain.receive_text("World Best Game Popular", conversation_id="conv-short-query")

        self.assertEqual(len(internet_service.calls), 1)
        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(result.metadata["skill_data"]["intent_kind"], "natural_research")
        request_query, _limit = internet_service.calls[0]
        assert isinstance(request_query, ResearchQuery)
        self.assertEqual(request_query.search_text, "World Best Game Popular")

    def test_conversational_follow_up_reuses_last_internet_topic(self) -> None:
        internet_service = _InternetServiceStub(_research_response("Kingfisher"))
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Kingfisher ke bare me batao", conversation_id="conv-followup")
        second = brain.receive_text("Iski latest information batao", conversation_id="conv-followup")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(len(internet_service.calls), 2)
        second_query, _limit = internet_service.calls[1]
        assert isinstance(second_query, ResearchQuery)
        self.assertEqual(second_query.topic, "Kingfisher")
        self.assertEqual(second_query.intent_kind, "follow_up")
        self.assertIn("Kingfisher", second_query.search_text)
        self.assertIn("latest", second_query.search_text.lower())

    def test_desktop_action_clears_stale_internet_follow_up_context(self) -> None:
        internet_service = _InternetServiceStub(_research_response("Kingfisher"))
        desktop_control = _DesktopControl()
        brain = self._build_brain(internet_service, desktop_control=desktop_control)

        first = brain.receive_text("Kingfisher ke bare me batao", conversation_id="conv-desktop-reset")
        second = brain.receive_text("Take screenshot", conversation_id="conv-desktop-reset")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-desktop-reset")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "desktop.control")
        self.assertEqual(len(internet_service.calls), 1)
        self.assertNotEqual(third.metadata.get("skill_name"), "internet.query")
        self.assertEqual(len(internet_service.calls), 1)

    def test_local_system_turn_clears_stale_internet_follow_up_context(self) -> None:
        internet_service = _InternetServiceStub(_research_response("Kingfisher"))
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Kingfisher ke bare me batao", conversation_id="conv-local-reset")
        second = brain.receive_text("Status kya hai", conversation_id="conv-local-reset")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-local-reset")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(len(internet_service.calls), 1)
        self.assertNotEqual(second.metadata.get("skill_name"), "internet.query")
        self.assertNotEqual(third.metadata.get("skill_name"), "internet.query")
        self.assertEqual(len(internet_service.calls), 1)

    def test_weather_today_routes_to_internet_handler_without_research_call(self) -> None:
        internet_service = _InternetServiceStub(_research_response("Weather"))
        brain = self._build_brain(internet_service)

        result = brain.receive_text("Weather today in Ahmedabad", conversation_id="conv-weather")

        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(internet_service.calls, [])
        self.assertEqual(internet_service.weather_calls, ["Ahmedabad"])
        self.assertIn("Weather for Ahmedabad", result.message)

    def test_latest_news_routes_to_internet_news_handler_without_research_call(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("News"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Adobe launches new suite",
                        "source": "Example News",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/adobe-suite",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        result = brain.receive_text("Latest news about Adobe", conversation_id="conv-latest-news")

        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(internet_service.calls, [])
        self.assertEqual(len(internet_service.news_calls), 1)
        request_query, limit = internet_service.news_calls[0]
        self.assertEqual(limit, 5)
        self.assertIsInstance(request_query, NewsQuery)
        assert isinstance(request_query, NewsQuery)
        self.assertEqual(request_query.topic, "Adobe")
        self.assertEqual(request_query.query_text, "Adobe latest news")
        self.assertIn("Adobe launches new suite", result.message)

    def test_source_aware_news_requests_route_to_internet_news_handler_without_research_call(self) -> None:
        cases = (
            ("latest news from Sandesh", {"source": "Sandesh", "query_text": "Sandesh latest news"}),
            ("Sandesh news", {"source": "Sandesh", "query_text": "Sandesh news"}),
            ("Divya Bhaskar news", {"source": "Divya Bhaskar", "query_text": "Divya Bhaskar news"}),
            ("Aaj Tak latest news", {"source": "Aaj Tak", "query_text": "Aaj Tak latest news"}),
            ("आज तक latest news", {"source": "Aaj Tak", "query_text": "Aaj Tak latest news"}),
            ("સંદેશ news", {"source": "Sandesh", "query_text": "Sandesh news"}),
            ("India Today world news", {"source": "India Today", "category": "world", "query_text": "India Today world news"}),
            ("Gujarat news", {"location": "Gujarat", "query_text": "Gujarat news"}),
            ("India news", {"location": "India", "query_text": "India news"}),
            ("Gujarat news from Sandesh", {"location": "Gujarat", "source": "Sandesh", "query_text": "Gujarat Sandesh news"}),
            ("Gujarat news from સંદેશ", {"location": "Gujarat", "source": "Sandesh", "query_text": "Gujarat Sandesh news"}),
            ("India news from Aaj Tak", {"location": "India", "source": "Aaj Tak", "query_text": "India Aaj Tak news"}),
            ("world news from India Today", {"source": "India Today", "category": "world", "query_text": "India Today world news"}),
            (
                "latest news about Adobe from Sandesh",
                {"topic": "Adobe", "source": "Sandesh", "query_text": "Adobe Sandesh latest news"},
            ),
        )

        for text, expected in cases:
            with self.subTest(text=text):
                internet_service = _InternetServiceStub(
                    _research_response("News"),
                    news_results=[
                        type(
                            "Article",
                            (),
                            {
                                "title": "Source aware headline",
                                "source": "Example News",
                                "published_at": "2026-07-07T01:25:38Z",
                                "url": "https://example.com/source-aware",
                            },
                        )()
                    ],
                )
                brain = self._build_brain(internet_service)

                result = brain.receive_text(text, conversation_id=f"conv-source-aware-{text}")

                self.assertEqual(result.metadata["skill_name"], "internet.query")
                self.assertEqual(internet_service.calls, [])
                self.assertEqual(len(internet_service.news_calls), 1)
                request_query, limit = internet_service.news_calls[0]
                self.assertEqual(limit, 5)
                self.assertIsInstance(request_query, NewsQuery)
                assert isinstance(request_query, NewsQuery)
                self.assertEqual(request_query.query_text, expected["query_text"])
                self.assertEqual(request_query.topic, expected.get("topic", ""))
                self.assertEqual(request_query.location, expected.get("location", ""))
                self.assertEqual(request_query.source, expected.get("source", ""))
                self.assertEqual(request_query.category, expected.get("category", ""))
                self.assertIn("Source aware headline", result.message)

    def test_direct_news_turn_replaces_stale_internet_topic_for_follow_up(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Bitcoin"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Adobe launches new suite",
                        "source": "Example News",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/adobe-suite",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Bitcoin kya hai", conversation_id="conv-news-follow-up")
        second = brain.receive_text("Latest news about Adobe", conversation_id="conv-news-follow-up")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-news-follow-up")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(third.metadata["skill_name"], "internet.query")
        self.assertEqual(len(internet_service.news_calls), 2)
        self.assertEqual(len(internet_service.calls), 1)
        follow_up_query, _limit = internet_service.news_calls[1]
        self.assertIsInstance(follow_up_query, NewsQuery)
        assert isinstance(follow_up_query, NewsQuery)
        self.assertEqual(follow_up_query.topic, "Adobe")
        self.assertEqual(follow_up_query.query_text, "Adobe latest news")
        self.assertNotEqual(follow_up_query.topic, "Bitcoin")

    def test_source_specific_news_turn_replaces_stale_internet_topic_for_follow_up(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Bitcoin"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Adobe launches new suite",
                        "source": "Sandesh",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/adobe-suite",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Bitcoin kya hai", conversation_id="conv-source-news-follow-up")
        second = brain.receive_text("latest news about Adobe from Sandesh", conversation_id="conv-source-news-follow-up")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-source-news-follow-up")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(third.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_data"]["query"], "Adobe Sandesh")
        self.assertEqual(second.metadata["skill_data"]["search_text"], "Adobe Sandesh latest news")
        self.assertEqual(len(internet_service.news_calls), 2)
        self.assertEqual(len(internet_service.calls), 1)
        follow_up_query, _limit = internet_service.news_calls[1]
        self.assertIsInstance(follow_up_query, NewsQuery)
        assert isinstance(follow_up_query, NewsQuery)
        self.assertEqual(follow_up_query.topic, "Adobe")
        self.assertEqual(follow_up_query.source, "Sandesh")
        self.assertEqual(follow_up_query.query_text, "Adobe Sandesh latest news")
        self.assertNotEqual(follow_up_query.topic, "Bitcoin")

    def test_source_specific_news_follow_up_context_survives_deduped_results(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Bitcoin"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Adobe creator tools update",
                        "source": "Sandesh",
                        "published_at": "2026-07-07T03:25:38Z",
                        "url": "https://example.com/adobe-deduped",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Bitcoin kya hai", conversation_id="conv-source-news-deduped-follow-up")
        second = brain.receive_text("latest news about Adobe from Sandesh", conversation_id="conv-source-news-deduped-follow-up")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-source-news-deduped-follow-up")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(third.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_data"]["query"], "Adobe Sandesh")
        self.assertEqual(second.metadata["skill_data"]["search_text"], "Adobe Sandesh latest news")
        self.assertEqual(len(internet_service.news_calls), 2)
        self.assertEqual(len(internet_service.calls), 1)
        follow_up_query, _limit = internet_service.news_calls[1]
        self.assertIsInstance(follow_up_query, NewsQuery)
        assert isinstance(follow_up_query, NewsQuery)
        self.assertEqual(follow_up_query.topic, "Adobe")
        self.assertEqual(follow_up_query.source, "Sandesh")
        self.assertEqual(follow_up_query.query_text, "Adobe Sandesh latest news")
        self.assertNotEqual(follow_up_query.topic, "Bitcoin")

    def test_source_only_news_turn_replaces_stale_internet_topic_for_follow_up(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Bitcoin"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Sandesh top headlines",
                        "source": "Sandesh",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/sandesh-headlines",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Bitcoin kya hai", conversation_id="conv-source-only-news-follow-up")
        second = brain.receive_text("latest news from Sandesh", conversation_id="conv-source-only-news-follow-up")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-source-only-news-follow-up")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(third.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_data"]["query"], "Sandesh")
        self.assertEqual(second.metadata["skill_data"]["search_text"], "Sandesh latest news")
        self.assertEqual(len(internet_service.news_calls), 2)
        self.assertEqual(len(internet_service.calls), 1)
        follow_up_query, _limit = internet_service.news_calls[1]
        self.assertIsInstance(follow_up_query, NewsQuery)
        assert isinstance(follow_up_query, NewsQuery)
        self.assertEqual(follow_up_query.source, "Sandesh")
        self.assertEqual(follow_up_query.query_text, "Sandesh latest news")

    def test_source_specific_news_follow_up_context_survives_no_valid_results(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Bitcoin"),
            news_results=[],
        )
        brain = self._build_brain(internet_service)

        first = brain.receive_text("Bitcoin kya hai", conversation_id="conv-source-news-no-results-follow-up")
        second = brain.receive_text("latest news about Adobe from Sandesh", conversation_id="conv-source-news-no-results-follow-up")
        third = brain.receive_text("Iski latest information batao", conversation_id="conv-source-news-no-results-follow-up")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(third.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_data"]["query"], "Adobe Sandesh")
        self.assertEqual(second.metadata["skill_data"]["search_text"], "Adobe Sandesh latest news")
        self.assertEqual(second.message, "No news articles are available for 'Adobe news from Sandesh'.")
        self.assertEqual(third.message, "No news articles are available for 'Adobe news from Sandesh'.")
        self.assertEqual(len(internet_service.news_calls), 2)
        self.assertEqual(len(internet_service.calls), 1)
        follow_up_query, _limit = internet_service.news_calls[1]
        self.assertIsInstance(follow_up_query, NewsQuery)
        assert isinstance(follow_up_query, NewsQuery)
        self.assertEqual(follow_up_query.topic, "Adobe")
        self.assertEqual(follow_up_query.source, "Sandesh")
        self.assertEqual(follow_up_query.query_text, "Adobe Sandesh latest news")
        self.assertNotEqual(follow_up_query.topic, "Bitcoin")

    def test_explicit_research_style_follow_up_still_uses_research_after_news_turn(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Bitcoin"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Technology headlines",
                        "source": "India Today",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/technology-headlines",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        first = brain.receive_text("latest news about technology from India Today", conversation_id="conv-explicit-research-after-news")
        second = brain.receive_text("iski latest information internet se batao", conversation_id="conv-explicit-research-after-news")

        self.assertEqual(first.metadata["skill_name"], "internet.query")
        self.assertEqual(second.metadata["skill_name"], "internet.query")
        self.assertEqual(len(internet_service.news_calls), 1)
        self.assertEqual(len(internet_service.calls), 1)
        follow_up_query, _limit = internet_service.calls[0]
        self.assertIsInstance(follow_up_query, ResearchQuery)

    def test_unknown_source_news_request_preserves_existing_research_fallback(self) -> None:
        internet_service = _InternetServiceStub(_research_response("ExampleWire", search_text="latest news from ExampleWire"))
        brain = self._build_brain(internet_service)

        result = brain.receive_text("latest news from ExampleWire", conversation_id="conv-unknown-source")

        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(internet_service.news_calls, [])
        self.assertEqual(len(internet_service.calls), 1)
        request_query, _limit = internet_service.calls[0]
        self.assertIsInstance(request_query, ResearchQuery)
        assert isinstance(request_query, ResearchQuery)
        self.assertIn("ExampleWire", request_query.search_text)

    def test_world_news_routes_to_internet_news_handler_without_research_call(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("News"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "World markets steady",
                        "source": "Global Wire",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/world-markets",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        result = brain.receive_text("world news", conversation_id="conv-world-news")

        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(internet_service.calls, [])
        self.assertEqual(len(internet_service.news_calls), 1)
        request_query, _limit = internet_service.news_calls[0]
        self.assertIsInstance(request_query, NewsQuery)
        assert isinstance(request_query, NewsQuery)
        self.assertEqual(request_query.query_text, "world news")
        self.assertEqual(request_query.category, "world")
        self.assertIn("World markets steady", result.message)

    def test_todays_top_news_routes_to_internet_news_handler_without_research_call(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("News"),
            news_results=[
                type(
                    "Article",
                    (),
                    {
                        "title": "Top stories round-up",
                        "source": "Morning Ledger",
                        "published_at": "2026-07-07T01:25:38Z",
                        "url": "https://example.com/top-stories",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        result = brain.receive_text("Today's top news", conversation_id="conv-top-news")

        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(internet_service.calls, [])
        self.assertEqual(len(internet_service.news_calls), 1)
        request_query, _limit = internet_service.news_calls[0]
        self.assertIsInstance(request_query, NewsQuery)
        assert isinstance(request_query, NewsQuery)
        self.assertEqual(request_query.request_type, "latest")
        self.assertEqual(request_query.category, "top")
        self.assertIn("Top stories round-up", result.message)

    def test_wikipedia_prefix_routes_to_internet_handler_without_research_call(self) -> None:
        internet_service = _InternetServiceStub(
            _research_response("Wikipedia"),
            wikipedia_results=[
                type(
                    "Wiki",
                    (),
                    {
                        "title": "Albert Einstein",
                        "summary": "Albert Einstein was a theoretical physicist.",
                        "url": "https://en.wikipedia.org/wiki/Albert_Einstein",
                    },
                )()
            ],
        )
        brain = self._build_brain(internet_service)

        result = brain.receive_text("wikipedia Albert Einstein", conversation_id="conv-wikipedia")

        self.assertEqual(result.metadata["skill_name"], "internet.query")
        self.assertEqual(internet_service.calls, [])
        self.assertEqual(internet_service.wikipedia_calls, [("Albert Einstein", 3)])
        self.assertIn("Albert Einstein", result.message)
        self.assertIn("https://en.wikipedia.org/wiki/Albert_Einstein", result.message)

    def test_open_app_commands_still_route_to_desktop_control(self) -> None:
        research_response = GroundedResearchResponse(
            query=ResearchQuery("Search the internet for AI", "AI", "AI"),
            answer="AI summary",
            sources=(),
            provider_name="deterministic-fallback",
            search_result_count=0,
            pages_read_count=0,
        )
        internet_service = _InternetServiceStub(research_response)
        desktop_control = _DesktopControl()
        brain = self._build_brain(internet_service, desktop_control=desktop_control)

        result = brain.receive_text("Open YouTube", conversation_id="conv-open")

        self.assertEqual(result.metadata["skill_name"], "desktop.control")
        self.assertEqual(desktop_control.opened_applications, ["YouTube"])
        self.assertEqual(internet_service.calls, [])

    def test_open_instagram_still_routes_to_desktop_control(self) -> None:
        research_response = GroundedResearchResponse(
            query=ResearchQuery("Search the internet for AI", "AI", "AI"),
            answer="AI summary",
            sources=(),
            provider_name="deterministic-fallback",
            search_result_count=0,
            pages_read_count=0,
        )
        internet_service = _InternetServiceStub(research_response)
        desktop_control = _DesktopControl()
        brain = self._build_brain(internet_service, desktop_control=desktop_control)

        result = brain.receive_text("Open Instagram", conversation_id="conv-open-instagram")

        self.assertEqual(result.metadata["skill_name"], "desktop.control")
        self.assertEqual(desktop_control.opened_applications, ["Instagram"])
        self.assertEqual(internet_service.calls, [])

    def test_open_photoshop_still_routes_to_desktop_control(self) -> None:
        research_response = GroundedResearchResponse(
            query=ResearchQuery("Search the internet for AI", "AI", "AI"),
            answer="AI summary",
            sources=(),
            provider_name="deterministic-fallback",
            search_result_count=0,
            pages_read_count=0,
        )
        internet_service = _InternetServiceStub(research_response)
        desktop_control = _DesktopControl()
        brain = self._build_brain(internet_service, desktop_control=desktop_control)

        result = brain.receive_text("Open Photoshop", conversation_id="conv-open-photoshop")

        self.assertEqual(result.metadata["skill_name"], "desktop.control")
        self.assertEqual(desktop_control.opened_applications, ["Photoshop"])
        self.assertEqual(internet_service.calls, [])

    def test_press_enter_still_routes_to_desktop_control(self) -> None:
        internet_service = _InternetServiceStub(_research_response("AI"))
        desktop_control = _DesktopControl()
        brain = self._build_brain(internet_service, desktop_control=desktop_control)

        result = brain.receive_text("Press enter", conversation_id="conv-press-enter")

        self.assertEqual(result.metadata["skill_name"], "desktop.control")
        self.assertEqual(internet_service.calls, [])


if __name__ == "__main__":
    unittest.main()
