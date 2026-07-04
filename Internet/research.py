"""Grounded web-research services for the NARVIS Internet package."""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib import error, request

from .safety import HostResolver, UnsafeUrlError, extract_domain, normalize_public_url
from .search import (
    BaseSearchProvider,
    SearchProviderDiagnostic,
    SearchProviderError,
    SearchResult,
    execute_search,
)

_QUESTION_WORDS = ("who", "what", "when", "where", "why", "how", "which")
_FRESHNESS_TERMS = ("latest", "current", "today", "recent", "news")
_AMBIGUITY_PATTERN = re.compile(r"\b(?:is|are|was|were)\s+(?:an?|the)\s+([^.;:\n]{10,90})", re.IGNORECASE)
_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4}|[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})\b"
)


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

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
class ResearchQuery:
    """Normalized intent extracted from a user internet-research request."""

    original_text: str
    topic: str
    search_text: str
    freshness_terms: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""


@dataclass(slots=True, frozen=True)
class ResearchSource:
    """One source shown in a grounded research response."""

    title: str
    url: str
    domain: str


@dataclass(slots=True)
class ExtractedContent:
    """Readable content extracted from a fetched public page."""

    title: str = ""
    text: str = ""
    excerpt: str = ""


@dataclass(slots=True)
class FetchedPage:
    """Represents the outcome of one bounded page-fetch attempt."""

    url: str
    final_url: str
    content_type: str = ""
    status_code: int | None = None
    success: bool = False
    title: str = ""
    text: str = ""
    excerpt: str = ""
    error: str | None = None


@dataclass(slots=True)
class GroundedResearchResponse:
    """Grounded answer plus the evidence and source list used to support it."""

    query: ResearchQuery
    answer: str
    sources: tuple[ResearchSource, ...]
    provider_name: str
    search_result_count: int
    pages_read_count: int
    evidence_summary: tuple[str, ...] = ()
    ambiguous: bool = False
    follow_up_question: str | None = None
    error: str | None = None
    search_status: str = "results"
    search_provider_name: str = ""
    search_diagnostics: tuple[SearchProviderDiagnostic, ...] = ()

    def render_message(self) -> str:
        """Render a human-readable research answer for the runtime skill path."""

        lines = [f"Research summary for '{self.query.topic}':", self.answer]
        if self.follow_up_question:
            lines.extend(("", self.follow_up_question))
        if self.sources:
            lines.extend(("", "Sources:"))
            for index, source in enumerate(self.sources, start=1):
                lines.append(f"{index}. {source.title} - {source.url}")
        return "\n".join(lines)


class ResearchSynthesizer(Protocol):
    """Protocol for grounded answer synthesis implementations."""

    def synthesize(
        self,
        query: ResearchQuery,
        search_results: list[SearchResult],
        pages: list[FetchedPage],
        *,
        error: str | None = None,
        search_status: str = "results",
        search_provider_name: str = "",
        search_diagnostics: tuple[SearchProviderDiagnostic, ...] = (),
    ) -> GroundedResearchResponse:
        """Build a grounded response from collected evidence."""


