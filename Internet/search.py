"""Search provider abstractions and public-web search implementations."""

from __future__ import annotations

import gzip
import socket
import ssl
import zlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib import error, parse, request

from .safety import UnsafeUrlError, extract_domain, normalize_public_url

HtmlFetcher = Callable[[str, str, float], Any]

_SUCCESSFUL_SEARCH_STATUSES = {"results", "zero_results"}
_BLOCKED_HTTP_STATUSES = {202, 403, 429, 503}
_GENERIC_BLOCKED_MARKERS = (
    "verify you are human",
    "verify that you are human",
    "captcha",
    "challenge",
    "automated requests",
    "unusual traffic",
    "access denied",
    "temporarily blocked",
    "bot verification",
)
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 NARVIS/1.1"
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


@dataclass(slots=True)
class SearchResult:
    """Represents a single normalized search result entry."""

    title: str
    url: str
    snippet: str = ""
    source: str = ""
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SearchProviderDiagnostic:
    """Structured diagnostic details for one provider attempt."""

    provider_name: str
    status: str
    result_count: int = 0
    error_message: str | None = None
    endpoint: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether the provider attempt completed successfully."""

        return self.status in _SUCCESSFUL_SEARCH_STATUSES


@dataclass(slots=True, frozen=True)
class SearchExecutionResult:
    """Normalized results plus per-provider diagnostics for one query."""

    query: str
    status: str
    results: tuple[SearchResult, ...] = ()
    attempts: tuple[SearchProviderDiagnostic, ...] = ()
    provider_name: str = ""
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether the overall search completed successfully."""

        return self.status in _SUCCESSFUL_SEARCH_STATUSES

    @property
    def zero_results(self) -> bool:
        """Return whether the search succeeded with a genuine empty result set."""

        return self.status == "zero_results"


@dataclass(slots=True, frozen=True)
class SearchHttpResponse:
    """Small decoded HTTP response record used by HTML search providers."""

    body: str
    status_code: int | None
    final_url: str
    content_type: str
    endpoint: str


