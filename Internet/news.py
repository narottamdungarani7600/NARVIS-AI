"""News provider abstractions and live providers for the NARVIS Internet package."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from .requests import BaseHttpClient

_TAG_PATTERN = re.compile(r"<[^>]+>")
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_TOP_NEWS_ALIAS_TEXTS = {
    "latest",
    "latest news",
    "top",
    "top news",
    "headlines",
    "top headlines",
    "today top news",
    "today's top news",
    "todays top news",
}


def _normalize_text_value(value: Any) -> str:
    """Collapse internal whitespace in a text payload."""

    if value is None:
        return ""
    return " ".join(str(value).strip().split())


@dataclass(slots=True, frozen=True)
class NewsSourceDefinition:
    """Defines one canonical publisher name and its recognized aliases."""

    canonical_name: str
    aliases: tuple[str, ...]
    inline_aliases: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class NewsSourceMatch:
    """Represents one matched source alias inside free-form text."""

    canonical_name: str
    matched_text: str
    start: int
    end: int


_KNOWN_NEWS_SOURCES = (
    NewsSourceDefinition(
        canonical_name="Sandesh",
        aliases=("Sandesh", "sandesh news", "sandesh samachar", "સંદેશ"),
        inline_aliases=("Sandesh", "sandesh samachar", "સંદેશ"),
    ),
    NewsSourceDefinition(
        canonical_name="Divya Bhaskar",
        aliases=("Divya Bhaskar", "divyabhaskar", "divya bhaskar news", "દિવ્ય ભાસ્કર"),
        inline_aliases=("Divya Bhaskar", "divyabhaskar", "દિવ્ય ભાસ્કર"),
    ),
    NewsSourceDefinition(
        canonical_name="Aaj Tak",
        aliases=("Aaj Tak", "AajTak", "aaj tak news", "आज तक"),
        inline_aliases=("Aaj Tak", "AajTak", "आज तक"),
    ),
    NewsSourceDefinition(
        canonical_name="India Today",
        aliases=("India Today", "indiatoday", "india today news"),
        inline_aliases=("India Today", "indiatoday"),
    ),
)

_KNOWN_NEWS_SOURCE_LOOKUP = {
    _normalize_text_value(alias).casefold(): definition.canonical_name
    for definition in _KNOWN_NEWS_SOURCES
    for alias in definition.aliases
}
_KNOWN_NEWS_SOURCE_PATTERNS = tuple(
    (
        definition.canonical_name,
        _normalize_text_value(alias),
        re.compile(rf"(?<!\w){re.escape(_normalize_text_value(alias))}(?!\w)", re.IGNORECASE),
    )
    for definition in _KNOWN_NEWS_SOURCES
    for alias in sorted(definition.inline_aliases or definition.aliases, key=len, reverse=True)
)


def resolve_known_news_source(value: Any) -> str:
    """Return the canonical source name for one recognized alias."""

    normalized = _normalize_text_value(value).casefold()
    if not normalized:
        return ""
    return _KNOWN_NEWS_SOURCE_LOOKUP.get(normalized, "")


def canonicalize_news_source(value: Any) -> str:
    """Return a stable canonical source name while preserving unknown values."""

    normalized = _normalize_text_value(value)
    return resolve_known_news_source(normalized) or normalized


def find_known_news_source(text: Any) -> NewsSourceMatch | None:
    """Locate one known publisher alias inside free-form user text."""

    normalized = _normalize_text_value(text)
    if not normalized:
        return None

    best_match: NewsSourceMatch | None = None
    for canonical_name, alias_text, pattern in _KNOWN_NEWS_SOURCE_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        candidate = NewsSourceMatch(
            canonical_name=canonical_name,
            matched_text=alias_text,
            start=match.start(),
            end=match.end(),
        )
        if best_match is None:
            best_match = candidate
            continue
        current_length = best_match.end - best_match.start
        candidate_length = candidate.end - candidate.start
        if candidate.start < best_match.start or (candidate.start == best_match.start and candidate_length > current_length):
            best_match = candidate
    return best_match


def _detect_news_descriptor(value: str, *, request_type: str) -> str:
    """Resolve a stable trailing descriptor for structured news queries."""

    normalized = _normalize_text_value(value).lower()
    if "breaking" in normalized:
        return "breaking news"
    if "top" in normalized or "headline" in normalized:
        return "top news"
    if "latest" in normalized or request_type in {"latest", "top"}:
        return "latest news"
    return "news"


def _build_structured_news_query_text(request: NewsQuery, *, descriptor: str) -> str:
    """Build canonical search text for structured topic/location/source requests."""

    tokens: list[str] = []
    if request.topic:
        tokens.append(request.topic)
    if request.location:
        tokens.append(request.location)
    if request.source:
        tokens.append(request.source)
    if request.category and request.category.lower() not in {"top"}:
        tokens.append(request.category)
    tokens.append(descriptor or "news")
    return _join_unique_news_tokens(tokens)


def _canonicalize_news_query_text(request: NewsQuery, *, raw_query_text: str) -> str:
    """Build one stable canonical query text for cache keys and provider calls."""

    normalized_raw = _normalize_text_value(raw_query_text)
    if request.request_type == "latest" and not any((request.topic, request.location, request.source)):
        return "latest news"
    if request.category.lower() == "world" and not any((request.topic, request.location, request.source)):
        return "world news"
    if request.topic or request.location or request.source or request.category:
        descriptor = _detect_news_descriptor(normalized_raw, request_type=request.request_type)
        return _build_structured_news_query_text(request, descriptor=descriptor)
    return normalized_raw or _build_news_query_text(request) or "latest news"


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


@dataclass(slots=True, frozen=True)
class NewsQuery:
    """Represents one normalized news request."""

    request_type: str = "latest"
    query_text: str = ""
    topic: str = ""
    location: str = ""
    source: str = ""
    category: str = ""


@dataclass(slots=True)
class NewsArticle:
    """Represents a single news article entry."""

    title: str
    url: str = ""
    summary: str = ""
    source: str = ""
    published_at: str = ""
    topic: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

def _join_unique_news_tokens(values: list[str]) -> str:
    """Join text tokens while preserving order and removing duplicates."""

    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text_value(value)
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(normalized)
    return " ".join(ordered)


def _build_news_query_text(request: NewsQuery) -> str:
    """Construct one Google News search string from a structured request."""

    if request.query_text:
        return request.query_text

    tokens: list[str] = []
    if request.topic:
        tokens.append(request.topic)
    if request.location:
        tokens.append(request.location)
    if request.source:
        tokens.append(request.source)
    if request.category and request.category.lower() not in {"top"}:
        tokens.append(request.category)
    if request.request_type in {"latest", "top"} or tokens:
        tokens.append("news")
    return _join_unique_news_tokens(tokens)


def _resolve_news_request_type(request: NewsQuery, *, query_text: str) -> str:
    """Determine whether the request should hit top stories or search feeds."""

    lowered_query = query_text.lower()
    if request.request_type in {"latest", "top"}:
        if request.topic or request.location or request.source:
            return "search"
        if request.category and request.category.lower() not in {"", "top"}:
            return "search"
        if lowered_query in {"", "latest news", "top news", "top headlines", "headlines"}:
            return "latest"
    return "search" if query_text or request.topic or request.location or request.source or request.category else "latest"


def normalize_news_request(topic: NewsQuery | str | None) -> NewsQuery:
    """Normalize a user news request into one canonical NewsQuery."""

    if isinstance(topic, NewsQuery):
        normalized_source = canonicalize_news_source(topic.source)
        normalized = NewsQuery(
            request_type=_normalize_text_value(topic.request_type).lower() or "latest",
            query_text=_normalize_text_value(topic.query_text),
            topic=_normalize_text_value(topic.topic),
            location=_normalize_text_value(topic.location),
            source=normalized_source,
            category=_normalize_text_value(topic.category),
        )
        query_text = _canonicalize_news_query_text(normalized, raw_query_text=topic.query_text)
        request_type = _resolve_news_request_type(normalized, query_text=query_text)
        if request_type == "latest":
            return NewsQuery(request_type="latest", query_text="latest news", category="top")
        return NewsQuery(
            request_type=request_type,
            query_text=query_text or "latest news",
            topic=normalized.topic,
            location=normalized.location,
            source=normalized.source,
            category=normalized.category,
        )

    normalized_text = _normalize_text_value(topic or "")
    lowered = normalized_text.lower()
    resolved_source = resolve_known_news_source(normalized_text)
    if resolved_source:
        return NewsQuery(request_type="search", query_text=f"{resolved_source} news", source=resolved_source)
    if not lowered or lowered in _TOP_NEWS_ALIAS_TEXTS:
        return NewsQuery(request_type="latest", query_text="latest news", category="top")
    if lowered in {"world news", "global news"}:
        return NewsQuery(request_type="search", query_text="world news", category="world")
    if "news" in lowered:
        return NewsQuery(request_type="search", query_text=normalized_text, topic=normalized_text)
    return NewsQuery(request_type="search", query_text=f"{normalized_text} news", topic=normalized_text)


class NewsProvider(Protocol):
    """Protocol for news provider services."""

    def fetch(self, topic: NewsQuery | str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Fetch news articles for a topic or structured news request."""


