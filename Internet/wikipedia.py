"""Wikipedia search abstractions and providers for the NARVIS Internet package."""

from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlencode
from typing import Any, Protocol

from .requests import BaseHttpClient

_TAG_PATTERN = re.compile(r"<[^>]+>")


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message through either the Core logger or stdlib logging."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


@dataclass(slots=True)
class WikipediaResult:
    """Represents a single Wikipedia search result."""

    title: str
    summary: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class WikipediaProvider(Protocol):
    """Protocol for Wikipedia search providers."""

    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Search Wikipedia content for the provided query."""


class BaseWikipediaProvider(ABC):
    """Abstract base class for Wikipedia provider implementations."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Search Wikipedia content for the provided query."""


@dataclass(slots=True, frozen=True)
class _WikipediaSearchHit:
    """Represents one normalized search hit from the MediaWiki search API."""

    page_id: int
    title: str
    snippet: str
    timestamp: str = ""


class MediaWikiWikipediaProvider(BaseWikipediaProvider):
    """Wikipedia provider backed by the MediaWiki Action API."""

    def __init__(
        self,
        *,
        http_client: BaseHttpClient,
        timeout_seconds: float = 6.0,
        api_endpoint: str = "https://en.wikipedia.org/w/api.php",
        logger: Any | None = None,
    ) -> None:
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds
        self.api_endpoint = api_endpoint
        self.logger = logger

    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Search English Wikipedia using the official MediaWiki Action API."""

        normalized_query = self._normalize_query(query)
        bounded_limit = self._bound_limit(limit)
        if not normalized_query:
            return []

        search_hits = self._search_hits(normalized_query, bounded_limit)
        if not search_hits:
            return []

        pages_by_id = self._page_details(search_hits)
        if pages_by_id is None:
            return []

        results: list[WikipediaResult] = []
        for index, hit in enumerate(search_hits, start=1):
            page = pages_by_id.get(str(hit.page_id), {})
            if not isinstance(page, dict):
                page = {}
            title = self._coerce_text(page.get("title")) or hit.title
            summary = self._coerce_text(page.get("extract")) or hit.snippet
            url = self._coerce_text(page.get("canonicalurl")) or self._coerce_text(page.get("fullurl"))
            results.append(
                WikipediaResult(
                    title=title,
                    summary=self._normalize_text(summary),
                    url=url,
                    metadata={
                        "pageid": hit.page_id,
                        "rank": index,
                        "search_snippet": hit.snippet,
                        "timestamp": hit.timestamp,
                    },
                )
            )
        return results

    def _search_hits(self, query: str, limit: int) -> list[_WikipediaSearchHit]:
        """Run the search stage and normalize ordered hits."""

        payload = self._request_json(
            {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": query,
                "srlimit": str(limit),
                "utf8": "1",
            }
        )
        if payload is None:
            return []

        query_payload = payload.get("query")
        if not isinstance(query_payload, dict):
            _emit_log(self.logger, "warning", "Wikipedia search payload missing query object", query=query)
            return []

        raw_hits = query_payload.get("search")
        if not isinstance(raw_hits, list):
            _emit_log(self.logger, "warning", "Wikipedia search payload missing search hits", query=query)
            return []

        hits: list[_WikipediaSearchHit] = []
        for item in raw_hits:
            if not isinstance(item, dict):
                _emit_log(self.logger, "warning", "Wikipedia search hit had invalid shape", query=query)
                return []
            page_id = item.get("pageid")
            title = self._coerce_text(item.get("title"))
            if not isinstance(page_id, int) or not title:
                _emit_log(self.logger, "warning", "Wikipedia search hit missing required fields", query=query)
                return []
            hits.append(
                _WikipediaSearchHit(
                    page_id=page_id,
                    title=title,
                    snippet=self._clean_search_snippet(item.get("snippet")),
                    timestamp=self._coerce_text(item.get("timestamp")),
                )
            )
        return hits

    def _page_details(self, hits: list[_WikipediaSearchHit]) -> dict[str, dict[str, Any]] | None:
        """Run the detail stage for the ordered set of search hits."""

        page_ids = "|".join(str(hit.page_id) for hit in hits)
        payload = self._request_json(
            {
                "action": "query",
                "format": "json",
                "prop": "extracts|info",
                "pageids": page_ids,
                "exintro": "1",
                "explaintext": "1",
                "exsentences": "2",
                "inprop": "url",
            }
        )
        if payload is None:
            return None

        query_payload = payload.get("query")
        if not isinstance(query_payload, dict):
            _emit_log(self.logger, "warning", "Wikipedia detail payload missing query object", page_ids=page_ids)
            return None

        raw_pages = query_payload.get("pages")
        if not isinstance(raw_pages, dict):
            _emit_log(self.logger, "warning", "Wikipedia detail payload missing pages mapping", page_ids=page_ids)
            return None

        pages: dict[str, dict[str, Any]] = {}
        for page_id, page_payload in raw_pages.items():
            if isinstance(page_payload, dict):
                pages[str(page_id)] = page_payload
        return pages

    def _request_json(self, params: dict[str, str]) -> dict[str, Any] | None:
        """Perform one MediaWiki GET request and validate the JSON payload."""

        url = self._build_url(params)
        try:
            response = self.http_client.get(url, timeout=self.timeout_seconds)
        except Exception as exc:
            _emit_log(self.logger, "warning", "Wikipedia request raised an exception", url=url, error=str(exc))
            return None

        if not isinstance(response, dict):
            _emit_log(self.logger, "warning", "Wikipedia request returned a non-dict response", url=url)
            return None

        status = response.get("status")
        if not isinstance(status, int) or status < 200 or status >= 300:
            _emit_log(
                self.logger,
                "warning",
                "Wikipedia request failed",
                url=url,
                status=status,
                error=response.get("error"),
            )
            return None

        payload = response.get("json")
        if not isinstance(payload, dict):
            _emit_log(self.logger, "warning", "Wikipedia request returned malformed JSON", url=url)
            return None
        return payload

    def _build_url(self, params: dict[str, str]) -> str:
        """Build a query URL against the configured MediaWiki endpoint."""

        separator = "&" if "?" in self.api_endpoint else "?"
        return f"{self.api_endpoint}{separator}{urlencode(params)}"

    def _bound_limit(self, limit: int) -> int:
        """Clamp the requested result count to a safe anonymous-search size."""

        return min(max(int(limit), 1), 10)

    def _normalize_query(self, query: str) -> str:
        """Normalize query whitespace before sending it to MediaWiki."""

        return self._normalize_text(query)

    def _clean_search_snippet(self, value: Any) -> str:
        """Strip MediaWiki snippet markup while preserving readable text."""

        return self._normalize_text(_TAG_PATTERN.sub("", html.unescape(self._coerce_text(value))))

    def _normalize_text(self, value: str) -> str:
        """Collapse internal whitespace in a text payload."""

        return " ".join(str(value).strip().split())

    def _coerce_text(self, value: Any) -> str:
        """Return a safe string representation for optional text fields."""

        return value.strip() if isinstance(value, str) else ""


class NullWikipediaProvider(BaseWikipediaProvider):
    """No-op Wikipedia provider used as a placeholder implementation."""

    def search(self, query: str, limit: int = 10) -> list[WikipediaResult]:
        """Return an empty result list."""
        return []


__all__ = [
    "BaseWikipediaProvider",
    "MediaWikiWikipediaProvider",
    "NullWikipediaProvider",
    "WikipediaProvider",
    "WikipediaResult",
]