class InternetResearchIntentParser:
    """Detect and normalize internet-research commands from natural language."""

    _EXPLICIT_PATTERNS: tuple[tuple[re.Pattern[str], float, str], ...] = (
        (re.compile(r"^search\s+(?:the\s+)?(?:internet|web)\s+for\s+(?P<query>.+)$", re.IGNORECASE), 0.97, "explicit search-web command"),
        (re.compile(r"^search\s+(?P<query>.+)$", re.IGNORECASE), 0.78, "generic search command"),
        (
            re.compile(
                r"^(?:(?:internet|web|google)(?:\s+(?:me|par|se))?\s+search\s+karo|online\s+search\s+karo)\s+(?P<query>.+)$",
                re.IGNORECASE,
            ),
            0.97,
            "explicit internet-search command",
        ),
        (
            re.compile(r"^(?:internet|web|google)\s+se\s+pata\s+karo\s+(?P<query>.+)$", re.IGNORECASE),
            0.96,
            "explicit web-research command",
        ),
        (
            re.compile(r"^(?:online|internet|web)\s+research\s+karo\s+(?P<query>.+)$", re.IGNORECASE),
            0.94,
            "explicit research command",
        ),
        (
            re.compile(r"^research\s+(?P<query>.+?)\s+(?:on|from)\s+the\s+web(?:\s+and\s+summarize\s+it)?$", re.IGNORECASE),
            0.93,
            "explicit web research request",
        ),
        (re.compile(r"^(?:latest|recent)\s+news\s+about\s+(?P<query>.+)$", re.IGNORECASE), 0.9, "fresh news request"),
        (re.compile(r"^current\s+information\s+about\s+(?P<query>.+)$", re.IGNORECASE), 0.9, "current-information request"),
    )

    def parse(self, text: str) -> ResearchQuery | None:
        """Return a structured research query when the request targets the web."""

        normalized_text = " ".join(str(text).strip().split())
        if not normalized_text:
            return None
        lowered = normalized_text.lower()
        if lowered.startswith("search memory for "):
            return None
        if self._looks_like_desktop_open(lowered):
            return None

        for pattern, confidence, reason in self._EXPLICIT_PATTERNS:
            match = pattern.match(normalized_text)
            if match is None:
                continue
            topic = self._cleanup_query(match.group("query"))
            if topic:
                return self._build_query(normalized_text, topic, confidence=confidence, reason=reason)

        if "search the internet" in lowered or "search the web" in lowered:
            candidate = re.sub(r"(?i)\bsearch\s+the\s+(?:internet|web)\b", "", normalized_text).strip(" .?!")
            topic = self._cleanup_query(candidate)
            if topic:
                return self._build_query(normalized_text, topic, confidence=0.87, reason="embedded search-web request")

        if any(term in lowered for term in ("latest news about ", "current information about ", "recent news about ")):
            for prefix in ("latest news about ", "recent news about ", "current information about "):
                if lowered.startswith(prefix):
                    topic = self._cleanup_query(normalized_text[len(prefix) :])
                    if topic:
                        return self._build_query(normalized_text, topic, confidence=0.9, reason="freshness-driven web request")

        return None

    def _build_query(self, original_text: str, topic: str, *, confidence: float, reason: str) -> ResearchQuery:
        """Create the final normalized query object from an extracted topic."""

        freshness_terms = tuple(term for term in _FRESHNESS_TERMS if term in original_text.lower())
        search_text = self._build_search_text(topic, freshness_terms)
        return ResearchQuery(
            original_text=original_text,
            topic=topic,
            search_text=search_text,
            freshness_terms=freshness_terms,
            confidence=confidence,
            reason=reason,
        )

    def _build_search_text(self, topic: str, freshness_terms: tuple[str, ...]) -> str:
        """Preserve freshness intent without polluting simple entity lookups."""

        lowered = topic.lower()
        if lowered.startswith(_QUESTION_WORDS):
            return topic

        suffix_parts: list[str] = []
        if any(term in freshness_terms for term in ("latest", "recent", "today")):
            suffix_parts.append("latest")
        if "news" in freshness_terms:
            suffix_parts.append("news")
        elif "current" in freshness_terms:
            suffix_parts.append("current information")
        if not suffix_parts:
            return topic
        return f"{topic} {' '.join(dict.fromkeys(suffix_parts))}".strip()

    def _cleanup_query(self, raw_query: str) -> str:
        """Trim filler phrasing while preserving the actual research topic."""

        candidate = " ".join(raw_query.strip().split())
        if not candidate:
            return ""

        for pattern in (
            r"\s+aur\s+mujhe\s+batao.*$",
            r"\s+mujhe\s+batao.*$",
            r"\s+(?:and\s+)?tell\s+me.*$",
            r"\s+batao.*$",
            r"\s+please\s*$",
            r"\s+ke\s+baare\s+me\s*$",
            r"\s+ke\s+bare\s+me\s*$",
            r"\s+naam\s+se\s+kya\s+kya\s+hai.*$",
            r"\s+naam\s+se\s+kya\s+hai.*$",
            r"\s+kya\s+kya\s+hai.*$",
            r"\s+kya\s+hai.*$",
        ):
            candidate = re.sub(pattern, "", candidate, flags=re.IGNORECASE).strip()
        return candidate.strip(" '\"`.,?!")

    def _looks_like_desktop_open(self, lowered_text: str) -> bool:
        """Avoid stealing the existing Universal Open-style desktop commands."""

        return lowered_text.startswith(("open ", "launch ", "close ", "start ")) or lowered_text.endswith(" kholo")


