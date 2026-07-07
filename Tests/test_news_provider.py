"""Tests for the live Google News RSS-backed news provider."""

from __future__ import annotations

import unittest
from typing import Any

from Internet import GoogleNewsRssProvider, NewsQuery


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


if __name__ == "__main__":
    unittest.main()
