"""Tests for the live Google News RSS-backed news provider."""

from __future__ import annotations

import unittest
from typing import Any

from Internet import GoogleNewsRssProvider, NewsQuery
from Internet.news import canonicalize_news_source, normalize_news_request


class _QueuedHttpClient:
    """HTTP client stub that returns queued responses without live network access."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float | None]] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        self.calls.append((url, timeout))
        if not self.responses:
            raise AssertionError("Unexpected GET request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        raise AssertionError("POST should not be used by the news provider")


class GoogleNewsRssProviderTests(unittest.TestCase):
    """Verify the Google News RSS provider normalizes feed responses safely."""

    def test_provider_uses_top_feed_for_latest_requests_and_normalizes_articles(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Top story one</title>
                              <link>https://news.google.com/rss/articles/abc</link>
                              <description>&lt;p&gt;Top story summary&lt;/p&gt;</description>
                              <pubDate>Tue, 07 Jul 2026 01:25:38 GMT</pubDate>
                              <source url="https://example.com">Example Source</source>
                            </item>
                            <item>
                              <title>Top story two</title>
                              <link>https://news.google.com/rss/articles/def</link>
                              <description>&lt;p&gt;Second summary&lt;/p&gt;</description>
                              <pubDate>Tue, 07 Jul 2026 02:10:00 GMT</pubDate>
                              <source>Second Source</source>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client, timeout_seconds=4.0)

        results = provider.fetch(limit=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "Top story one")
        self.assertEqual(results[0].summary, "Top story summary")
        self.assertEqual(results[0].source, "Example Source")
        self.assertEqual(results[0].published_at, "2026-07-07T01:25:38Z")
        self.assertEqual(results[0].metadata["provider"], "google-news-rss")
        self.assertEqual(results[0].metadata["request_type"], "latest")
        self.assertEqual(results[0].metadata["requested_query"], "latest news")
        self.assertEqual(results[0].metadata["requested_category"], "top")
        self.assertEqual(results[0].metadata["rank"], 1)
        self.assertEqual(results[0].metadata["source_url"], "https://example.com")
        self.assertEqual(len(http_client.calls), 1)
        self.assertIn("https://news.google.com/rss?", http_client.calls[0][0])
        self.assertIn("hl=en-IN", http_client.calls[0][0])
        self.assertIn("gl=IN", http_client.calls[0][0])
        self.assertIn("ceid=IN%3Aen", http_client.calls[0][0])
        self.assertEqual(http_client.calls[0][1], 4.0)

    def test_provider_uses_search_feed_for_structured_requests(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Technology update</title>
                              <link>https://news.google.com/rss/articles/tech</link>
                              <source>Reuters</source>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(
            NewsQuery(request_type="search", topic="technology", location="India", source="Reuters"),
            limit=3,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Technology update")
        self.assertEqual(results[0].topic, "technology")
        self.assertEqual(results[0].metadata["requested_topic"], "technology")
        self.assertEqual(results[0].metadata["requested_location"], "India")
        self.assertEqual(results[0].metadata["requested_source"], "Reuters")
        self.assertIn("https://news.google.com/rss/search?", http_client.calls[0][0])
        self.assertIn("q=technology+India+Reuters+news", http_client.calls[0][0])

    def test_provider_returns_empty_list_when_feed_has_no_items(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "text": "<rss><channel></channel></rss>"}])
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch("world news", limit=5)

        self.assertEqual(results, [])
        self.assertEqual(len(http_client.calls), 1)

    def test_provider_returns_empty_list_on_http_error(self) -> None:
        http_client = _QueuedHttpClient([{"status": 503, "error": "service unavailable"}])
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch("technology", limit=3)

        self.assertEqual(results, [])

    def test_provider_returns_empty_list_on_transport_exception(self) -> None:
        http_client = _QueuedHttpClient([TimeoutError("timed out")])
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch("technology", limit=3)

        self.assertEqual(results, [])

    def test_provider_returns_empty_list_on_malformed_feed(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "text": "<rss><channel><item></rss>"}])
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch("technology", limit=3)

        self.assertEqual(results, [])

    def test_provider_handles_missing_optional_fields_deterministically(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Simple headline</title>
                              <link>https://news.google.com/rss/articles/simple</link>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch("climate", limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].summary, "")
        self.assertEqual(results[0].source, "")
        self.assertEqual(results[0].published_at, "")
        self.assertEqual(results[0].topic, "climate")
        self.assertEqual(results[0].metadata["requested_topic"], "climate")
        self.assertNotIn("payload", results[0].metadata)

    def test_provider_treats_blank_requests_as_latest_news(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Blank request still maps to top stories</title>
                              <link>https://news.google.com/rss/articles/top</link>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch("   ", limit=1)

        self.assertEqual(len(results), 1)
        self.assertIn("https://news.google.com/rss?", http_client.calls[0][0])

    def test_normalize_news_request_canonicalizes_known_source_aliases(self) -> None:
        normalized = normalize_news_request("દિવ્ય ભાસ્કર")

        self.assertEqual(normalized.source, "Divya Bhaskar")
        self.assertEqual(normalized.query_text, "Divya Bhaskar news")

    def test_provider_builds_canonical_google_queries_for_source_aware_requests(self) -> None:
        cases = (
            (
                NewsQuery(request_type="search", source="સંદેશ"),
                "q=Sandesh+news",
            ),
            (
                NewsQuery(request_type="search", topic="Adobe", source="आज तक"),
                "q=Adobe+Aaj+Tak+news",
            ),
            (
                NewsQuery(request_type="search", location="Gujarat", source="દિવ્ય ભાસ્કર"),
                "q=Gujarat+Divya+Bhaskar+news",
            ),
            (
                NewsQuery(request_type="search", source="indiatoday", category="world"),
                "q=India+Today+world+news",
            ),
        )

        for request, expected_query in cases:
            with self.subTest(request=request):
                http_client = _QueuedHttpClient(
                    [
                        {
                            "status": 200,
                            "text": f"""
                                <rss version="2.0">
                                  <channel>
                                    <item>
                                      <title>Canonical query headline</title>
                                      <link>https://news.google.com/rss/articles/source-aware</link>
                                      <source>{canonicalize_news_source(request.source) or "Google News"}</source>
                                    </item>
                                  </channel>
                                </rss>
                            """,
                        }
                    ]
                )
                provider = GoogleNewsRssProvider(http_client=http_client)

                results = provider.fetch(request, limit=1)

                self.assertEqual(len(results), 1)
                self.assertIn("https://news.google.com/rss/search?", http_client.calls[0][0])
                self.assertIn(expected_query, http_client.calls[0][0])

    def test_provider_filters_source_topic_results_to_matching_source_and_topic(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Writer Raises $200M Series C for AI platform</title>
                              <link>https://news.google.com/rss/articles/business-wire</link>
                              <source>Business Wire</source>
                            </item>
                            <item>
                              <title>Adobe expands creator tooling in Gujarat</title>
                              <link>https://news.google.com/rss/articles/sandesh-adobe</link>
                              <description>Sandesh reports Adobe is expanding creator tooling.</description>
                              <source>Sandesh</source>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(
            NewsQuery(request_type="search", topic="Adobe", source="Sandesh", query_text="Adobe Sandesh latest news"),
            limit=5,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Adobe expands creator tooling in Gujarat")
        self.assertEqual(results[0].source, "Sandesh")

    def test_provider_returns_no_results_when_source_topic_feed_has_only_unrelated_publishers(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Adobe launches a new campaign</title>
                              <link>https://news.google.com/rss/articles/business-wire</link>
                              <description>Business Wire covers Adobe.</description>
                              <source>Business Wire</source>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(
            NewsQuery(request_type="search", topic="Adobe", source="Sandesh", query_text="Adobe Sandesh latest news"),
            limit=5,
        )

        self.assertEqual(results, [])

    def test_provider_keeps_matching_source_only_results_when_unrelated_publishers_appear_first(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": """
                        <rss version="2.0">
                          <channel>
                            <item>
                              <title>Top finance bulletin</title>
                              <link>https://news.google.com/rss/articles/business-wire</link>
                              <source>Business Wire</source>
                            </item>
                            <item>
                              <title>Sandesh morning headlines</title>
                              <link>https://news.google.com/rss/articles/sandesh-top</link>
                              <source>Sandesh</source>
                            </item>
                          </channel>
                        </rss>
                    """,
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", source="Sandesh", query_text="Sandesh latest news"), limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Sandesh morning headlines")
        self.assertEqual(results[0].source, "Sandesh")


if __name__ == "__main__":
    unittest.main()