class SafePageFetcher:
    """Fetch public HTTP(S) pages with strict safety and size limits."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 6.0,
        max_response_bytes: int = 250_000,
        max_redirects: int = 3,
        user_agent: str = "NARVIS/1.1 (grounded web research; no-js)",
        resolver: HostResolver | None = None,
        opener_factory: Callable[[request.BaseHandler], Any] | None = None,
        extractor: "HtmlContentExtractor | None" = None,
        logger: Any | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.resolver = resolver
        self.opener_factory = opener_factory
        self.extractor = extractor or HtmlContentExtractor()
        self.logger = logger

    def fetch(self, url: str) -> FetchedPage:
        """Fetch one URL and return extracted readable content or a bounded failure."""

        try:
            safe_url = normalize_public_url(url, resolve_host=True, resolver=self.resolver)
        except UnsafeUrlError as exc:
            return FetchedPage(url=url, final_url=url, error=str(exc), success=False)

        redirect_handler = _SafeRedirectHandler(
            validator=lambda target: normalize_public_url(target, resolve_host=True, resolver=self.resolver),
            max_redirects=self.max_redirects,
        )
        opener = self.opener_factory(redirect_handler) if self.opener_factory is not None else request.build_opener(redirect_handler)
        req = request.Request(
            safe_url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,text/plain"},
            method="GET",
        )
        try:
            with opener.open(req, timeout=self.timeout_seconds) as response:
                final_url = normalize_public_url(response.geturl(), resolve_host=True, resolver=self.resolver)
                content_type = response.headers.get_content_type().lower()
                if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    return FetchedPage(
                        url=safe_url,
                        final_url=final_url,
                        content_type=content_type,
                        status_code=getattr(response, "status", None),
                        success=False,
                        error=f"unsupported content type: {content_type}",
                    )

                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_response_bytes:
                    return FetchedPage(
                        url=safe_url,
                        final_url=final_url,
                        content_type=content_type,
                        status_code=getattr(response, "status", None),
                        success=False,
                        error="response exceeded the configured size limit",
                    )

                payload = response.read(self.max_response_bytes + 1)
                if len(payload) > self.max_response_bytes:
                    return FetchedPage(
                        url=safe_url,
                        final_url=final_url,
                        content_type=content_type,
                        status_code=getattr(response, "status", None),
                        success=False,
                        error="response exceeded the configured size limit",
                    )

                charset = response.headers.get_content_charset("utf-8")
                text = payload.decode(charset, errors="replace")
                extracted = self.extractor.extract(text, content_type=content_type)
                return FetchedPage(
                    url=safe_url,
                    final_url=final_url,
                    content_type=content_type,
                    status_code=getattr(response, "status", None),
                    success=bool(extracted.text or extracted.title),
                    title=extracted.title,
                    text=extracted.text,
                    excerpt=extracted.excerpt,
                    error=None if (extracted.text or extracted.title) else "no readable text extracted",
                )
        except UnsafeUrlError as exc:
            return FetchedPage(url=safe_url, final_url=safe_url, success=False, error=str(exc))
        except error.HTTPError as exc:
            return FetchedPage(url=safe_url, final_url=safe_url, success=False, status_code=exc.code, error=f"HTTP {exc.code}")
        except error.URLError as exc:
            return FetchedPage(url=safe_url, final_url=safe_url, success=False, error=str(getattr(exc, "reason", exc)))
        except OSError as exc:
            return FetchedPage(url=safe_url, final_url=safe_url, success=False, error=str(exc))


class HtmlContentExtractor:
    """Extract readable text from safe HTML and plain-text pages."""

    def __init__(self, *, max_chars: int = 6_000) -> None:
        self.max_chars = max_chars

    def extract(self, content: str, *, content_type: str = "text/html") -> ExtractedContent:
        """Extract readable text while removing scripts, styles, and common page chrome."""

        if content_type == "text/plain":
            text = _truncate_text(_normalize_whitespace(content), self.max_chars)
            return ExtractedContent(title="", text=text, excerpt=_first_excerpt(text))

        parser = _ReadableHtmlParser()
        parser.feed(content)
        parser.close()
        text = _truncate_text(_normalize_whitespace(" ".join(parser.text_chunks)), self.max_chars)
        title = _normalize_whitespace(parser.title_text)
        return ExtractedContent(title=title, text=text, excerpt=_first_excerpt(text or title))


class DeterministicResearchSynthesizer:
    """Build a grounded answer directly from search results and fetched evidence."""

    def __init__(self, *, logger: Any | None = None) -> None:
        self.logger = logger

    def synthesize(
        self,
        query: ResearchQuery,
        search_results: list[SearchResult],
        pages: list[FetchedPage],
        *,
        error: str | None = None,
        search_status: str = "results",
        search_provider_name: str = "",
        search_diagnostics: tuple[SearchProviderDiagnostic, ...] = (),
    ) -> GroundedResearchResponse:
        """Create a concise grounded answer without requiring an AI provider."""

        sources = self._dedupe_sources(search_results)
        readable_pages = [page for page in pages if page.success]
        evidence_lines = tuple(self._build_evidence_lines(search_results, readable_pages))

        if not search_results:
            if search_status == "zero_results":
                answer = f"I couldn't find public web results for '{query.topic}'."
            else:
                answer = (
                    f"I couldn't complete a live web search for '{query.topic}' because the available search providers "
                    "were unreachable or blocked."
                )
            return GroundedResearchResponse(
                query=query,
                answer=answer,
                sources=(),
                provider_name="deterministic-fallback",
                search_result_count=0,
                pages_read_count=0,
                error=error,
                search_status=search_status,
                search_provider_name=search_provider_name,
                search_diagnostics=search_diagnostics,
            )

        ambiguous_labels = self._detect_ambiguity(query, search_results, readable_pages)
        follow_up_question: str | None = None
        if ambiguous_labels:
            answer = (
                f"'{query.topic}' looks ambiguous in the web results. I found references to "
                f"{_join_with_commas(ambiguous_labels)}."
            )
            follow_up_question = "Which meaning do you want to explore further?"
        else:
            summary_sentences = self._collect_summary_sentences(query, search_results, readable_pages)
            if summary_sentences:
                answer = " ".join(summary_sentences[:2])
            else:
                answer = f"I found public web results about '{query.topic}', but there was not enough readable evidence to summarize confidently."

        if search_results and readable_pages and len(readable_pages) < min(3, len(search_results)):
            answer += " I could only read some of the linked pages directly, so this summary also relies on search-result snippets."
        elif search_results and not readable_pages:
            answer += " I could not read any linked pages directly, so this summary is based on search-result snippets only."

        if query.freshness_terms and not self._has_dated_evidence(search_results, readable_pages):
            answer += " Freshness note: I found relevant web results, but I could not verify exact publication dates from every source."

        return GroundedResearchResponse(
            query=query,
            answer=answer,
            sources=tuple(sources),
            provider_name="deterministic-fallback",
            search_result_count=len(search_results),
            pages_read_count=len(readable_pages),
            evidence_summary=evidence_lines,
            ambiguous=bool(ambiguous_labels),
            follow_up_question=follow_up_question,
            error=error,
            search_status=search_status,
            search_provider_name=search_provider_name,
            search_diagnostics=search_diagnostics,
        )

    def _dedupe_sources(self, search_results: list[SearchResult]) -> list[ResearchSource]:
        """Return one deduplicated source list suitable for user display."""

        sources: list[ResearchSource] = []
        seen_urls: set[str] = set()
        for result in search_results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            sources.append(ResearchSource(title=result.title, url=result.url, domain=result.source or extract_domain(result.url)))
        return sources[:5]

    def _build_evidence_lines(self, search_results: list[SearchResult], pages: list[FetchedPage]) -> list[str]:
        """Create short evidence notes retained for future follow-up handling."""

        lines: list[str] = []
        for result in search_results[:3]:
            if result.snippet:
                lines.append(f"{result.title}: {result.snippet}")
        for page in pages[:2]:
            if page.excerpt:
                lines.append(f"{page.title or page.final_url}: {page.excerpt}")
        return lines[:4]

    def _detect_ambiguity(
        self,
        query: ResearchQuery,
        search_results: list[SearchResult],
        pages: list[FetchedPage],
    ) -> list[str]:
        """Detect whether the collected evidence points to multiple distinct meanings."""

        if len(query.topic.split()) > 3:
            return []

        candidates: list[str] = []
        for result in search_results[:5]:
            candidate = self._definition_candidate(result.snippet) or self._title_candidate(query.topic, result.title)
            if candidate:
                candidates.append(candidate)
        for page in pages[:3]:
            candidate = self._definition_candidate(page.excerpt or page.text[:240]) or self._title_candidate(query.topic, page.title)
            if candidate:
                candidates.append(candidate)

        unique: list[str] = []
        seen_keys: set[str] = set()
        for candidate in candidates:
            key = re.sub(r"[^a-z0-9]+", " ", candidate.lower()).strip()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            unique.append(candidate)
        return unique[:3] if len(unique) >= 2 else []

    def _definition_candidate(self, text: str) -> str | None:
        """Extract a human-readable definition phrase from one evidence block."""

        match = _AMBIGUITY_PATTERN.search(text or "")
        if match is None:
            return None
        candidate = match.group(1).strip(" .,:;")
        candidate = candidate.split(" which ")[0].split(" that ")[0].split(" with ")[0].strip()
        words = candidate.split()
        if len(words) < 3:
            return None
        return " ".join(words[:8])

    def _title_candidate(self, topic: str, title: str) -> str | None:
        """Extract a distinguishing title segment when it differs from the query itself."""

        if not title:
            return None
        head = re.split(r"\s+[|\-:]\s+", title, maxsplit=1)[0].strip()
        normalized_head = re.sub(r"[^a-z0-9]+", " ", head.lower()).strip()
        normalized_topic = re.sub(r"[^a-z0-9]+", " ", topic.lower()).strip()
        if not normalized_head or normalized_head == normalized_topic:
            return None
        return head

    def _collect_summary_sentences(
        self,
        query: ResearchQuery,
        search_results: list[SearchResult],
        pages: list[FetchedPage],
    ) -> list[str]:
        """Choose concise evidence-backed summary sentences."""

        sentences: list[str] = []
        seen: set[str] = set()
        evidence_blocks = [page.excerpt or page.text for page in pages] + [result.snippet for result in search_results]
        for block in evidence_blocks:
            for sentence in _split_sentences(block):
                cleaned = sentence.strip(" .")
                if len(cleaned.split()) < 5:
                    continue
                key = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
                if key in seen:
                    continue
                seen.add(key)
                sentences.append(cleaned + ".")
                if len(sentences) >= 2:
                    return sentences
        if not sentences and search_results:
            sentences.append(
                f"Based on the results I found, '{query.topic}' is discussed across multiple public sources such as "
                f"{_join_with_commas([result.source or extract_domain(result.url) for result in search_results[:3]])}."
            )
        return sentences

    def _has_dated_evidence(self, search_results: list[SearchResult], pages: list[FetchedPage]) -> bool:
        """Return whether the evidence includes any obvious publication date."""

        for text in [*(result.snippet for result in search_results), *(page.excerpt for page in pages)]:
            if _DATE_PATTERN.search(text or ""):
                return True
        return False


class ProviderBackedResearchSynthesizer:
    """Optionally use the configured AI provider, with deterministic fallback."""

    def __init__(
        self,
        *,
        provider: Any | None,
        fallback: DeterministicResearchSynthesizer,
        logger: Any | None = None,
    ) -> None:
        self.provider = provider
        self.fallback = fallback
        self.logger = logger

    def synthesize(
        self,
        query: ResearchQuery,
        search_results: list[SearchResult],
        pages: list[FetchedPage],
        *,
        error: str | None = None,
        search_status: str = "results",
        search_provider_name: str = "",
        search_diagnostics: tuple[SearchProviderDiagnostic, ...] = (),
    ) -> GroundedResearchResponse:
        """Use the active provider when viable, otherwise fall back deterministically."""

        fallback_response = self.fallback.synthesize(
            query,
            search_results,
            pages,
            error=error,
            search_status=search_status,
            search_provider_name=search_provider_name,
            search_diagnostics=search_diagnostics,
        )
        if not self._provider_is_usable():
            return fallback_response

        prompt = self._build_prompt(query, search_results, pages)
        try:
            provider_response = self._run_provider_sync(prompt)
        except Exception as exc:  # pragma: no cover - defensive fallback path
            _emit_log(self.logger, "warning", "Provider-backed research synthesis failed; using fallback", error=str(exc))
            return fallback_response

        if provider_response is None:
            return fallback_response
        if getattr(provider_response, "is_fallback", False):
            return fallback_response

        answer = str(getattr(provider_response, "content", "")).strip()
        if not answer:
            return fallback_response
        return replace(fallback_response, answer=answer, provider_name=str(getattr(provider_response, "provider_name", "provider")))

    def _provider_is_usable(self) -> bool:
        """Return whether the configured provider looks callable for synthesis."""

        if self.provider is None:
            return False
        provider_name = str(getattr(self.provider, "name", "")).lower()
        if provider_name in {"", "fallback"}:
            return False
        api_key = getattr(self.provider, "api_key", None)
        if api_key is not None and not str(api_key).strip():
            return False
        return hasattr(self.provider, "complete_chat")

    def _build_prompt(self, query: ResearchQuery, search_results: list[SearchResult], pages: list[FetchedPage]) -> str:
        """Construct the grounded evidence prompt for optional provider synthesis."""

        lines = [
            "Use only the supplied evidence. Do not invent facts.",
            f"User research topic: {query.topic}",
            f"Search text used: {query.search_text}",
        ]
        if query.freshness_terms:
            lines.append(f"Freshness hints: {', '.join(query.freshness_terms)}")
        lines.append("Search results:")
        for result in search_results[:5]:
            lines.append(f"- {result.title} | {result.url} | {result.snippet}")
        lines.append("Fetched page evidence:")
        for page in [item for item in pages if item.success][:3]:
            lines.append(f"- {page.title or page.final_url} | {page.final_url} | {page.excerpt}")
        lines.append("Return a concise grounded summary. If the topic is ambiguous, say so clearly.")
        return "\n".join(lines)

    def _run_provider_sync(self, prompt: str) -> Any:
        """Execute the provider call from synchronous skill code."""

        async def _complete() -> Any:
            return await self.provider.complete_chat(
                [{"role": "user", "content": prompt}],
                system_prompt="You are NARVIS. Summarize only the supplied web evidence and avoid inventing missing facts.",
                temperature=0.1,
                max_tokens=300,
                stream=False,
                context=None,
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_complete())

        result_box: dict[str, Any] = {}
        error_box: dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result_box["value"] = asyncio.run(_complete())
            except BaseException as exc:  # pragma: no cover - defensive handoff path
                error_box["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=getattr(self.provider, "timeout_seconds", 20) + 1)
        if thread.is_alive():
            raise TimeoutError("provider-backed research synthesis timed out")
        if "error" in error_box:
            raise error_box["error"]
        return result_box.get("value")


class InternetResearchService:
    """Coordinate search, safe page fetching, and grounded answer synthesis."""

    def __init__(
        self,
        *,
        search_provider: BaseSearchProvider,
        page_fetcher: SafePageFetcher,
        synthesizer: ResearchSynthesizer,
        logger: Any | None = None,
        search_limit: int = 5,
        page_limit: int = 3,
    ) -> None:
        self.search_provider = search_provider
        self.page_fetcher = page_fetcher
        self.synthesizer = synthesizer
        self.logger = logger
        self.search_limit = search_limit
        self.page_limit = page_limit

    def research(self, query: ResearchQuery | str, *, limit: int | None = None) -> GroundedResearchResponse:
        """Run one grounded public-web research request."""

        resolved_query = query if isinstance(query, ResearchQuery) else ResearchQuery(str(query), str(query), str(query))
        if not resolved_query.topic.strip():
            return GroundedResearchResponse(
                query=resolved_query,
                answer="I need a search topic before I can research the web.",
                sources=(),
                provider_name="deterministic-fallback",
                search_result_count=0,
                pages_read_count=0,
                error="empty query",
                search_status="all_failed",
            )

        if hasattr(self.search_provider, "is_available") and not self.search_provider.is_available():
            diagnostic = SearchProviderDiagnostic(
                provider_name=type(self.search_provider).__name__,
                status="provider_unavailable",
                result_count=0,
                error_message="provider is not available",
            )
            return self.synthesizer.synthesize(
                resolved_query,
                [],
                [],
                error="the configured search provider is unavailable",
                search_status="all_failed",
                search_diagnostics=(diagnostic,),
            )

        search_outcome = execute_search(self.search_provider, resolved_query.search_text, limit=limit or self.search_limit)
        self._log_search_attempts(resolved_query.search_text, search_outcome.attempts)

        if not search_outcome.succeeded:
            return self.synthesizer.synthesize(
                resolved_query,
                [],
                [],
                error=self._summarize_search_failure(search_outcome.attempts),
                search_status="all_failed",
                search_diagnostics=search_outcome.attempts,
            )

        search_results = list(search_outcome.results)

        pages: list[FetchedPage] = []
        for result in search_results[: self.page_limit]:
            fetched = self.page_fetcher.fetch(result.url)
            pages.append(fetched)

        response = self.synthesizer.synthesize(
            resolved_query,
            search_results,
            pages,
            search_status=search_outcome.status,
            search_provider_name=search_outcome.provider_name,
            search_diagnostics=search_outcome.attempts,
        )
        _emit_log(
            self.logger,
            "info",
            "Completed grounded research request",
            query=resolved_query.search_text,
            search_results=len(search_results),
            pages_read=len([page for page in pages if page.success]),
            provider=response.provider_name,
            search_provider=search_outcome.provider_name,
            search_status=search_outcome.status,
        )
        return response

    def _log_search_attempts(
        self,
        query: str,
        attempts: tuple[SearchProviderDiagnostic, ...],
    ) -> None:
        """Log each provider attempt without exposing raw response bodies."""

        for diagnostic in attempts:
            level = "debug" if diagnostic.succeeded else "warning"
            _emit_log(
                self.logger,
                level,
                "Research search-provider attempt",
                query=query,
                provider=diagnostic.provider_name,
                status=diagnostic.status,
                result_count=diagnostic.result_count,
                http_status=diagnostic.http_status,
                error=diagnostic.error_message,
            )

    def _summarize_search_failure(self, attempts: tuple[SearchProviderDiagnostic, ...]) -> str:
        """Create one concise technical summary for logs and diagnostics."""

        if not attempts:
            return "all live search providers failed"
        parts = []
        for diagnostic in attempts:
            if diagnostic.succeeded:
                continue
            detail = diagnostic.status
            if diagnostic.http_status is not None:
                detail = f"{detail} (HTTP {diagnostic.http_status})"
            parts.append(f"{diagnostic.provider_name}: {detail}")
        return "; ".join(parts) if parts else "all live search providers failed"


class _SafeRedirectHandler(request.HTTPRedirectHandler):
    """Validate redirect targets and enforce a strict redirect limit."""

    def __init__(self, *, validator: Callable[[str], str], max_redirects: int) -> None:
        super().__init__()
        self.validator = validator
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise UnsafeUrlError("too many redirects")
        self.validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ReadableHtmlParser(HTMLParser):
    """Extract readable text while skipping obvious non-content HTML regions."""

    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe", "nav", "footer", "header", "aside", "form"}
    _NOISE_HINTS = ("nav", "menu", "footer", "header", "sidebar", "breadcrumb")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignore_depth = 0
        self.capture_title = False
        self.title_text = ""
        self.text_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "").lower() for name, value in attrs}
        class_or_id = " ".join(filter(None, (attributes.get("class", ""), attributes.get("id", ""))))
        if tag in self._IGNORED_TAGS or any(token in class_or_id for token in self._NOISE_HINTS):
            self.ignore_depth += 1
            return
        if tag == "title":
            self.capture_title = True
            return
        if tag in {"p", "div", "section", "article", "main", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self.capture_title and tag == "title":
            self.capture_title = False
            return
        if self.ignore_depth > 0 and tag in self._IGNORED_TAGS.union({"div", "section", "article", "main", "aside", "form"}):
            self.ignore_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture_title:
            self.title_text += data
            return
        if self.ignore_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self.text_chunks.append(stripped)


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace to improve readability."""

    return " ".join(str(text).replace("\xa0", " ").split())


