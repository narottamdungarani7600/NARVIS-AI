"""Runtime service wiring and aggregation helpers for NARVIS Internet."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .browser import BaseBrowser, NullBrowser
from .downloader import BaseFileDownloader, NullFileDownloader
from .internet import NetworkStatus
from .news import BaseNewsProvider, NewsArticle, NullNewsProvider
from .requests import BaseHttpClient, NullHttpClient, UrllibHttpClient
from .research import (
    DeterministicResearchSynthesizer,
    GroundedResearchResponse,
    InternetResearchService,
    ProviderBackedResearchSynthesizer,
    ResearchQuery,
    SafePageFetcher,
)
from .search import BaseSearchProvider, NullSearchProvider, SearchResult, build_public_search_provider_chain
from .weather import BaseWeatherProvider, OpenMeteoWeatherProvider, WeatherReport
from .wikipedia import BaseWikipediaProvider, MediaWikiWikipediaProvider, WikipediaResult
from .youtube import BaseYouTubeProvider, NullYouTubeProvider, YouTubeResult


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


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Internet."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class RuntimeOptimizerProtocol(Protocol):
    """Protocol for the runtime cache used by Internet services."""

    def get(self, namespace: str, key: str) -> Any | None:
        """Return a cached value if it exists."""

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: float | None = None) -> Any:
        """Cache a value and return it."""

    def increment_counter(self, name: str, amount: int = 1) -> int:
        """Increment a named counter."""


@dataclass(slots=True, frozen=True)
class InternetRequestRecord:
    """Represents one internet-facing request handled by the runtime."""

    operation: str
    target: str
    cached: bool = False
    item_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class StaticConnectivityProbe:
    """Report connectivity based on configured provider capabilities."""

    def __init__(self, http_client: BaseHttpClient, logger: Any | None = None) -> None:
        self.http_client = http_client
        self.logger = logger

    def check(self) -> NetworkStatus:
        """Return a deterministic connectivity status without external calls."""

        offline = type(self.http_client).__name__.lower().startswith("null")
        details = {
            "mode": "offline" if offline else "configured",
            "http_client": type(self.http_client).__name__,
        }
        return NetworkStatus(online=not offline, latency_ms=None, details=details)


class InternetService:
    """Aggregate browser, search, content, and download capabilities."""

    def __init__(
        self,
        *,
        browser: BaseBrowser,
        http_client: BaseHttpClient,
        download_manager: BaseFileDownloader,
        search_provider: BaseSearchProvider,
        research_service: InternetResearchService,
        news_provider: BaseNewsProvider,
        weather_provider: BaseWeatherProvider,
        wikipedia_provider: BaseWikipediaProvider,
        youtube_provider: BaseYouTubeProvider,
        connectivity_probe: StaticConnectivityProbe,
        runtime_optimizer: RuntimeOptimizerProtocol | None = None,
        logger: Any | None = None,
        cache_ttl_seconds: float = 30.0,
    ) -> None:
        self.browser = browser
        self.http_client = http_client
        self.download_manager = download_manager
        self.search_provider = search_provider
        self.research_service = research_service
        self.news_provider = news_provider
        self.weather_provider = weather_provider
        self.wikipedia_provider = wikipedia_provider
        self.youtube_provider = youtube_provider
        self.connectivity_probe = connectivity_probe
        self.runtime_optimizer = runtime_optimizer
        self.logger = logger
        self.cache_ttl_seconds = cache_ttl_seconds
        self._history: list[InternetRequestRecord] = []

    def network_status(self) -> NetworkStatus:
        """Return the current connectivity status."""

        return self.connectivity_probe.check()

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search through the configured search provider with caching."""

        normalized_query = self._normalize_query(query)
        cache_key = f"search:{normalized_query}:{max(limit, 1)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._record("search", normalized_query, cached=True, item_count=len(cached))
            return list(cached)

        try:
            results = list(self.search_provider.search(normalized_query, limit=max(limit, 1)))
        except Exception as exc:
            self._record("search", normalized_query, item_count=0, metadata={"error": str(exc)})
            _emit_log(self.logger, "warning", "Search provider failed", query=normalized_query, error=str(exc))
            return []
        self._set_cached(cache_key, tuple(results))
        self._record("search", normalized_query, item_count=len(results))
        return results

    def research(self, query: ResearchQuery | str, limit: int = 5) -> GroundedResearchResponse:
        """Run a grounded public-web research request with caching."""

        resolved_query = query if isinstance(query, ResearchQuery) else ResearchQuery(str(query), str(query), str(query))
        cache_key = f"research:{resolved_query.search_text}:{max(limit, 1)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._record("research", resolved_query.search_text, cached=True, item_count=len(cached.sources))
            return cached

        response = self.research_service.research(resolved_query, limit=max(limit, 1))
        self._set_cached(cache_key, response)
        self._record(
            "research",
            resolved_query.search_text,
            item_count=response.search_result_count,
            metadata={"pages_read": response.pages_read_count, "provider": response.provider_name},
        )
        return response

    def fetch_news(self, topic: str | None = None, limit: int = 10) -> list[NewsArticle]:
        """Fetch news articles through the configured news provider."""

        normalized_topic = self._normalize_query(topic or "latest")
        cache_key = f"news:{normalized_topic}:{max(limit, 1)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._record("news", normalized_topic, cached=True, item_count=len(cached))
            return list(cached)

        articles = list(self.news_provider.fetch(topic=normalized_topic, limit=max(limit, 1)))
        self._set_cached(cache_key, tuple(articles))
        self._record("news", normalized_topic, item_count=len(articles))
        return articles

    def fetch_weather(self, location: str) -> WeatherReport:
        """Fetch one weather report through the configured provider."""

        normalized_location = self._normalize_query(location)
        cache_key = f"weather:{normalized_location}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._record("weather", normalized_location, cached=True, item_count=1)
            return cached

        report = self.weather_provider.fetch(normalized_location)
        self._set_cached(cache_key, report)
        self._record("weather", normalized_location, item_count=1)
        return report

    def search_wikipedia(self, query: str, limit: int = 5) -> list[WikipediaResult]:
        """Search Wikipedia content."""

        normalized_query = self._normalize_query(query)
        cache_key = f"wikipedia:{normalized_query}:{max(limit, 1)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._record("wikipedia", normalized_query, cached=True, item_count=len(cached))
            return list(cached)

        results = list(self.wikipedia_provider.search(normalized_query, limit=max(limit, 1)))
        self._set_cached(cache_key, tuple(results))
        self._record("wikipedia", normalized_query, item_count=len(results))
        return results

    def search_youtube(self, query: str, limit: int = 5) -> list[YouTubeResult]:
        """Search YouTube content."""

        normalized_query = self._normalize_query(query)
        cache_key = f"youtube:{normalized_query}:{max(limit, 1)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            self._record("youtube", normalized_query, cached=True, item_count=len(cached))
            return list(cached)

        results = list(self.youtube_provider.search(normalized_query, limit=max(limit, 1)))
        self._set_cached(cache_key, tuple(results))
        self._record("youtube", normalized_query, item_count=len(results))
        return results

    def open_url(self, url: str) -> bool:
        """Open a URL in the configured browser."""

        self.browser.open(url)
        self._record("browser.open", url, item_count=1)
        return True

    def download(self, url: str, destination: str | Path) -> Path:
        """Download a file through the configured download manager."""

        path = self.download_manager.download(url, destination)
        self._record("download", url, item_count=1, metadata={"destination": str(path)})
        return path

    def request_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform a GET request through the configured HTTP client."""

        self._record("http.get", url, item_count=1)
        return self.http_client.get(url, headers=headers, timeout=timeout)

    def history(self, limit: int | None = None) -> tuple[InternetRequestRecord, ...]:
        """Return recent internet requests."""

        if limit is None:
            return tuple(self._history)
        return tuple(self._history[-max(limit, 0) :])

    def capabilities(self) -> dict[str, Any]:
        """Return a lightweight capability summary."""

        return {
            "browser": type(self.browser).__name__,
            "http_client": type(self.http_client).__name__,
            "download_manager": type(self.download_manager).__name__,
            "search_provider": type(self.search_provider).__name__,
            "research_service": type(self.research_service).__name__,
            "news_provider": type(self.news_provider).__name__,
            "weather_provider": type(self.weather_provider).__name__,
            "wikipedia_provider": type(self.wikipedia_provider).__name__,
            "youtube_provider": type(self.youtube_provider).__name__,
        }

    def _normalize_query(self, value: str) -> str:
        """Normalize user-provided query text."""

        return " ".join(str(value).strip().split())

    def _get_cached(self, key: str) -> Any | None:
        """Return a cached value using the runtime optimizer when available."""

        if self.runtime_optimizer is None:
            return None
        return self.runtime_optimizer.get("internet", key)

    def _set_cached(self, key: str, value: Any) -> Any:
        """Store a cached value using the runtime optimizer when available."""

        if self.runtime_optimizer is None:
            return value
        return self.runtime_optimizer.set("internet", key, value, ttl_seconds=self.cache_ttl_seconds)

    def _record(
        self,
        operation: str,
        target: str,
        *,
        cached: bool = False,
        item_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a runtime internet request."""

        record = InternetRequestRecord(
            operation=operation,
            target=target,
            cached=cached,
            item_count=item_count,
            metadata=dict(metadata or {}),
        )
        self._history.append(record)
        if self.runtime_optimizer is not None:
            self.runtime_optimizer.increment_counter("internet.requests", amount=1)
        _emit_log(self.logger, "debug", "Handled internet request", operation=operation, target=target, cached=cached)