class BaseNewsProvider(ABC):
    """Abstract base class for news provider implementations."""

    @abstractmethod
    def fetch(self, topic: NewsQuery | str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Fetch news articles for a topic or structured news request."""


class GoogleNewsRssProvider(BaseNewsProvider):
    """Live news provider backed by Google News RSS search and top-story feeds."""

    def __init__(
        self,
        *,
        http_client: BaseHttpClient,
        timeout_seconds: float = 6.0,
        top_feed_endpoint: str = "https://news.google.com/rss",
        search_feed_endpoint: str = "https://news.google.com/rss/search",
        language: str = "en",
        region: str = "IN",
        logger: Any | None = None,
    ) -> None:
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds
        self.top_feed_endpoint = top_feed_endpoint
        self.search_feed_endpoint = search_feed_endpoint
        self.language = self._normalize_text(language) or "en"
        self.region = self._normalize_text(region).upper() or "IN"
        self.logger = logger

    def fetch(self, topic: NewsQuery | str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Fetch live news from Google News RSS feeds."""

        request = self._normalize_request(topic)
        bounded_limit = self._bound_limit(limit)
        url = self._build_feed_url(request)
        feed_text = self._request_feed_text(url)
        if feed_text is None:
            return []
        return self._parse_feed(feed_text, request, bounded_limit)

    def _normalize_request(self, topic: NewsQuery | str | None) -> NewsQuery:
        """Normalize either a simple topic string or a structured request."""

        return normalize_news_request(topic)

    def _resolve_request_type(self, request: NewsQuery, *, query_text: str) -> str:
        """Determine whether the request should hit top stories or search feeds."""

        lowered_query = query_text.lower()
        if request.request_type in {"latest", "top"}:
            if request.topic or request.location or request.source:
                return "search"
            if request.category and request.category.lower() not in {"", "top"}:
                return "search"
            if lowered_query in {"", "latest news", "top news", "top headlines", "headlines"}:
                return "latest"
        return "search" if query_text or request.topic or request.location or request.source or request.category else "latest"

    def _build_query_text(self, request: NewsQuery) -> str:
        """Construct one Google News search string from a structured request."""

        if request.query_text:
            return request.query_text

        tokens: list[str] = []
        if request.topic:
            tokens.append(request.topic)
        if request.location:
            tokens.append(request.location)
        if request.source:
            tokens.append(request.source)
        if request.category and request.category.lower() not in {"top"}:
            tokens.append(request.category)
        if request.request_type in {"latest", "top"} or tokens:
            tokens.append("news")
        return self._join_unique_tokens(tokens)

    def _build_feed_url(self, request: NewsQuery) -> str:
        """Build the Google News RSS URL for the normalized request."""

        params = {
            "hl": f"{self.language}-{self.region}",
            "gl": self.region,
            "ceid": f"{self.region}:{self.language}",
        }
        if request.request_type == "latest":
            return self._build_url(self.top_feed_endpoint, params)

        search_query = request.query_text or self._build_query_text(request)
        params["q"] = search_query or "latest news"
        return self._build_url(self.search_feed_endpoint, params)

    def _request_feed_text(self, url: str) -> str | None:
        """Perform one feed request and return the XML payload text when valid."""

        try:
            response = self.http_client.get(
                url,
                headers={
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
                },
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            _emit_log(self.logger, "warning", "News feed request raised an exception", url=url, error=str(exc))
            return None

        if not isinstance(response, dict):
            _emit_log(self.logger, "warning", "News feed request returned a non-dict response", url=url)
            return None

        status = response.get("status")
        if not isinstance(status, int) or status < 200 or status >= 300:
            _emit_log(self.logger, "warning", "News feed request failed", url=url, status=status, error=response.get("error"))
            return None

        payload = response.get("text")
        if not isinstance(payload, str) or not payload.strip():
            _emit_log(self.logger, "warning", "News feed request returned malformed XML text", url=url)
            return None
        return payload

    def _parse_feed(self, feed_text: str, request: NewsQuery, limit: int) -> list[NewsArticle]:
        """Parse either an RSS or Atom feed into normalized news articles."""

        try:
            root = ET.fromstring(feed_text)
        except ET.ParseError as exc:
            _emit_log(self.logger, "warning", "News feed XML parsing failed", error=str(exc))
            return []

        local_name = self._local_name(root.tag)
        if local_name == "feed":
            return self._finalize_articles(self._parse_atom_feed(root, request), request, limit)

        channel = root.find("channel") if local_name == "rss" else root if local_name == "channel" else None
        if channel is None:
            _emit_log(self.logger, "warning", "News feed payload missing RSS channel", root_tag=local_name)
            return []
        return self._finalize_articles(self._parse_rss_channel(channel, request), request, limit)

    def _parse_rss_channel(self, channel: ET.Element, request: NewsQuery) -> list[NewsArticle]:
        """Normalize one RSS channel into ordered news articles."""

        results: list[NewsArticle] = []
        for rank, item in enumerate(channel.findall("item"), start=1):
            article = self._parse_rss_item(item, rank, request)
            if article is None:
                continue
            results.append(article)
        return results

    def _parse_rss_item(self, item: ET.Element, rank: int, request: NewsQuery) -> NewsArticle | None:
        """Normalize one RSS item safely."""

        title = self._normalize_text(item.findtext("title") or "")
        if not title:
            return None

        link = self._normalize_text(item.findtext("link") or "")
        summary = self._clean_summary(item.findtext("description"))
        if summary == title:
            summary = ""

        source_element = item.find("source")
        source = self._normalize_text(source_element.text if source_element is not None and source_element.text else "")
        source_url = ""
        if source_element is not None:
            source_url = self._normalize_text(source_element.attrib.get("url", ""))

        topic = self._normalize_text(item.findtext("category") or "") or request.topic or request.category
        metadata = self._build_metadata(request, rank)
        if source_url:
            metadata["source_url"] = source_url

        return NewsArticle(
            title=title,
            url=link,
            summary=summary,
            source=source,
            published_at=self._normalize_datetime(item.findtext("pubDate")),
            topic=topic,
            metadata=metadata,
        )

    def _parse_atom_feed(self, root: ET.Element, request: NewsQuery) -> list[NewsArticle]:
        """Normalize one Atom feed into ordered news articles."""

        results: list[NewsArticle] = []
        for rank, entry in enumerate((child for child in root if self._local_name(child.tag) == "entry"), start=1):
            article = self._parse_atom_entry(entry, rank, request)
            if article is None:
                continue
            results.append(article)
        return results

    def _parse_atom_entry(self, entry: ET.Element, rank: int, request: NewsQuery) -> NewsArticle | None:
        """Normalize one Atom entry safely."""

        title = self._child_text(entry, "title")
        if not title:
            return None

        summary = self._clean_summary(self._child_text(entry, "summary") or self._child_text(entry, "content"))
        if summary == title:
            summary = ""

        source = ""
        source_url = ""
        topic = request.topic or request.category
        for child in entry:
            local_name = self._local_name(child.tag)
            if local_name == "category":
                topic = self._normalize_text(child.attrib.get("term", "")) or topic
            elif local_name == "source":
                source = self._child_text(child, "title") or source
                source_url = self._child_text(child, "id") or source_url

        metadata = self._build_metadata(request, rank)
        if source_url:
            metadata["source_url"] = source_url

        return NewsArticle(
            title=title,
            url=self._entry_link(entry),
            summary=summary,
            source=source,
            published_at=self._normalize_datetime(self._child_text(entry, "published") or self._child_text(entry, "updated")),
            topic=topic,
            metadata=metadata,
        )

    def _entry_link(self, entry: ET.Element) -> str:
        """Resolve the primary link from an Atom entry."""

        for child in entry:
            if self._local_name(child.tag) != "link":
                continue
            relation = self._normalize_text(child.attrib.get("rel", "alternate")).lower()
            href = self._normalize_text(child.attrib.get("href", ""))
            if href and relation in {"alternate", ""}:
                return href
        return ""

    def _build_metadata(self, request: NewsQuery, rank: int) -> dict[str, Any]:
        """Build compact metadata without retaining raw provider payloads."""

        metadata = {
            "provider": "google-news-rss",
            "rank": rank,
            "request_type": request.request_type,
        }
        if request.query_text:
            metadata["requested_query"] = request.query_text
        if request.topic:
            metadata["requested_topic"] = request.topic
        if request.location:
            metadata["requested_location"] = request.location
        if request.source:
            metadata["requested_source"] = request.source
        if request.category:
            metadata["requested_category"] = request.category
        return metadata

    def _finalize_articles(self, articles: list[NewsArticle], request: NewsQuery, limit: int) -> list[NewsArticle]:
        """Apply conservative structured-request validation before truncating results."""

        filtered = self._filter_articles_for_request(articles, request)
        return filtered[:limit]

    def _filter_articles_for_request(self, articles: list[NewsArticle], request: NewsQuery) -> list[NewsArticle]:
        """Filter source-aware requests conservatively without broadening the backend."""

        if not request.source:
            return articles

        source_filtered = [article for article in articles if self._article_matches_requested_source(article, request.source)]
        if not source_filtered:
            return []
        if not request.topic:
            return source_filtered
        return [article for article in source_filtered if self._article_matches_requested_topic(article, request.topic)]

    def _article_matches_requested_source(self, article: NewsArticle, requested_source: str) -> bool:
        """Return whether one parsed article publisher matches the canonical requested source."""

        source_text = self._normalize_text(getattr(article, "source", "") or "")
        if not source_text or not requested_source:
            return False

        if canonicalize_news_source(source_text) == requested_source:
            return True

        source_match = find_known_news_source(source_text)
        if source_match is not None and source_match.canonical_name == requested_source:
            return True

        escaped_source = re.escape(requested_source)
        return re.search(rf"(?<!\w){escaped_source}(?!\w)", source_text, re.IGNORECASE) is not None

    def _article_matches_requested_topic(self, article: NewsArticle, requested_topic: str) -> bool:
        """Return whether one source-matched article still looks topic-relevant."""

        normalized_topic = self._normalize_relevance_text(requested_topic)
        if not normalized_topic:
            return True

        haystack = self._normalize_relevance_text(
            " ".join(
                part
                for part in (
                    getattr(article, "title", ""),
                    getattr(article, "summary", ""),
                    getattr(article, "topic", ""),
                )
                if part
            )
        )
        if not haystack:
            return False

        escaped_topic = re.escape(normalized_topic)
        if re.search(rf"(?<!\w){escaped_topic}(?!\w)", haystack, re.IGNORECASE) is not None:
            return True

        topic_tokens = [token for token in _WORD_PATTERN.findall(normalized_topic.casefold()) if len(token) >= 3]
        if not topic_tokens:
            return False
        haystack_tokens = set(_WORD_PATTERN.findall(haystack.casefold()))
        return all(token in haystack_tokens for token in topic_tokens)

    def _normalize_relevance_text(self, value: Any) -> str:
        """Normalize text for conservative source/topic relevance checks."""

        normalized = self._normalize_text(value)
        if not normalized:
            return ""
        return " ".join(_WORD_PATTERN.findall(normalized.casefold()))

    def _build_url(self, endpoint: str, params: dict[str, str]) -> str:
        """Build a query URL against the configured feed endpoint."""

        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{urlencode(params)}"

    def _bound_limit(self, limit: int) -> int:
        """Clamp the requested result count to a safe feed size."""

        return min(max(int(limit), 1), 20)

    def _normalize_datetime(self, value: str) -> str:
        """Normalize RSS or Atom timestamps into compact ISO 8601 strings."""

        normalized = self._normalize_text(value)
        if not normalized:
            return ""
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        try:
            parsed = parsed or parsedate_to_datetime(normalized)
        except (TypeError, ValueError, IndexError, OverflowError):
            parsed = None
        if parsed is None:
            try:
                parsed = parsedate_to_datetime(normalized.replace("Z", "+0000"))
            except (TypeError, ValueError, IndexError, OverflowError):
                parsed = None
        if parsed is None:
            try:
                parsed = parsedate_to_datetime(normalized.replace("Z", " GMT"))
            except (TypeError, ValueError, IndexError, OverflowError):
                parsed = None
        if parsed is None:
            return normalized
        if parsed.tzinfo is None:
            return parsed.isoformat()
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _clean_summary(self, value: str | None) -> str:
        """Strip markup from RSS or Atom summary text."""

        normalized = _TAG_PATTERN.sub(" ", html.unescape(value or ""))
        return self._normalize_text(normalized)

    def _child_text(self, element: ET.Element, name: str) -> str:
        """Return one normalized child text value by local element name."""

        for child in element:
            if self._local_name(child.tag) == name:
                return self._normalize_text("".join(child.itertext()))
        return ""

    def _local_name(self, tag: str) -> str:
        """Resolve an XML element local name without namespace noise."""

        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    def _join_unique_tokens(self, values: list[str]) -> str:
        """Join text tokens while preserving order and removing duplicates."""

        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize_text(value)
            lowered = normalized.lower()
            if not normalized or lowered in seen:
                continue
            seen.add(lowered)
            ordered.append(normalized)
        return " ".join(ordered)

    def _normalize_text(self, value: Any) -> str:
        """Collapse internal whitespace in a text payload."""

        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class NullNewsProvider(BaseNewsProvider):
    """No-op news provider used as a placeholder implementation."""

    def fetch(self, topic: NewsQuery | str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Return an empty article list."""

        return []


__all__ = [
    "BaseNewsProvider",
    "GoogleNewsRssProvider",
    "NewsSourceDefinition",
    "NewsSourceMatch",
    "NewsArticle",
    "NewsProvider",
    "NewsQuery",
    "NullNewsProvider",
    "canonicalize_news_source",
    "find_known_news_source",
    "resolve_known_news_source",
]