def _truncate_text(text: str, max_chars: int) -> str:
    """Bound extracted text length without cutting a word in half."""

    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].strip()
    return trimmed or text[:max_chars]


def _first_excerpt(text: str, max_chars: int = 280) -> str:
    """Return a short excerpt from extracted readable text."""

    if len(text) <= max_chars:
        return text
    return _truncate_text(text, max_chars)


def _split_sentences(text: str) -> list[str]:
    """Split text into compact sentence-like chunks."""

    normalized = _normalize_whitespace(text)
    if not normalized:
        return []
    return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", normalized) if chunk.strip()]


def _join_with_commas(items: list[str]) -> str:
    """Join short labels into a natural-language list."""

    unique = list(dict.fromkeys(item.strip() for item in items if item.strip()))
    if not unique:
        return ""
    if len(unique) == 1:
        return unique[0]
    if len(unique) == 2:
        return f"{unique[0]} and {unique[1]}"
    return f"{', '.join(unique[:-1])}, and {unique[-1]}"


__all__ = [
    "DeterministicResearchSynthesizer",
    "ExtractedContent",
    "FetchedPage",
    "GroundedResearchResponse",
    "HtmlContentExtractor",
    "InternetResearchIntentParser",
    "InternetResearchService",
    "ProviderBackedResearchSynthesizer",
    "ResearchQuery",
    "ResearchSource",
    "ResearchSynthesizer",
    "SafePageFetcher",
]
