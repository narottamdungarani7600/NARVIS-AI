"""Internet package for NARVIS.

This package provides reusable abstractions for connectivity checks, browser
interaction, search providers, HTTP clients, downloads, news, weather, YouTube,
and Wikipedia integration without introducing real service logic.
"""

from .browser import BaseBrowser, Browser, NullBrowser
from .downloader import BaseFileDownloader, FileDownloader, NullFileDownloader
from .internet import ConnectivityProbe, NetworkStatus
from .news import BaseNewsProvider, NewsArticle, NewsProvider, NullNewsProvider
from .requests import BaseHttpClient, HttpClient, NullHttpClient
from .runtime import (
    InternetRequestRecord,
    InternetService,
    InternetServices,
    StaticConnectivityProbe,
    build_internet_services,
    register_internet_services,
)
from .search import BaseSearchProvider, NullSearchProvider, SearchProvider, SearchResult
from .weather import BaseWeatherProvider, NullWeatherProvider, WeatherProvider, WeatherReport
from .wikipedia import BaseWikipediaProvider, NullWikipediaProvider, WikipediaProvider, WikipediaResult
from .youtube import BaseYouTubeProvider, NullYouTubeProvider, YouTubeProvider, YouTubeResult

__all__ = [
    "BaseBrowser",
    "BaseFileDownloader",
    "BaseHttpClient",
    "BaseNewsProvider",
    "BaseSearchProvider",
    "BaseWeatherProvider",
    "BaseWikipediaProvider",
    "BaseYouTubeProvider",
    "Browser",
    "ConnectivityProbe",
    "FileDownloader",
    "HttpClient",
    "InternetRequestRecord",
    "InternetService",
    "InternetServices",
    "NetworkStatus",
    "NewsArticle",
    "NewsProvider",
    "NullBrowser",
    "NullFileDownloader",
    "NullHttpClient",
    "NullNewsProvider",
    "NullSearchProvider",
    "NullWeatherProvider",
    "NullWikipediaProvider",
    "NullYouTubeProvider",
    "SearchProvider",
    "SearchResult",
    "StaticConnectivityProbe",
    "WeatherProvider",
    "WeatherReport",
    "WikipediaProvider",
    "WikipediaResult",
    "YouTubeProvider",
    "YouTubeResult",
    "build_internet_services",
    "register_internet_services",
]