@dataclass(slots=True)
class InternetServices:
    """Container for runtime internet services and collaborators."""

    internet_service: InternetService
    connectivity_probe: StaticConnectivityProbe
    browser: BaseBrowser
    http_client: BaseHttpClient
    download_manager: BaseFileDownloader
    search_provider: BaseSearchProvider
    research_service: InternetResearchService
    news_provider: BaseNewsProvider
    weather_provider: BaseWeatherProvider
    wikipedia_provider: BaseWikipediaProvider
    youtube_provider: BaseYouTubeProvider


def build_internet_services(
    *,
    browser: BaseBrowser | None = None,
    http_client: BaseHttpClient | None = None,
    download_manager: BaseFileDownloader | None = None,
    search_provider: BaseSearchProvider | None = None,
    research_service: InternetResearchService | None = None,
    news_provider: BaseNewsProvider | None = None,
    weather_provider: BaseWeatherProvider | None = None,
    wikipedia_provider: BaseWikipediaProvider | None = None,
    youtube_provider: BaseYouTubeProvider | None = None,
    ai_provider: Any | None = None,
    runtime_optimizer: RuntimeOptimizerProtocol | None = None,
    logger: Any | None = None,
) -> InternetServices:
    """Build the runtime internet service bundle using constructor injection."""

    resolved_browser = browser or NullBrowser()
    resolved_http_client = http_client or UrllibHttpClient()
    resolved_download_manager = download_manager or NullFileDownloader()
    resolved_search_provider = search_provider or build_public_search_provider_chain(logger=logger)
    resolved_news_provider = news_provider or NullNewsProvider()
    resolved_weather_provider = weather_provider or OpenMeteoWeatherProvider(
        http_client=resolved_http_client,
        logger=logger,
    )
    resolved_wikipedia_provider = wikipedia_provider or MediaWikiWikipediaProvider(
        http_client=resolved_http_client,
        logger=logger,
    )
    resolved_youtube_provider = youtube_provider or NullYouTubeProvider()
    resolved_research_service = research_service or InternetResearchService(
        search_provider=resolved_search_provider,
        page_fetcher=SafePageFetcher(logger=logger),
        synthesizer=ProviderBackedResearchSynthesizer(
            provider=ai_provider,
            fallback=DeterministicResearchSynthesizer(logger=logger),
            logger=logger,
        ),
        logger=logger,
    )
    connectivity_probe = StaticConnectivityProbe(http_client=resolved_http_client, logger=logger)
    internet_service = InternetService(
        browser=resolved_browser,
        http_client=resolved_http_client,
        download_manager=resolved_download_manager,
        search_provider=resolved_search_provider,
        research_service=resolved_research_service,
        news_provider=resolved_news_provider,
        weather_provider=resolved_weather_provider,
        wikipedia_provider=resolved_wikipedia_provider,
        youtube_provider=resolved_youtube_provider,
        connectivity_probe=connectivity_probe,
        runtime_optimizer=runtime_optimizer,
        logger=logger,
    )
    _emit_log(logger, "info", "Built internet services")
    return InternetServices(
        internet_service=internet_service,
        connectivity_probe=connectivity_probe,
        browser=resolved_browser,
        http_client=resolved_http_client,
        download_manager=resolved_download_manager,
        search_provider=resolved_search_provider,
        research_service=resolved_research_service,
        news_provider=resolved_news_provider,
        weather_provider=resolved_weather_provider,
        wikipedia_provider=resolved_wikipedia_provider,
        youtube_provider=resolved_youtube_provider,
    )


def register_internet_services(
    container: DependencyRegistrar,
    services: InternetServices,
    *,
    logger: Any | None = None,
) -> InternetServices:
    """Register runtime internet services in the dependency container."""

    container.register_instance("internet_service", services.internet_service)
    container.register_instance("connectivity_probe", services.connectivity_probe)
    container.register_instance("browser", services.browser)
    container.register_instance("http_client", services.http_client)
    container.register_instance("download_manager", services.download_manager)
    container.register_instance("search_provider", services.search_provider)
    container.register_instance("internet_research_service", services.research_service)
    container.register_instance("news_provider", services.news_provider)
    container.register_instance("weather_provider", services.weather_provider)
    container.register_instance("wikipedia_provider", services.wikipedia_provider)
    container.register_instance("youtube_provider", services.youtube_provider)
    _emit_log(logger, "info", "Registered internet services in container")
    return services


__all__ = [
    "InternetRequestRecord",
    "InternetService",
    "InternetServices",
    "StaticConnectivityProbe",
    "build_internet_services",
    "register_internet_services",
]