class SearchProviderError(RuntimeError):
    """Base exception for search-provider failures."""

    status = "provider_unavailable"

    def __init__(
        self,
        message: str,
        *,
        provider_name: str = "",
        endpoint: str | None = None,
        final_url: str | None = None,
        http_status: int | None = None,
        content_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_name = provider_name
        self.endpoint = endpoint
        self.final_url = final_url
        self.http_status = http_status
        self.content_type = content_type

    def to_diagnostic(self, *, provider_name: str | None = None) -> SearchProviderDiagnostic:
        """Convert the exception into a structured diagnostic payload."""

        return SearchProviderDiagnostic(
            provider_name=provider_name or self.provider_name or "unknown-provider",
            status=self.status,
            result_count=0,
            error_message=str(self),
            endpoint=self.endpoint,
            final_url=self.final_url,
            http_status=self.http_status,
            content_type=self.content_type,
        )


class SearchProviderUnavailableError(SearchProviderError):
    """Raised when a search provider cannot be used."""

    status = "provider_unavailable"


class SearchProviderConnectionError(SearchProviderError):
    """Raised when a network or TLS connection to the provider fails."""

    status = "connection_failure"


class SearchProviderTimeoutError(SearchProviderError):
    """Raised when a search request times out."""

    status = "timeout"


class SearchProviderHttpError(SearchProviderError):
    """Raised when a provider returns an unexpected HTTP response."""

    status = "http_failure"


class SearchProviderBlockedError(SearchProviderError):
    """Raised when a provider appears to return an anti-bot or challenge page."""

    status = "blocked"


class SearchProviderParseError(SearchProviderError):
    """Raised when a provider response cannot be parsed safely."""

    status = "parse_failure"


class SearchProvidersExhaustedError(SearchProviderUnavailableError):
    """Raised when every provider in a fallback chain fails."""

    def __init__(
        self,
        message: str,
        *,
        attempts: Sequence[SearchProviderDiagnostic],
        provider_name: str = "fallback-chain",
    ) -> None:
        super().__init__(message, provider_name=provider_name)
        self.attempts = tuple(attempts)


class SearchProvider(Protocol):
    """Protocol for search providers."""

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for results related to the provided query."""


class BaseSearchProvider(ABC):
    """Abstract base class for search provider implementations."""

    def is_available(self) -> bool:
        """Return whether the provider is configured well enough to be attempted."""

        return True

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for results related to the provided query."""


class NullSearchProvider(BaseSearchProvider):
    """No-op search provider used as a placeholder implementation."""

    provider_name = "null-search"

    def is_available(self) -> bool:
        """Return that no live search capability is configured."""

        return False

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return an empty list of results."""

        return []


class _BaseHtmlSearchProvider(BaseSearchProvider):
    """Common HTML-search provider logic with structured diagnostics."""

    provider_name = "html-search"
    no_result_markers: tuple[str, ...] = ()
    blocked_markers: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: float = 6.0,
        max_response_bytes: int = 400_000,
        user_agent: str = _DEFAULT_USER_AGENT,
        html_fetcher: HtmlFetcher | None = None,
        logger: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.user_agent = user_agent
        self.html_fetcher = html_fetcher or self._fetch_html_response
        self.logger = logger

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search the web and return normalized results or raise a structured failure."""

        outcome = self.search_diagnostics(query, limit=limit)
        if outcome.succeeded:
            return list(outcome.results)
        raise self._outcome_to_error(outcome)

    def search_diagnostics(self, query: str, limit: int = 10) -> SearchExecutionResult:
        """Search the web and return results plus structured provider diagnostics."""

        normalized_query = _normalize_query(query)
        max_results = max(limit, 0)
        if not normalized_query or max_results <= 0:
            return SearchExecutionResult(
                query=normalized_query,
                status="zero_results",
                results=(),
                attempts=(SearchProviderDiagnostic(provider_name=self.provider_name, status="zero_results", result_count=0),),
                provider_name=self.provider_name,
            )

        try:
            response = self._load_response(normalized_query)
            candidates = self._parse_results(response.body)
            results = _normalize_search_results(candidates, provider_name=self.provider_name, limit=max_results)
        except SearchProviderError as exc:
            diagnostic = exc.to_diagnostic(provider_name=self.provider_name)
            self._log_attempt(diagnostic, normalized_query)
            return SearchExecutionResult(
                query=normalized_query,
                status=diagnostic.status,
                attempts=(diagnostic,),
                error_message=str(exc),
            )

        if results:
            diagnostic = SearchProviderDiagnostic(
                provider_name=self.provider_name,
                status="results",
                result_count=len(results),
                endpoint=response.endpoint,
                final_url=response.final_url,
                http_status=response.status_code,
                content_type=response.content_type,
            )
            self._log_attempt(diagnostic, normalized_query)
            return SearchExecutionResult(
                query=normalized_query,
                status="results",
                results=tuple(results),
                attempts=(diagnostic,),
                provider_name=self.provider_name,
            )

        body_lower = response.body.lower()
        if _looks_like_blocked(body_lower, extra_markers=self.blocked_markers) or response.status_code in _BLOCKED_HTTP_STATUSES:
            error_message = f"{self.provider_name} returned a blocked or challenge response"
            diagnostic = SearchProviderBlockedError(
                error_message,
                provider_name=self.provider_name,
                endpoint=response.endpoint,
                final_url=response.final_url,
                http_status=response.status_code,
                content_type=response.content_type,
            ).to_diagnostic()
            self._log_attempt(diagnostic, normalized_query)
            return SearchExecutionResult(
                query=normalized_query,
                status=diagnostic.status,
                attempts=(diagnostic,),
                error_message=error_message,
            )

        if _looks_like_no_results(body_lower, extra_markers=self.no_result_markers):
            diagnostic = SearchProviderDiagnostic(
                provider_name=self.provider_name,
                status="zero_results",
                result_count=0,
                endpoint=response.endpoint,
                final_url=response.final_url,
                http_status=response.status_code,
                content_type=response.content_type,
            )
            self._log_attempt(diagnostic, normalized_query)
            return SearchExecutionResult(
                query=normalized_query,
                status="zero_results",
                attempts=(diagnostic,),
                provider_name=self.provider_name,
            )

        error_message = (
            f"{self.provider_name} response did not contain recognizable search results "
            "and was not a verified empty-result page"
        )
        diagnostic = SearchProviderParseError(
            error_message,
            provider_name=self.provider_name,
            endpoint=response.endpoint,
            final_url=response.final_url,
            http_status=response.status_code,
            content_type=response.content_type,
        ).to_diagnostic()
        self._log_attempt(diagnostic, normalized_query)
        return SearchExecutionResult(
            query=normalized_query,
            status=diagnostic.status,
            attempts=(diagnostic,),
            error_message=error_message,
        )

    def _load_response(self, query: str) -> SearchHttpResponse:
        """Run the provider fetcher and normalize the response object."""

        try:
            response = self.html_fetcher(query, self.endpoint, self.timeout_seconds)
        except SearchProviderError:
            raise
        except TimeoutError as exc:
            raise SearchProviderTimeoutError(
                "search request timed out",
                provider_name=self.provider_name,
                endpoint=self.endpoint,
            ) from exc
        except OSError as exc:
            raise SearchProviderConnectionError(
                f"search provider connection failed: {exc}",
                provider_name=self.provider_name,
                endpoint=self.endpoint,
            ) from exc
        if isinstance(response, SearchHttpResponse):
            return response
        return SearchHttpResponse(
            body=str(response),
            status_code=200,
            final_url=self.endpoint,
            content_type="text/html",
            endpoint=self.endpoint,
        )

    def _fetch_html_response(self, query: str, endpoint: str, timeout_seconds: float) -> SearchHttpResponse:
        """Fetch one search-results page with bounded size and decoded text."""

        url = endpoint
        params = self._build_query_params(query)
        if params:
            url = f"{endpoint}?{parse.urlencode(params)}"

        req = request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_response_bytes:
                    raise SearchProviderParseError(
                        "search response exceeded the configured size limit",
                        provider_name=self.provider_name,
                        endpoint=endpoint,
                        final_url=response.geturl(),
                        http_status=getattr(response, "status", None),
                        content_type=response.headers.get_content_type().lower(),
                    )
                payload = response.read(self.max_response_bytes + 1)
                if len(payload) > self.max_response_bytes:
                    raise SearchProviderParseError(
                        "search response exceeded the configured size limit",
                        provider_name=self.provider_name,
                        endpoint=endpoint,
                        final_url=response.geturl(),
                        http_status=getattr(response, "status", None),
                        content_type=response.headers.get_content_type().lower(),
                    )
                decoded_text = _decode_search_payload(
                    payload,
                    content_encoding=response.headers.get("Content-Encoding", ""),
                    charset=response.headers.get_content_charset("utf-8"),
                    max_response_bytes=self.max_response_bytes,
                    provider_name=self.provider_name,
                    endpoint=endpoint,
                    final_url=response.geturl(),
                    http_status=getattr(response, "status", None),
                    content_type=response.headers.get_content_type().lower(),
                )
                return SearchHttpResponse(
                    body=decoded_text,
                    status_code=getattr(response, "status", None),
                    final_url=response.geturl(),
                    content_type=response.headers.get_content_type().lower(),
                    endpoint=endpoint,
                )
        except TimeoutError as exc:
            raise SearchProviderTimeoutError(
                "search request timed out",
                provider_name=self.provider_name,
                endpoint=endpoint,
            ) from exc
        except error.HTTPError as exc:
            raise self._http_error_to_search_error(exc, endpoint=endpoint) from exc
        except error.URLError as exc:
            raise _url_error_to_search_error(exc, provider_name=self.provider_name, endpoint=endpoint) from exc
        except ssl.SSLError as exc:
            raise SearchProviderConnectionError(
                f"TLS connection failed: {exc}",
                provider_name=self.provider_name,
                endpoint=endpoint,
            ) from exc
        except OSError as exc:
            raise SearchProviderConnectionError(
                f"search provider connection failed: {exc}",
                provider_name=self.provider_name,
                endpoint=endpoint,
            ) from exc

    def _http_error_to_search_error(self, exc: error.HTTPError, *, endpoint: str) -> SearchProviderError:
        """Convert an HTTP failure into the right structured search exception."""

        message = f"search provider returned HTTP {exc.code}"
        response_body = _read_http_error_body(exc, self.max_response_bytes)
        body_lower = response_body.lower()
        if exc.code in _BLOCKED_HTTP_STATUSES or _looks_like_blocked(body_lower, extra_markers=self.blocked_markers):
            return SearchProviderBlockedError(
                message,
                provider_name=self.provider_name,
                endpoint=endpoint,
                final_url=exc.geturl(),
                http_status=exc.code,
                content_type=exc.headers.get_content_type().lower() if exc.headers else None,
            )
        return SearchProviderHttpError(
            message,
            provider_name=self.provider_name,
            endpoint=endpoint,
            final_url=exc.geturl(),
            http_status=exc.code,
            content_type=exc.headers.get_content_type().lower() if exc.headers else None,
        )

    def _outcome_to_error(self, outcome: SearchExecutionResult) -> SearchProviderError:
        """Convert a failed execution result back into a structured exception."""

        diagnostic = outcome.attempts[-1] if outcome.attempts else None
        message = outcome.error_message or "search provider failed"
        if diagnostic is None:
            return SearchProviderUnavailableError(message, provider_name=self.provider_name, endpoint=self.endpoint)
        error_cls = {
            "provider_unavailable": SearchProviderUnavailableError,
            "connection_failure": SearchProviderConnectionError,
            "timeout": SearchProviderTimeoutError,
            "http_failure": SearchProviderHttpError,
            "blocked": SearchProviderBlockedError,
            "parse_failure": SearchProviderParseError,
        }.get(diagnostic.status, SearchProviderError)
        return error_cls(
            message,
            provider_name=diagnostic.provider_name,
            endpoint=diagnostic.endpoint,
            final_url=diagnostic.final_url,
            http_status=diagnostic.http_status,
            content_type=diagnostic.content_type,
        )

    def _build_query_params(self, query: str) -> dict[str, str]:
        """Return query parameters for the provider endpoint."""

        return {"q": query}

    @abstractmethod
    def _parse_results(self, html: str) -> list[dict[str, str]]:
        """Extract title, URL, and snippet candidates from one HTML body."""

    def _log_attempt(self, diagnostic: SearchProviderDiagnostic, query: str) -> None:
        """Log one provider attempt in a structured, secret-safe form."""

        level = "debug" if diagnostic.succeeded else "warning"
        _emit_log(
            self.logger,
            level,
            "Search provider attempt",
            provider=diagnostic.provider_name,
            query=query,
            status=diagnostic.status,
            result_count=diagnostic.result_count,
            http_status=diagnostic.http_status,
            content_type=diagnostic.content_type,
            endpoint=diagnostic.endpoint,
            error=diagnostic.error_message,
        )


class DuckDuckGoSearchProvider(_BaseHtmlSearchProvider):
    """Public-web search provider backed by DuckDuckGo HTML results."""

    provider_name = "duckduckgo"
    no_result_markers = (
        "no results found",
        "no results.",
        "no matches found",
        "did not match any documents",
    )
    blocked_markers = (
        "anomaly.js",
        "please complete the following challenge",
        "duckduckgo detected unusual traffic",
    )

    def __init__(
        self,
        *,
        endpoint: str = "https://duckduckgo.com/html/",
        timeout_seconds: float = 6.0,
        max_response_bytes: int = 400_000,
        user_agent: str = _DEFAULT_USER_AGENT,
        html_fetcher: HtmlFetcher | None = None,
        logger: Any | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            user_agent=user_agent,
            html_fetcher=html_fetcher,
            logger=logger,
        )

    def _build_query_params(self, query: str) -> dict[str, str]:
        """Return the DuckDuckGo HTML search query parameters."""

        return {"q": query, "kl": "us-en"}

    def _parse_results(self, html: str) -> list[dict[str, str]]:
        """Extract result candidates from a DuckDuckGo HTML response."""

        parser = _DuckDuckGoHtmlParser()
        parser.feed(html)
        parser.close()
        return parser.results


class BingSearchProvider(_BaseHtmlSearchProvider):
    """Public-web search provider backed by Bing HTML results."""

    provider_name = "bing"
    no_result_markers = (
        "there are no results for",
        "no results for",
        "did not match any documents",
    )
    blocked_markers = (
        "our systems have detected unusual traffic",
        "please solve the challenge below",
        "please verify you are a human",
    )

    def __init__(
        self,
        *,
        endpoint: str = "https://www.bing.com/search",
        timeout_seconds: float = 6.0,
        max_response_bytes: int = 400_000,
        user_agent: str = _DEFAULT_USER_AGENT,
        html_fetcher: HtmlFetcher | None = None,
        logger: Any | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            user_agent=user_agent,
            html_fetcher=html_fetcher,
            logger=logger,
        )

    def _build_query_params(self, query: str) -> dict[str, str]:
        """Return the Bing search query parameters."""

        return {"q": query, "setlang": "en-US"}

    def _parse_results(self, html: str) -> list[dict[str, str]]:
        """Extract result candidates from a Bing HTML response."""

        parser = _BingHtmlParser()
        parser.feed(html)
        parser.close()
        return parser.results


class FallbackSearchProvider(BaseSearchProvider):
    """Fallback chain that keeps trying providers until a reliable outcome is found."""

    provider_name = "fallback-chain"

    def __init__(
        self,
        providers: Sequence[BaseSearchProvider],
        *,
        logger: Any | None = None,
    ) -> None:
        self.providers = tuple(providers)
        self.logger = logger

    def is_available(self) -> bool:
        """Return whether at least one configured provider can be attempted."""

        return any(getattr(provider, "is_available", lambda: True)() for provider in self.providers)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Run the provider chain and raise only when every provider fails."""

        outcome = self.search_diagnostics(query, limit=limit)
        if outcome.succeeded:
            return list(outcome.results)
        raise SearchProvidersExhaustedError(
            outcome.error_message or "all live search providers failed",
            attempts=outcome.attempts,
            provider_name=self.provider_name,
        )

    def search_diagnostics(self, query: str, limit: int = 10) -> SearchExecutionResult:
        """Run the provider chain and capture diagnostics from each provider attempt."""

        normalized_query = _normalize_query(query)
        max_results = max(limit, 0)
        if not normalized_query or max_results <= 0:
            return SearchExecutionResult(query=normalized_query, status="zero_results", provider_name=self.provider_name)

        attempts: list[SearchProviderDiagnostic] = []
        collected: list[SearchResult] = []
        zero_result_provider: str | None = None

        for provider in self.providers:
            if hasattr(provider, "is_available") and not provider.is_available():
                diagnostic = SearchProviderDiagnostic(
                    provider_name=_provider_name(provider),
                    status="provider_unavailable",
                    result_count=0,
                    error_message="provider is not available",
                )
                attempts.append(diagnostic)
                self._log_attempt(diagnostic, normalized_query)
                continue

            outcome = execute_search(provider, normalized_query, limit=max_results)
            for diagnostic in outcome.attempts:
                attempts.append(diagnostic)
                self._log_attempt(diagnostic, normalized_query)

            if outcome.status == "results":
                collected.extend(outcome.results)
                deduped = _deduplicate_search_results(collected, limit=max_results)
                collected = list(deduped)
                if len(collected) >= max_results:
                    break
                continue

            if outcome.status == "zero_results":
                zero_result_provider = outcome.provider_name or _provider_name(provider)
                if not collected:
                    break
                continue

        if collected:
            return SearchExecutionResult(
                query=normalized_query,
                status="results",
                results=_rerank_results(collected),
                attempts=tuple(attempts),
                provider_name=next(
                    (diagnostic.provider_name for diagnostic in attempts if diagnostic.status == "results"),
                    self.provider_name,
                ),
            )

        if zero_result_provider is not None:
            return SearchExecutionResult(
                query=normalized_query,
                status="zero_results",
                attempts=tuple(attempts),
                provider_name=zero_result_provider,
            )

        error_message = "all live search providers failed"
        return SearchExecutionResult(
            query=normalized_query,
            status="all_failed",
            attempts=tuple(attempts),
            provider_name=self.provider_name,
            error_message=error_message,
        )

    def _log_attempt(self, diagnostic: SearchProviderDiagnostic, query: str) -> None:
        """Log one provider attempt from the fallback chain."""

        level = "debug" if diagnostic.succeeded else "warning"
        _emit_log(
            self.logger,
            level,
            "Search fallback attempt",
            provider=diagnostic.provider_name,
            query=query,
            status=diagnostic.status,
            result_count=diagnostic.result_count,
            http_status=diagnostic.http_status,
            error=diagnostic.error_message,
        )


def execute_search(provider: Any, query: str, limit: int = 10) -> SearchExecutionResult:
    """Execute a search provider call while preserving structured diagnostics."""

    diagnostics_method = getattr(provider, "search_diagnostics", None)
    if callable(diagnostics_method):
        try:
            outcome = diagnostics_method(query, limit=limit)
        except SearchProviderError as exc:
            diagnostic = exc.to_diagnostic(provider_name=_provider_name(provider))
            return SearchExecutionResult(
                query=_normalize_query(query),
                status=diagnostic.status,
                attempts=(diagnostic,),
                error_message=str(exc),
            )
        if isinstance(outcome, SearchExecutionResult):
            return outcome

    try:
        results = tuple(provider.search(query, limit=limit))
    except SearchProviderError as exc:
        diagnostic = exc.to_diagnostic(provider_name=_provider_name(provider))
        return SearchExecutionResult(
            query=_normalize_query(query),
            status=diagnostic.status,
            attempts=(diagnostic,),
            error_message=str(exc),
        )
    except TimeoutError as exc:
        diagnostic = SearchProviderTimeoutError(
            "search request timed out",
            provider_name=_provider_name(provider),
        ).to_diagnostic()
        return SearchExecutionResult(
            query=_normalize_query(query),
            status=diagnostic.status,
            attempts=(diagnostic,),
            error_message=str(exc),
        )
    except OSError as exc:
        diagnostic = SearchProviderConnectionError(
            f"search provider connection failed: {exc}",
            provider_name=_provider_name(provider),
        ).to_diagnostic()
        return SearchExecutionResult(
            query=_normalize_query(query),
            status=diagnostic.status,
            attempts=(diagnostic,),
            error_message=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive adapter path
        diagnostic = SearchProviderUnavailableError(
            f"search provider is unavailable: {exc}",
            provider_name=_provider_name(provider),
        ).to_diagnostic()
        return SearchExecutionResult(
            query=_normalize_query(query),
            status=diagnostic.status,
            attempts=(diagnostic,),
            error_message=str(exc),
        )

    deduped = _deduplicate_search_results(results, limit=max(limit, 0))
    status = "results" if deduped else "zero_results"
    diagnostic = SearchProviderDiagnostic(
        provider_name=_provider_name(provider),
        status=status,
        result_count=len(deduped),
    )
    return SearchExecutionResult(
        query=_normalize_query(query),
        status=status,
        results=deduped,
        attempts=(diagnostic,),
        provider_name=_provider_name(provider),
    )


def build_public_search_provider_chain(*, logger: Any | None = None) -> FallbackSearchProvider:
    """Build the default live-search provider chain used by the runtime."""

    return FallbackSearchProvider(
        (
            DuckDuckGoSearchProvider(logger=logger),
            BingSearchProvider(logger=logger),
        ),
        logger=logger,
    )


def _provider_name(provider: Any) -> str:
    """Return a stable provider name for diagnostics."""

    name = getattr(provider, "provider_name", None) or getattr(provider, "name", None)
    return str(name or type(provider).__name__).strip() or type(provider).__name__


def _normalize_query(value: str) -> str:
    """Normalize one free-form search query."""

    return " ".join(str(value).strip().split())


def _normalize_search_results(
    candidates: Iterable[dict[str, str]],
    *,
    provider_name: str,
    limit: int,
) -> list[SearchResult]:
    """Normalize parser output into safe deduplicated search results."""

    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if len(results) >= limit:
            break
        raw_url = str(candidate.get("url", "")).strip()
        if not raw_url:
            continue
        try:
            normalized_url = normalize_public_url(raw_url, resolve_host=False)
        except UnsafeUrlError:
            continue
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        title = _normalize_text(candidate.get("title", ""))
        snippet = _normalize_text(candidate.get("snippet", ""))
        if not title:
            continue
        results.append(
            SearchResult(
                title=title,
                url=normalized_url,
                snippet=snippet,
                source=extract_domain(normalized_url),
                rank=len(results) + 1,
                metadata={"provider": provider_name},
            )
        )
    return results


def _deduplicate_search_results(results: Iterable[SearchResult], *, limit: int) -> tuple[SearchResult, ...]:
    """Deduplicate results across providers using normalized public URLs."""

    deduped: list[SearchResult] = []
    seen_urls: set[str] = set()
    for result in results:
        if len(deduped) >= limit:
            break
        try:
            normalized_url = normalize_public_url(result.url, resolve_host=False)
        except UnsafeUrlError:
            continue
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduped.append(
            SearchResult(
                title=result.title,
                url=normalized_url,
                snippet=result.snippet,
                source=result.source or extract_domain(normalized_url),
                rank=len(deduped) + 1,
                metadata=dict(result.metadata),
            )
        )
    return tuple(deduped)


def _rerank_results(results: Sequence[SearchResult]) -> tuple[SearchResult, ...]:
    """Return the supplied results with stable sequential ranking."""

    reranked: list[SearchResult] = []
    for index, result in enumerate(results, start=1):
        reranked.append(
            SearchResult(
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                source=result.source,
                rank=index,
                metadata=dict(result.metadata),
            )
        )
    return tuple(reranked)


def _decode_search_payload(
    payload: bytes,
    *,
    content_encoding: str,
    charset: str,
    max_response_bytes: int,
    provider_name: str,
    endpoint: str,
    final_url: str,
    http_status: int | None,
    content_type: str | None,
) -> str:
    """Decode compressed or plain search HTML safely within the size budget."""

    normalized_encoding = content_encoding.strip().lower()
    decoded_payload = payload
    try:
        if normalized_encoding == "gzip":
            decoded_payload = gzip.decompress(payload)
        elif normalized_encoding == "deflate":
            try:
                decoded_payload = zlib.decompress(payload)
            except zlib.error:
                decoded_payload = zlib.decompress(payload, -zlib.MAX_WBITS)
        elif normalized_encoding and normalized_encoding not in {"identity"}:
            raise SearchProviderParseError(
                f"unsupported content encoding: {normalized_encoding}",
                provider_name=provider_name,
                endpoint=endpoint,
                final_url=final_url,
                http_status=http_status,
                content_type=content_type,
            )
    except (OSError, zlib.error) as exc:
        raise SearchProviderParseError(
            f"unable to decode compressed search response: {exc}",
            provider_name=provider_name,
            endpoint=endpoint,
            final_url=final_url,
            http_status=http_status,
            content_type=content_type,
        ) from exc

    if len(decoded_payload) > max_response_bytes:
        raise SearchProviderParseError(
            "search response exceeded the configured size limit",
            provider_name=provider_name,
            endpoint=endpoint,
            final_url=final_url,
            http_status=http_status,
            content_type=content_type,
        )
    return decoded_payload.decode(charset or "utf-8", errors="replace")


def _read_http_error_body(exc: error.HTTPError, max_response_bytes: int) -> str:
    """Read a bounded HTTP error body for challenge detection."""

    try:
        payload = exc.read(max_response_bytes)
    except Exception:
        return ""
    content_encoding = exc.headers.get("Content-Encoding", "") if exc.headers else ""
    charset = exc.headers.get_content_charset("utf-8") if exc.headers else "utf-8"
    try:
        return _decode_search_payload(
            payload,
            content_encoding=content_encoding,
            charset=charset,
            max_response_bytes=max_response_bytes,
            provider_name="http-error",
            endpoint=exc.geturl(),
            final_url=exc.geturl(),
            http_status=exc.code,
            content_type=exc.headers.get_content_type().lower() if exc.headers else None,
        )
    except SearchProviderError:
        return ""


def _url_error_to_search_error(exc: error.URLError, *, provider_name: str, endpoint: str) -> SearchProviderError:
    """Map urllib URL errors into stable structured search error categories."""

    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return SearchProviderTimeoutError("search request timed out", provider_name=provider_name, endpoint=endpoint)
    if isinstance(reason, ssl.SSLError):
        return SearchProviderConnectionError(f"TLS connection failed: {reason}", provider_name=provider_name, endpoint=endpoint)
    if isinstance(reason, OSError):
        return SearchProviderConnectionError(
            f"search provider connection failed: {reason}",
            provider_name=provider_name,
            endpoint=endpoint,
        )
    message = str(reason).lower()
    if "timed out" in message:
        return SearchProviderTimeoutError("search request timed out", provider_name=provider_name, endpoint=endpoint)
    return SearchProviderConnectionError(
        f"search provider connection failed: {reason}",
        provider_name=provider_name,
        endpoint=endpoint,
    )


def _looks_like_blocked(body_lower: str, *, extra_markers: Sequence[str] = ()) -> bool:
    """Return whether one HTML body looks like a challenge or anti-bot page."""

    markers = (*_GENERIC_BLOCKED_MARKERS, *extra_markers)
    return any(marker in body_lower for marker in markers)


def _looks_like_no_results(body_lower: str, *, extra_markers: Sequence[str] = ()) -> bool:
    """Return whether one HTML body confidently represents a true empty SERP."""

    markers = (
        "no results found",
        "no results for",
        "did not match any documents",
        "no matches found",
        *extra_markers,
    )
    return any(marker in body_lower for marker in markers)


class _DuckDuckGoHtmlParser(HTMLParser):
    """Extract title and snippet fields from DuckDuckGo HTML search results."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._capture_title = False
        self._capture_snippet = False
        self._snippet_depth = 0
        self._snippet_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        class_name = attributes.get("class", "").lower()
        rel_tokens = {token for token in attributes.get("rel", "").lower().split() if token}

        if tag == "a":
            href = attributes.get("href", "").strip()
            is_snippet_link = "result__snippet" in class_name or "result-snippet" in class_name
            is_result_link = "result__a" in class_name or "result-link" in class_name or (
                "nofollow" in rel_tokens and href and not is_snippet_link
            )
            if is_result_link:
                self._capture_title = True
                self._anchor_href = href
                self._anchor_text = []

        if tag in {"a", "div", "span", "td"} and ("result__snippet" in class_name or "result-snippet" in class_name):
            self._capture_snippet = True
            self._snippet_depth = 1
            self._snippet_text = []
        elif self._capture_snippet and tag in {"a", "div", "span", "td"}:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            title = _normalize_text("".join(self._anchor_text))
            if title and self._anchor_href:
                self.results.append({"title": title, "url": self._anchor_href, "snippet": ""})
            self._capture_title = False
            self._anchor_href = None
            self._anchor_text = []
            return

        if self._capture_snippet and tag in {"a", "div", "span", "td"}:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                snippet = _normalize_text("".join(self._snippet_text))
                if snippet and self.results and not self.results[-1]["snippet"]:
                    self.results[-1]["snippet"] = snippet
                self._capture_snippet = False
                self._snippet_depth = 0
                self._snippet_text = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._anchor_text.append(data)
        if self._capture_snippet:
            self._snippet_text.append(data)


class _BingHtmlParser(HTMLParser):
    """Extract title and snippet fields from Bing HTML search results."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._result_depth = 0
        self._current_anchor_href: str | None = None
        self._capture_title = False
        self._title_text: list[str] = []
        self._capture_snippet = False
        self._snippet_depth = 0
        self._snippet_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        class_name = attributes.get("class", "").lower()

        if tag == "li" and "b_algo" in class_name:
            self._in_result = True
            self._result_depth = 1
            self._current_anchor_href = None
            self._capture_title = False
            self._capture_snippet = False
            self._title_text = []
            self._snippet_text = []
            return

        if self._in_result and tag == "li":
            self._result_depth += 1

        if self._in_result and tag == "a" and self._current_anchor_href is None:
            href = attributes.get("href", "").strip()
            if href:
                self._current_anchor_href = href
                self._capture_title = True
                self._title_text = []

        if self._in_result and tag in {"div", "p", "span"} and (
            "b_caption" in class_name or "b_snippet" in class_name or "b_paractl" in class_name
        ):
            self._capture_snippet = True
            self._snippet_depth = 1
            self._snippet_text = []
        elif self._capture_snippet and tag in {"div", "p", "span"}:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            title = _normalize_text("".join(self._title_text))
            if title and self._current_anchor_href:
                self.results.append({"title": title, "url": self._current_anchor_href, "snippet": ""})
            self._capture_title = False
            self._title_text = []
            return

        if self._capture_snippet and tag in {"div", "p", "span"}:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                snippet = _normalize_text("".join(self._snippet_text))
                if snippet and self.results and not self.results[-1]["snippet"]:
                    self.results[-1]["snippet"] = snippet
                self._capture_snippet = False
                self._snippet_depth = 0
                self._snippet_text = []

        if self._in_result and tag == "li":
            self._result_depth -= 1
            if self._result_depth <= 0:
                self._in_result = False
                self._result_depth = 0
                self._current_anchor_href = None
                self._capture_title = False
                self._capture_snippet = False
                self._title_text = []
                self._snippet_text = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_text.append(data)
        if self._capture_snippet:
            self._snippet_text.append(data)


def _normalize_text(value: str) -> str:
    """Normalize whitespace inside one extracted HTML text block."""

    return " ".join(str(value).replace("\xa0", " ").split())


__all__ = [
    "BaseSearchProvider",
    "BingSearchProvider",
    "DuckDuckGoSearchProvider",
    "FallbackSearchProvider",
    "NullSearchProvider",
    "SearchExecutionResult",
    "SearchHttpResponse",
    "SearchProvider",
    "SearchProviderBlockedError",
    "SearchProviderConnectionError",
    "SearchProviderDiagnostic",
    "SearchProviderError",
    "SearchProviderHttpError",
    "SearchProviderParseError",
    "SearchProviderTimeoutError",
    "SearchProviderUnavailableError",
    "SearchProvidersExhaustedError",
    "SearchResult",
    "build_public_search_provider_chain",
    "execute_search",
]
