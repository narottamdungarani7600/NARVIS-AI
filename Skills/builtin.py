"""Built-in skills that integrate the NARVIS runtime subsystems."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from Internet.news import NewsQuery, normalize_news_request
from Internet.research import InternetResearchIntentParser
from .desktop_commands import build_desktop_command_services
from .framework import BaseSkill, SkillMatch, SkillRequest, SkillResult

_NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
_DIRECT_NEWS_PREFIX_PATTERN = re.compile(
    r"^(?P<descriptor>(?:latest|top|breaking)\s+news|today(?:'s)?\s+top\s+news|top headlines|headlines)"
    r"(?:\s+(?:about|on|for)\s+(?P<topic>.+))?$",
    re.IGNORECASE,
)
_DIRECT_NEWS_SUFFIX_PATTERN = re.compile(
    r"^(?P<topic>.+?)\s+(?P<descriptor>latest|top|breaking)\s+news$",
    re.IGNORECASE,
)
_DIRECT_NEWS_RESEARCH_MARKERS = (
    "search the internet",
    "search internet",
    "internet se",
    "internet me",
    "internet par",
    "internet pe",
    "research ",
    " on the web",
    " web par",
    " web pe",
)


def _slugify(value: str) -> str:
    """Create a stable key from user-provided text."""

    normalized = _NON_WORD_PATTERN.sub("_", value.strip().lower()).strip("_")
    return normalized or "memory"


class HelpSkill(BaseSkill):
    """List the runtime skills available to the user."""

    def __init__(self, *, catalog_provider: Callable[[], list[dict[str, str]]], logger: Any | None = None) -> None:
        super().__init__(
            name="help.catalog",
            description="List built-in runtime skills and their purpose.",
            keywords=("help", "skills", "capabilities", "what can you do"),
            logger=logger,
        )
        self._catalog_provider = catalog_provider

    def execute(self, request: SkillRequest) -> SkillResult:
        """Return the skill catalog."""

        catalog = self._catalog_provider()
        lines = [f"{item['name']}: {item['description']}" for item in catalog]
        message = "Available skills:\n" + "\n".join(lines) if lines else "No skills are registered."
        return SkillResult(skill_name=self.name, handled=True, message=message, data={"skills": catalog})


class RuntimeStatusSkill(BaseSkill):
    """Summarize runtime health reports."""

    def __init__(self, *, health_provider: Callable[[], dict[str, Any]], logger: Any | None = None) -> None:
        super().__init__(
            name="runtime.status",
            description="Summarize runtime health and module readiness.",
            keywords=("status", "health", "runtime", "modules", "uptime"),
            logger=logger,
        )
        self._health_provider = health_provider

    def execute(self, request: SkillRequest) -> SkillResult:
        """Return a text summary of module health."""

        reports = self._health_provider()
        if not reports:
            return SkillResult(skill_name=self.name, handled=True, message="No health reports are available.")
        lines = [f"{name}: {getattr(report, 'status', 'unknown')}" for name, report in sorted(reports.items())]
        return SkillResult(
            skill_name=self.name,
            handled=True,
            message="Runtime status:\n" + "\n".join(lines),
            data={"modules": lines},
        )


class MemorySkill(BaseSkill):
    """Persist, search, and forget memory items."""

    def __init__(self, *, memory_service: Any, logger: Any | None = None) -> None:
        super().__init__(
            name="memory.manage",
            description="Remember, forget, and recall persisted runtime memories.",
            keywords=("remember", "memory", "recall", "forget"),
            logger=logger,
        )
        self.memory_service = memory_service

    def execute(self, request: SkillRequest) -> SkillResult:
        """Handle deterministic memory commands."""

        normalized_text = " ".join(request.text.strip().split())
        lowered = normalized_text.lower()

        if lowered.startswith("remember "):
            content = normalized_text[9:].strip()
            key = _slugify(content[:48])
            stored = self.memory_service.remember(
                key=key,
                value=content,
                scope="both",
                metadata={"source": "skill", "conversation_id": request.conversation_id},
            )
            return SkillResult(
                skill_name=self.name,
                handled=True,
                message=f"Remembered '{content}' under key '{key}'.",
                data={"key": key, "stored_count": len(stored)},
            )

        if lowered.startswith("forget "):
            key = _slugify(normalized_text[7:].strip())
            removed = self.memory_service.forget(key)
            return SkillResult(
                skill_name=self.name,
                handled=True,
                message=f"{'Forgot' if removed else 'Did not find'} memory key '{key}'.",
                data={"key": key, "removed": removed},
            )

        recall_prefixes = (
            "recall ",
            "remember about ",
            "what do you remember about ",
            "search memory for ",
        )
        matched_prefix = next((prefix for prefix in recall_prefixes if lowered.startswith(prefix)), None)
        if matched_prefix is not None:
            query = normalized_text[len(matched_prefix) :].strip()
            entry = self.memory_service.recall(_slugify(query))
            if entry is not None:
                return SkillResult(
                    skill_name=self.name,
                    handled=True,
                    message=f"Memory '{entry.key}': {entry.value}",
                    data={"key": entry.key, "value": entry.value},
                )
            results = self.memory_service.search(query, limit=5)
            if not results:
                return SkillResult(
                    skill_name=self.name,
                    handled=True,
                    message=f"No stored memory matched '{query}'.",
                    data={"query": query, "results": []},
                )
            lines = [f"{result.key}: {result.value}" for result in results]
            return SkillResult(
                skill_name=self.name,
                handled=True,
                message="Memory search results:\n" + "\n".join(lines),
                data={"query": query, "results": lines},
            )

        return SkillResult(skill_name=self.name, handled=False, message="No memory action matched.")


class InternetSkill(BaseSkill):
    """Run deterministic internet queries through the configured runtime service."""

    def __init__(self, *, internet_service: Any, logger: Any | None = None) -> None:
        super().__init__(
            name="internet.query",
            description="Search, fetch weather, news, Wikipedia, or YouTube content.",
            keywords=("search", "weather", "news", "wikipedia", "youtube"),
            logger=logger,
        )
        self.internet_service = internet_service
        self.intent_parser = InternetResearchIntentParser(logger=logger)

    def match(self, request: SkillRequest) -> SkillMatch:
        """Detect grounded web-research requests without stealing desktop commands."""

        direct_news_request = self._extract_direct_news_request(request.text)
        if direct_news_request is not None:
            return SkillMatch(skill_name=self.name, confidence=0.9, reason="natural news intent")

        intent_decision = self.intent_parser.evaluate(request.text, context=request.metadata)
        if intent_decision.query is not None:
            return SkillMatch(skill_name=self.name, confidence=intent_decision.confidence, reason=intent_decision.reason)

        lowered = " ".join(request.text.strip().lower().split())
        if lowered.startswith("weather "):
            return SkillMatch(skill_name=self.name, confidence=0.92, reason="weather prefix")
        if lowered.startswith("news "):
            return SkillMatch(skill_name=self.name, confidence=0.84, reason="news prefix")
        if lowered.startswith("wikipedia "):
            return SkillMatch(skill_name=self.name, confidence=0.82, reason="wikipedia prefix")
        if lowered.startswith("youtube "):
            return SkillMatch(skill_name=self.name, confidence=0.82, reason="youtube prefix")
        return SkillMatch(skill_name=self.name, confidence=0.0, reason="no internet action matched")

    def execute(self, request: SkillRequest) -> SkillResult:
        """Handle deterministic internet commands."""

        normalized_text = " ".join(request.text.strip().split())
        lowered = normalized_text.lower()

        direct_news_request = self._extract_direct_news_request(normalized_text)
        if direct_news_request is not None:
            return self._execute_news_request(direct_news_request)

        intent_decision = self.intent_parser.evaluate(normalized_text, context=request.metadata)
        if intent_decision.query is not None:
            response = self.internet_service.research(intent_decision.query, limit=5)
            return SkillResult(
                skill_name=self.name,
                handled=True,
                message=response.render_message(),
                data={
                    "query": response.query.topic,
                    "search_text": response.query.search_text,
                    "intent_kind": response.query.intent_kind,
                    "routing_signals": list(response.query.routing_signals),
                    "provider": response.provider_name,
                    "search_provider": response.search_provider_name,
                    "search_status": response.search_status,
                    "search_result_count": response.search_result_count,
                    "pages_read_count": response.pages_read_count,
                    "ambiguous": response.ambiguous,
                    "follow_up_question": response.follow_up_question,
                    "sources": [{"title": source.title, "url": source.url, "domain": source.domain} for source in response.sources],
                    "search_diagnostics": [
                        {
                            "provider": diagnostic.provider_name,
                            "status": diagnostic.status,
                            "result_count": diagnostic.result_count,
                            "http_status": diagnostic.http_status,
                            "error": diagnostic.error_message,
                        }
                        for diagnostic in response.search_diagnostics
                    ],
                    "error": response.error,
                },
            )

        if lowered.startswith("weather "):
            location = self._extract_weather_location(normalized_text)
            report = self.internet_service.fetch_weather(location)
            message = f"Weather for {report.location}: {report.condition}"
            if report.temperature_c is not None:
                message += f", {report.temperature_c:.1f} C"
            return SkillResult(skill_name=self.name, handled=True, message=message, data={"location": report.location})

        if lowered.startswith("news "):
            topic = normalized_text[5:].removeprefix("about ").strip()
            return self._execute_news_request(topic or None)

        if lowered.startswith("wikipedia "):
            query = normalized_text[10:].strip()
            results = self.internet_service.search_wikipedia(query, limit=3)
            lines = []
            for result in results:
                line = f"{result.title} - {result.summary}" if result.summary else result.title
                if result.url:
                    line = f"{line} - {result.url}"
                lines.append(line)
            message = "Wikipedia results:\n" + "\n".join(lines) if lines else f"No Wikipedia results are available for '{query}'."
            return SkillResult(skill_name=self.name, handled=True, message=message, data={"results": lines})

        if lowered.startswith("youtube "):
            query = normalized_text[8:].strip()
            results = self.internet_service.search_youtube(query, limit=3)
            lines = [f"{result.title} - {result.url}" for result in results]
            message = "YouTube results:\n" + "\n".join(lines) if lines else f"No YouTube results are available for '{query}'."
            return SkillResult(skill_name=self.name, handled=True, message=message, data={"results": lines})

        return SkillResult(skill_name=self.name, handled=False, message="No internet action matched.")

    def _extract_weather_location(self, text: str) -> str:
        """Normalize weather requests like 'Weather today in Ahmedabad'."""

        match = re.match(
            r"^weather(?:\s+(?:today|current|now|aaj|abhi))?(?:\s+(?:in|for)\s+)?(?P<location>.+)$",
            text,
            re.IGNORECASE,
        )
        if match is not None:
            location = " ".join(match.group("location").strip().split())
            if location:
                return location
        fallback = text[8:].removeprefix("in ").strip()
        return fallback or text

    def _execute_news_request(self, topic: NewsQuery | str | None) -> SkillResult:
        """Fetch news and render one compact user-facing summary."""

        normalized_request = normalize_news_request(topic)
        articles = self.internet_service.fetch_news(topic=topic, limit=5)
        lines = [self._format_news_line(article) for article in articles]
        request_label = self._describe_news_request(normalized_request)
        query = normalized_request.topic or normalized_request.query_text or request_label
        search_text = normalized_request.query_text or normalized_request.topic or request_label
        message = "News results:\n" + "\n".join(lines) if lines else f"No news articles are available for '{request_label}'."
        return SkillResult(
            skill_name=self.name,
            handled=True,
            message=message,
            data={
                "results": lines,
                "query": query,
                "search_text": search_text,
                "intent_kind": "news",
                "internet_kind": "news",
                "routing_signals": self._news_routing_signals(normalized_request),
            },
        )

    def _extract_direct_news_request(self, text: str) -> NewsQuery | None:
        """Detect direct natural-language news requests without stealing research commands."""

        normalized_text = " ".join(text.strip().split())
        lowered = normalized_text.lower()
        if not lowered or lowered.startswith(("news ", "weather ", "wikipedia ", "youtube ")):
            return None
        if any(marker in lowered for marker in _DIRECT_NEWS_RESEARCH_MARKERS):
            return None
        if lowered in {"world news", "global news"}:
            return NewsQuery(request_type="search", query_text="world news", category="world")

        match = _DIRECT_NEWS_PREFIX_PATTERN.match(normalized_text)
        if match is not None:
            topic = " ".join((match.group("topic") or "").strip().split())
            descriptor = self._normalize_news_descriptor(match.group("descriptor") or "")
            if not topic:
                return NewsQuery(request_type="latest", query_text="latest news", category="top")
            return NewsQuery(request_type="search", query_text=f"{topic} {descriptor}", topic=topic)

        match = _DIRECT_NEWS_SUFFIX_PATTERN.match(normalized_text)
        if match is not None:
            topic = " ".join((match.group("topic") or "").strip().split())
            descriptor = self._normalize_news_descriptor(match.group("descriptor") or "")
            if topic:
                return NewsQuery(request_type="search", query_text=f"{topic} {descriptor}", topic=topic)
        return None

    def _normalize_news_descriptor(self, value: str) -> str:
        """Normalize natural-news phrases into consistent search text."""

        normalized = " ".join(str(value).strip().lower().split())
        if normalized in {"today top news", "today's top news", "todays top news", "top headlines", "headlines"}:
            return "top news"
        if normalized == "breaking":
            return "breaking news"
        if normalized == "top":
            return "top news"
        return "latest news" if normalized in {"latest", "latest news"} else normalized

    def _format_news_line(self, article: Any) -> str:
        """Render one compact news article summary for the user."""

        parts = [str(getattr(article, "title", "")).strip()]
        source = str(getattr(article, "source", "") or "").strip()
        published_at = str(getattr(article, "published_at", "") or "").strip()
        url = str(getattr(article, "url", "") or "").strip()
        source_summary = " | ".join(part for part in (source, published_at) if part)
        if source_summary:
            parts.append(source_summary)
        if url:
            parts.append(url)
        return " - ".join(part for part in parts if part) or "News article"

    def _describe_news_request(self, topic: NewsQuery | str | None) -> str:
        """Build a concise label for no-result messages."""

        if isinstance(topic, NewsQuery):
            if topic.topic:
                return topic.topic
            if topic.category and topic.category.lower() != "top":
                return f"{topic.category} news"
            return "latest"
        normalized = " ".join(str(topic or "").strip().split())
        return normalized or "latest"

    def _news_routing_signals(self, request: NewsQuery) -> list[str]:
        """Build compact routing signals for Brain follow-up context."""

        signals = ["news"]
        if request.request_type == "latest" or "latest" in request.query_text.lower():
            signals.append("latest")
        if request.category:
            signals.append(request.category.lower())
        return list(dict.fromkeys(signal for signal in signals if signal))


class DesktopSkill(BaseSkill):
    """Control desktop-oriented runtime capabilities."""

    def __init__(
        self,
        *,
        desktop_control: Any,
        desktop_command_pipeline: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        super().__init__(
            name="desktop.control",
            description="Capture screenshots, access the clipboard, and manage applications or windows.",
            keywords=("screenshot", "clipboard", "application", "window", "launch", "open", "copy", "type", "press"),
            logger=logger,
        )
        self.desktop_control = desktop_control
        self.command_pipeline = desktop_command_pipeline or build_desktop_command_services(
            desktop_control=desktop_control,
            logger=logger,
        ).pipeline

    def match(self, request: SkillRequest) -> SkillMatch:
        """Return the natural-language match score for desktop commands."""

        command_match = self.command_pipeline.match(request)
        if command_match is None:
            return super().match(request)
        return SkillMatch(
            skill_name=self.name,
            confidence=command_match.confidence,
            reason=command_match.reason,
        )

    def execute(self, request: SkillRequest) -> SkillResult:
        """Handle deterministic desktop-control commands."""

        result = self.command_pipeline.execute(request)
        if result is not None:
            return SkillResult(
                skill_name=self.name,
                handled=result.handled,
                message=result.message,
                data=dict(result.data),
                confidence=result.confidence,
            )
        return SkillResult(skill_name=self.name, handled=False, message="No desktop action matched.")


def build_builtin_skills(
    *,
    memory_service: Any,
    internet_service: Any,
    desktop_control: Any,
    desktop_command_pipeline: Any | None = None,
    health_provider: Callable[[], dict[str, Any]],
    catalog_provider: Callable[[], list[dict[str, str]]],
    logger: Any | None = None,
) -> tuple[BaseSkill, ...]:
    """Build the default stable-release skill pack."""

    return (
        HelpSkill(catalog_provider=catalog_provider, logger=logger),
        RuntimeStatusSkill(health_provider=health_provider, logger=logger),
        MemorySkill(memory_service=memory_service, logger=logger),
        InternetSkill(internet_service=internet_service, logger=logger),
        DesktopSkill(
            desktop_control=desktop_control,
            desktop_command_pipeline=desktop_command_pipeline,
            logger=logger,
        ),
    )


__all__ = [
    "DesktopSkill",
    "HelpSkill",
    "InternetSkill",
    "MemorySkill",
    "RuntimeStatusSkill",
    "build_builtin_skills",
]
