"""Tests for the live MediaWiki-backed Wikipedia provider."""

from __future__ import annotations

import unittest
from typing import Any

from Internet import MediaWikiWikipediaProvider


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
        raise AssertionError("POST should not be used by the Wikipedia provider")


class MediaWikiWikipediaProviderTests(unittest.TestCase):
    """Verify the MediaWiki provider normalizes Wikipedia responses safely."""

    def test_provider_normalizes_successful_search_and_detail_results(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "search": [
                                {
                                    "pageid": 736,
                                    "title": "Albert Einstein",
                                    "snippet": "<span class=\"searchmatch\">Albert</span> Einstein was a physicist.",
                                    "timestamp": "2026-01-01T00:00:00Z",
                                },
                                {
                                    "pageid": 32857,
                                    "title": "Theory of relativity",
                                    "snippet": "Theory of relativity is a scientific theory.",
                                    "timestamp": "2026-01-02T00:00:00Z",
                                },
                            ]
                        }
                    },
                },
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "pages": {
                                "32857": {
                                    "pageid": 32857,
                                    "title": "Theory of relativity",
                                    "extract": "Theory of relativity usually encompasses two interrelated theories by Albert Einstein.",
                                    "canonicalurl": "https://en.wikipedia.org/wiki/Theory_of_relativity",
                                },
                                "736": {
                                    "pageid": 736,
                                    "title": "Albert Einstein",
                                    "extract": "Albert Einstein was a German-born theoretical physicist.",
                                    "canonicalurl": "https://en.wikipedia.org/wiki/Albert_Einstein",
                                },
                            }
                        }
                    },
                },
            ]
        )
        provider = MediaWikiWikipediaProvider(http_client=http_client, timeout_seconds=3.5)

        results = provider.search("  Albert Einstein  ", limit=5)

        self.assertEqual([result.title for result in results], ["Albert Einstein", "Theory of relativity"])
        self.assertEqual(
            [result.url for result in results],
            [
                "https://en.wikipedia.org/wiki/Albert_Einstein",
                "https://en.wikipedia.org/wiki/Theory_of_relativity",
            ],
        )
        self.assertEqual(results[0].summary, "Albert Einstein was a German-born theoretical physicist.")
        self.assertEqual(results[0].metadata["pageid"], 736)
        self.assertEqual(results[0].metadata["rank"], 1)
        self.assertEqual(results[0].metadata["search_snippet"], "Albert Einstein was a physicist.")
        self.assertEqual(len(http_client.calls), 2)
        self.assertIn("list=search", http_client.calls[0][0])
        self.assertIn("prop=extracts%7Cinfo", http_client.calls[1][0])
        self.assertIn("inprop=url", http_client.calls[1][0])
        self.assertIn("explaintext=1", http_client.calls[1][0])
        self.assertIn("exsentences=2", http_client.calls[1][0])
        self.assertEqual(http_client.calls[0][1], 3.5)
        self.assertEqual(http_client.calls[1][1], 3.5)

    def test_provider_preserves_multiple_ordered_results_for_disambiguation_like_queries(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "search": [
                                {"pageid": 10, "title": "Mercury", "snippet": "Mercury may refer to."},
                                {"pageid": 11, "title": "Mercury (planet)", "snippet": "Mercury is the smallest planet."},
                                {"pageid": 12, "title": "Mercury (element)", "snippet": "Mercury is a chemical element."},
                            ]
                        }
                    },
                },
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "pages": {
                                "12": {
                                    "pageid": 12,
                                    "title": "Mercury (element)",
                                    "extract": "Mercury is a chemical element with symbol Hg.",
                                    "canonicalurl": "https://en.wikipedia.org/wiki/Mercury_(element)",
                                },
                                "10": {
                                    "pageid": 10,
                                    "title": "Mercury",
                                    "extract": "Mercury may refer to multiple topics.",
                                    "canonicalurl": "https://en.wikipedia.org/wiki/Mercury",
                                },
                                "11": {
                                    "pageid": 11,
                                    "title": "Mercury (planet)",
                                    "extract": "Mercury is the smallest planet in the Solar System.",
                                    "canonicalurl": "https://en.wikipedia.org/wiki/Mercury_(planet)",
                                },
                            }
                        }
                    },
                },
            ]
        )
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("Mercury", limit=3)

        self.assertEqual(len(results), 3)
        self.assertEqual(
            [result.title for result in results],
            ["Mercury", "Mercury (planet)", "Mercury (element)"],
        )

    def test_provider_returns_empty_list_when_search_has_no_results(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "json": {"query": {"search": []}}}])
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("zzzz-not-a-page", limit=5)

        self.assertEqual(results, [])
        self.assertEqual(len(http_client.calls), 1)

    def test_provider_falls_back_to_cleaned_search_snippet_when_extract_is_missing(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "search": [
                                {
                                    "pageid": 99,
                                    "title": "Ada Lovelace",
                                    "snippet": "<span class=\"searchmatch\">Ada</span> Lovelace &amp; mathematician",
                                }
                            ]
                        }
                    },
                },
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "pages": {
                                "99": {
                                    "pageid": 99,
                                    "title": "Ada Lovelace",
                                    "canonicalurl": "https://en.wikipedia.org/wiki/Ada_Lovelace",
                                }
                            }
                        }
                    },
                },
            ]
        )
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("Ada Lovelace", limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].summary, "Ada Lovelace & mathematician")
        self.assertEqual(results[0].url, "https://en.wikipedia.org/wiki/Ada_Lovelace")

    def test_provider_returns_empty_list_on_malformed_json_response(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "text": "not-json"}])
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("Albert Einstein", limit=3)

        self.assertEqual(results, [])

    def test_provider_returns_empty_list_on_http_error(self) -> None:
        http_client = _QueuedHttpClient([{"status": 503, "error": "service unavailable"}])
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("Albert Einstein", limit=3)

        self.assertEqual(results, [])

    def test_provider_returns_empty_list_on_timeout_exception(self) -> None:
        http_client = _QueuedHttpClient([TimeoutError("timed out")])
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("Albert Einstein", limit=3)

        self.assertEqual(results, [])

    def test_provider_returns_empty_list_on_invalid_payload_shape(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "json": {
                        "query": {
                            "search": [
                                {"pageid": 736, "title": "Albert Einstein", "snippet": "Albert Einstein was a physicist."}
                            ]
                        }
                    },
                },
                {"status": 200, "json": {"query": {"pages": []}}},
            ]
        )
        provider = MediaWikiWikipediaProvider(http_client=http_client)

        results = provider.search("Albert Einstein", limit=3)

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
