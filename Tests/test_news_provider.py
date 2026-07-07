"""Tests for the live Google News RSS-backed news provider."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest import mock
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


def _rss_item(
    *,
    title: str | None = None,
    link: str = "",
    description: str | None = None,
    source: str | None = None,
    pub_date: str | None = None,
    category: str | None = None,
) -> str:
    """Build one compact RSS item fixture."""

    fields: list[str] = []
    if title is not None:
        fields.append(f"<title>{title}</title>")
    if link:
        fields.append(f"<link>{link}</link>")
    if description is not None:
        fields.append(f"<description>{description}</description>")
    if pub_date is not None:
        fields.append(f"<pubDate>{pub_date}</pubDate>")
    if source is not None:
        fields.append(f"<source>{source}</source>")
    if category is not None:
        fields.append(f"<category>{category}</category>")
    return f"<item>{''.join(fields)}</item>"


def _rss_feed(*items: str) -> str:
    """Wrap RSS items in one simple feed document."""

    return f"<rss version=\"2.0\"><channel>{''.join(items)}</channel></rss>"


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
        self.assertEqual([result.title for result in results], ["Top story two", "Top story one"])
        self.assertEqual(results[0].published_at, "2026-07-07T02:10:00Z")
        self.assertEqual(results[0].metadata["provider"], "google-news-rss")
        self.assertEqual(results[0].metadata["request_type"], "latest")
        self.assertEqual(results[0].metadata["requested_query"], "latest news")
        self.assertEqual(results[0].metadata["requested_category"], "top")
        self.assertEqual(results[0].metadata["rank"], 2)
        self.assertEqual(results[1].summary, "Top story summary")
        self.assertEqual(results[1].source, "Example Source")
        self.assertEqual(results[1].metadata["source_url"], "https://example.com")
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
                                      <title>{request.topic or request.location or request.category or "Canonical"} query headline</title>
                                      <description>{request.topic or request.location or request.category or "Canonical"} query summary</description>
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

    def test_provider_deduplicates_exact_same_source_story_with_different_google_urls(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/one", source="Reuters"),
                        _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/two", source="Reuters"),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", source="Reuters", query_text="Reuters news"), limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Adobe launches new suite")

    def test_provider_deduplicates_normalized_title_variants_from_same_source(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/one", source="Reuters"),
                        _rss_item(title="ADOBE launches new suite!", link="https://news.google.com/rss/articles/two", source="Reuters"),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", source="Reuters", query_text="Reuters news"), limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Adobe launches new suite")

    def test_provider_deduplicates_equivalent_source_alias_titles_under_one_canonical_source(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/one", source="Aaj Tak"),
                        _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/two", source="AajTak"),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", source="Aaj Tak", query_text="Aaj Tak news"), limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "Aaj Tak")

    def test_provider_prefers_newer_valid_non_future_duplicate_timestamp(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Adobe launches new suite",
                            link="https://news.google.com/rss/articles/older",
                            source="Reuters",
                            pub_date="Tue, 07 Jul 2026 01:25:38 GMT",
                        ),
                        _rss_item(
                            title="Adobe launches new suite",
                            link="https://news.google.com/rss/articles/newer",
                            source="Reuters",
                            pub_date="Tue, 07 Jul 2026 03:25:38 GMT",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)
        with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            results = provider.fetch(NewsQuery(request_type="search", source="Reuters", query_text="Reuters news"), limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/newer")
        self.assertEqual(results[0].published_at, "2026-07-07T03:25:38Z")

    def test_provider_keeps_first_duplicate_when_timestamps_are_equal_missing_or_invalid(self) -> None:
        cases = (
            (
                "equal",
                _rss_item(
                    title="Adobe launches new suite",
                    link="https://news.google.com/rss/articles/first",
                    source="Reuters",
                    pub_date="Tue, 07 Jul 2026 01:25:38 GMT",
                ),
                _rss_item(
                    title="Adobe launches new suite",
                    link="https://news.google.com/rss/articles/second",
                    source="Reuters",
                    pub_date="Tue, 07 Jul 2026 01:25:38 GMT",
                ),
            ),
            (
                "missing",
                _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/first", source="Reuters"),
                _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/second", source="Reuters"),
            ),
            (
                "invalid",
                _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/first", source="Reuters", pub_date="invalid"),
                _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/second", source="Reuters", pub_date="still invalid"),
            ),
        )

        for label, first_item, second_item in cases:
            with self.subTest(case=label):
                http_client = _QueuedHttpClient([{"status": 200, "text": _rss_feed(first_item, second_item)}])
                provider = GoogleNewsRssProvider(http_client=http_client)
                with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
                    results = provider.fetch(NewsQuery(request_type="search", source="Reuters", query_text="Reuters news"), limit=5)

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].url, "https://news.google.com/rss/articles/first")

    def test_provider_does_not_give_future_duplicate_timestamp_priority(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Adobe launches new suite",
                            link="https://news.google.com/rss/articles/current",
                            source="Reuters",
                            pub_date="Tue, 07 Jul 2026 01:25:38 GMT",
                        ),
                        _rss_item(
                            title="Adobe launches new suite",
                            link="https://news.google.com/rss/articles/future",
                            source="Reuters",
                            pub_date="Tue, 07 Jul 2099 01:25:38 GMT",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)
        with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            results = provider.fetch(NewsQuery(request_type="search", source="Reuters", query_text="Reuters news"), limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/current")

    def test_provider_applies_source_filter_before_deduplicating_same_title_from_other_publishers(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Adobe launches new suite",
                            link="https://news.google.com/rss/articles/business-wire",
                            description="Adobe story from Business Wire.",
                            source="Business Wire",
                        ),
                        _rss_item(
                            title="Adobe launches new suite",
                            link="https://news.google.com/rss/articles/sandesh",
                            description="Adobe story from Sandesh.",
                            source="Sandesh",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(
            NewsQuery(request_type="search", topic="Adobe", source="Sandesh", query_text="Adobe Sandesh latest news"),
            limit=5,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "Sandesh")
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/sandesh")

    def test_provider_ranks_exact_canonical_source_match_above_weak_source_match(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Adobe creator tools update",
                            link="https://news.google.com/rss/articles/weak",
                            description="Adobe update from a regional Sandesh desk.",
                            source="Sandesh Gujarati Edition",
                        ),
                        _rss_item(
                            title="Adobe creator tools update",
                            link="https://news.google.com/rss/articles/exact",
                            description="Adobe update from Sandesh.",
                            source="Sandesh",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(
            NewsQuery(request_type="search", topic="Adobe", source="Sandesh", query_text="Adobe Sandesh latest news"),
            limit=5,
        )

        self.assertEqual([result.source for result in results], ["Sandesh", "Sandesh Gujarati Edition"])

    def test_provider_ranks_topic_relevant_story_first(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Markets close mixed", link="https://news.google.com/rss/articles/generic", description="Economic roundup."),
                        _rss_item(title="Adobe launches new suite", link="https://news.google.com/rss/articles/adobe", description="Adobe expands creative tooling."),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", topic="Adobe", query_text="Adobe latest news"), limit=5)

        self.assertEqual([result.title for result in results], ["Adobe launches new suite", "Markets close mixed"])

    def test_provider_ranks_location_relevant_story_first(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Business update", link="https://news.google.com/rss/articles/generic", description="National business roundup."),
                        _rss_item(title="Gujarat factory expansion", link="https://news.google.com/rss/articles/gujarat", description="New jobs are opening in Gujarat."),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", location="Gujarat", query_text="Gujarat news"), limit=5)

        self.assertEqual([result.title for result in results], ["Gujarat factory expansion", "Business update"])

    def test_provider_ranks_category_relevant_story_first(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Local council update", link="https://news.google.com/rss/articles/local", description="City hall bulletin."),
                        _rss_item(title="Global markets steady", link="https://news.google.com/rss/articles/world", description="International stocks are steady."),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(NewsQuery(request_type="search", category="world", query_text="world news"), limit=5)

        self.assertEqual([result.title for result in results], ["Global markets steady", "Local council update"])

    def test_provider_demotes_stale_latest_news_results(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Older headline",
                            link="https://news.google.com/rss/articles/older",
                            pub_date="Tue, 30 Jun 2026 01:25:38 GMT",
                        ),
                        _rss_item(
                            title="Fresh headline",
                            link="https://news.google.com/rss/articles/fresh",
                            pub_date="Tue, 07 Jul 2026 03:25:38 GMT",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)
        with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            results = provider.fetch(limit=5)

        self.assertEqual([result.title for result in results], ["Fresh headline", "Older headline"])

    def test_provider_latest_source_topic_prefers_newest_valid_article(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Technology policy explainer",
                            link="https://news.google.com/rss/articles/older",
                            description="India Today explains a technology policy change.",
                            source="India Today",
                            pub_date="Fri, 26 Jun 2026 01:25:38 GMT",
                        ),
                        _rss_item(
                            title="Technology hiring rebounds",
                            link="https://news.google.com/rss/articles/newer",
                            description="India Today reports a technology hiring rebound.",
                            source="India Today",
                            pub_date="Tue, 07 Jul 2026 03:25:38 GMT",
                        ),
                        _rss_item(
                            title="Technology funding update",
                            link="https://news.google.com/rss/articles/middle",
                            description="India Today covers a technology funding update.",
                            source="India Today",
                            pub_date="Tue, 05 May 2026 05:25:38 GMT",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)
        request = NewsQuery(
            request_type="search",
            topic="technology",
            source="India Today",
            query_text="technology India Today latest news",
        )

        with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            results = provider.fetch(request, limit=5)

        self.assertEqual(
            [result.title for result in results],
            ["Technology hiring rebounds", "Technology policy explainer", "Technology funding update"],
        )

    def test_provider_latest_requests_do_not_reward_future_or_missing_timestamps(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Future technology teaser",
                            link="https://news.google.com/rss/articles/future",
                            description="India Today previews a future technology update.",
                            source="India Today",
                            pub_date="Wed, 08 Jul 2026 01:25:38 GMT",
                        ),
                        _rss_item(
                            title="Undated technology note",
                            link="https://news.google.com/rss/articles/undated",
                            description="India Today shares a technology briefing.",
                            source="India Today",
                        ),
                        _rss_item(
                            title="Recent technology roundup",
                            link="https://news.google.com/rss/articles/recent",
                            description="India Today reports the latest technology roundup.",
                            source="India Today",
                            pub_date="Tue, 07 Jul 2026 03:25:38 GMT",
                        ),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)
        request = NewsQuery(
            request_type="search",
            topic="technology",
            source="India Today",
            query_text="technology India Today latest news",
        )

        with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            results = provider.fetch(request, limit=5)

        self.assertEqual(
            [result.title for result in results],
            ["Recent technology roundup", "Future technology teaser", "Undated technology note"],
        )
        self.assertEqual(results[1].published_at, "2026-07-08T01:25:38Z")
        self.assertEqual(results[2].published_at, "")

    def test_provider_handles_missing_or_invalid_timestamps_safely(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="First headline", link="https://news.google.com/rss/articles/first", pub_date="invalid"),
                        _rss_item(title="Second headline", link="https://news.google.com/rss/articles/second"),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)
        with mock.patch.object(provider, "_utc_now", return_value=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)):
            results = provider.fetch(limit=5)

        self.assertEqual([result.title for result in results], ["First headline", "Second headline"])
        self.assertEqual(results[0].published_at, "invalid")
        self.assertEqual(results[1].published_at, "")

    def test_provider_ordering_is_deterministic_across_repeated_runs(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Alpha headline", link="https://news.google.com/rss/articles/alpha"),
                        _rss_item(title="Beta headline", link="https://news.google.com/rss/articles/beta"),
                    ),
                },
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="Alpha headline", link="https://news.google.com/rss/articles/alpha"),
                        _rss_item(title="Beta headline", link="https://news.google.com/rss/articles/beta"),
                    ),
                },
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        first = [result.title for result in provider.fetch(limit=5)]
        second = [result.title for result in provider.fetch(limit=5)]

        self.assertEqual(first, ["Alpha headline", "Beta headline"])
        self.assertEqual(second, first)

    def test_provider_discards_unusable_empty_title_items_before_limiting_results(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(title="...", link="https://news.google.com/rss/articles/unusable"),
                        _rss_item(title="Useful headline", link="https://news.google.com/rss/articles/useful"),
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(limit=5)

        self.assertEqual([result.title for result in results], ["Useful headline"])

    def test_provider_returns_no_results_when_source_match_lacks_real_topic_relevance(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "text": _rss_feed(
                        _rss_item(
                            title="Sandesh launches festival coverage",
                            link="https://news.google.com/rss/articles/sandesh-festival",
                            description="Regional festival coverage from Sandesh.",
                            source="Sandesh",
                        )
                    ),
                }
            ]
        )
        provider = GoogleNewsRssProvider(http_client=http_client)

        results = provider.fetch(
            NewsQuery(request_type="search", topic="Adobe", source="Sandesh", query_text="Adobe Sandesh latest news"),
            limit=5,
        )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
