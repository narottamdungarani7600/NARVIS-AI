"""Natural-language desktop command pipeline for the NARVIS Skills package."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from AI.intent import IntentAnalyzer, IntentClassification, IntentType
from AI.router import IntentRouter, ModuleRoute, Router
from Computer.control import DesktopControlResult, DesktopControlService

from .framework import (
    BaseSkill,
    DependencyRegistrar,
    SkillExecutor,
    SkillMatch,
    SkillRegistry,
    SkillRequest,
    SkillResult,
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


_WHITESPACE_PATTERN = re.compile(r"\s+")
_REQUEST_PREFIX_PATTERN = re.compile(r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)+", re.IGNORECASE)
_REQUEST_SUFFIX_PATTERN = re.compile(r"(?:\s+(?:for me|please|right now|now|today))+$", re.IGNORECASE)


def _compact_text(text: str) -> str:
    """Collapse whitespace while preserving the original text casing."""

    return _WHITESPACE_PATTERN.sub(" ", text.strip()).strip()


def _normalize_text(text: str) -> str:
    """Normalize request text for deterministic matching."""

    collapsed = _WHITESPACE_PATTERN.sub(" ", text.strip().lower())
    return collapsed.strip()


def _clean_argument(value: str) -> str:
    """Remove polite wrappers and punctuation from captured text."""

    cleaned = value.strip().strip(" \t\r\n.,!?;:")
    cleaned = _REQUEST_SUFFIX_PATTERN.sub("", cleaned).strip(" \t\r\n.,!?;:")
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'`":
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _strip_request_prefix(normalized: str) -> str:
    """Remove leading polite phrases while preserving the command body."""

    stripped = _REQUEST_PREFIX_PATTERN.sub("", normalized)
    return stripped.strip()


def _normalize_key_name(value: str) -> str:
    """Convert common natural-language key names into backend-friendly names."""

    aliases = {
        "escape": "esc",
        "escape key": "esc",
        "return": "enter",
        "return key": "enter",
        "space": "space",
        "space bar": "space",
        "spacebar": "space",
        "page up": "pageup",
        "page down": "pagedown",
        "back space": "backspace",
    }
    normalized = _clean_argument(value).lower()
    return aliases.get(normalized, normalized)


@dataclass(slots=True, frozen=True)
class DesktopCommandCandidate:
    """Represents one parsed desktop command candidate."""

    confidence: float
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DesktopCommandMatch:
    """Represents a matched desktop command and its routing context."""

    command_name: str
    confidence: float
    reason: str
    intent: str
    route: str


class DesktopCommandSkill(BaseSkill):
    """Base class for natural-language desktop command handlers."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        desktop_control: DesktopControlService,
        keywords: tuple[str, ...] = (),
        logger: Any | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            keywords=keywords,
            logger=logger,
        )
        self.desktop_control = desktop_control

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        """Parse a request into command arguments when it matches."""

        raise NotImplementedError

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        """Execute the parsed command through the desktop control service."""

        raise NotImplementedError

    def match(self, request: SkillRequest) -> SkillMatch:
        """Return the match score for the supplied request."""

        candidate = self.parse(request)
        if candidate is None:
            return SkillMatch(skill_name=self.name, confidence=0.0, reason="no command match")
        return SkillMatch(
            skill_name=self.name,
            confidence=candidate.confidence,
            reason=candidate.reason,
        )

    def execute(self, request: SkillRequest) -> SkillResult:
        """Execute the supplied request when it can be parsed."""

        candidate = self.parse(request)
        if candidate is None:
            return SkillResult(skill_name=self.name, handled=False, message="No desktop action matched.")

        result = self.run(candidate)
        result_data = dict(getattr(result, "data", {}))
        return SkillResult(
            skill_name=self.name,
            handled=True,
            message=str(getattr(result, "message", "")),
            data={
                "action": getattr(result, "action", self.name),
                "success": bool(getattr(result, "success", True)),
                **result_data,
            },
            confidence=candidate.confidence,
        )


class CaptureScreenshotCommandSkill(DesktopCommandSkill):
    """Capture a screenshot from natural-language requests."""

    _PATTERNS = (
        re.compile(r"\b(?:take|capture|grab|snap)\s+(?:a\s+)?(?:screen shot|screenshot)\b"),
        re.compile(r"\b(?:screen shot|screenshot)\b"),
        re.compile(r"\bcapture\s+(?:the\s+)?screen\b"),
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.screenshot",
            description="Capture a screenshot of the current desktop.",
            desktop_control=desktop_control,
            keywords=("screenshot", "screen shot", "capture screen"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        normalized = _normalize_text(request.text)
        if any(pattern.search(normalized) for pattern in self._PATTERNS):
            return DesktopCommandCandidate(confidence=0.95, reason="matched screenshot request")
        return None

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.capture_screenshot()


class ReadClipboardCommandSkill(DesktopCommandSkill):
    """Read clipboard contents from natural-language requests."""

    _PATTERNS = (
        re.compile(r"\b(?:read|show|display|get|view)\b.*\bclipboard\b"),
        re.compile(r"\bwhat(?:'s| is)\b.*\bclipboard\b"),
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.clipboard.read",
            description="Read the current clipboard contents.",
            desktop_control=desktop_control,
            keywords=("clipboard", "read clipboard", "show clipboard"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        normalized = _normalize_text(request.text)
        if "clipboard" not in normalized:
            return None
        if any(pattern.search(normalized) for pattern in self._PATTERNS):
            return DesktopCommandCandidate(confidence=0.92, reason="matched clipboard read request")
        return None

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.read_clipboard()


class WriteClipboardCommandSkill(DesktopCommandSkill):
    """Write clipboard contents from natural-language requests."""

    _PATTERNS = (
        re.compile(
            r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:copy)\s+(?P<text>.+?)\s+(?:to|into|on)\s+clipboard[.!?]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:put|save|write)\s+(?P<text>.+?)\s+(?:to|into|on)\s+clipboard[.!?]*$",
            re.IGNORECASE,
        ),
        re.compile(r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*write clipboard\s+(?P<text>.+)$", re.IGNORECASE),
        re.compile(r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*copy\s+(?P<text>.+)$", re.IGNORECASE),
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.clipboard.write",
            description="Write text to the clipboard.",
            desktop_control=desktop_control,
            keywords=("copy", "write clipboard", "clipboard"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        normalized = _compact_text(request.text)
        for pattern in self._PATTERNS:
            match = pattern.match(normalized)
            if match is None:
                continue
            text = _clean_argument(match.group("text"))
            if not text:
                return None
            return DesktopCommandCandidate(
                confidence=0.91,
                reason="matched clipboard write request",
                arguments={"text": text},
            )
        return None

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.write_clipboard(str(candidate.arguments["text"]))


class TypeTextCommandSkill(DesktopCommandSkill):
    """Type text through the desktop keyboard controller."""

    _PATTERN = re.compile(
        r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:type|enter)\s+(?P<text>.+)$",
        re.IGNORECASE,
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.type_text",
            description="Type text into the active application.",
            desktop_control=desktop_control,
            keywords=("type", "enter text"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        match = self._PATTERN.match(_compact_text(request.text))
        if match is None:
            return None
        text = _clean_argument(match.group("text"))
        if not text:
            return None
        return DesktopCommandCandidate(
            confidence=0.9,
            reason="matched text entry request",
            arguments={"text": text},
        )

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.type_text(str(candidate.arguments["text"]))


class PressKeyCommandSkill(DesktopCommandSkill):
    """Press one keyboard key from a natural-language request."""

    _PATTERN = re.compile(
        r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:press|hit|tap)\s+(?:the\s+)?(?P<key>[a-z0-9_+\- ]+?)(?:\s+key)?[.!?]*$",
        re.IGNORECASE,
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.press_key",
            description="Press a single keyboard key.",
            desktop_control=desktop_control,
            keywords=("press", "hit key", "tap key"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        match = self._PATTERN.match(_compact_text(request.text))
        if match is None:
            return None
        key = _normalize_key_name(match.group("key"))
        if not key:
            return None
        return DesktopCommandCandidate(
            confidence=0.88,
            reason="matched key press request",
            arguments={"key": key},
        )

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.press_key(str(candidate.arguments["key"]))


class OpenApplicationCommandSkill(DesktopCommandSkill):
    """Open an application from natural-language requests."""

    _PATTERN = re.compile(
        r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:open|launch|start)\s+(?:the\s+)?(?:application\s+)?(?P<application>.+)$",
        re.IGNORECASE,
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.application.open",
            description="Open an application by name.",
            desktop_control=desktop_control,
            keywords=("open", "launch", "start application"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        compact = _strip_request_prefix(_compact_text(request.text))
        match = self._PATTERN.match(compact)
        if match is None:
            return None
        application = _clean_argument(match.group("application")).removeprefix("the ").strip()
        if not application:
            return None
        return DesktopCommandCandidate(
            confidence=0.89,
            reason="matched application launch request",
            arguments={"application": application},
        )

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.open_application(str(candidate.arguments["application"]))


class CloseApplicationCommandSkill(DesktopCommandSkill):
    """Close an application from natural-language requests."""

    _PATTERN = re.compile(
        r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:close|quit|exit|stop)\s+(?:the\s+)?(?:application\s+)?(?P<application>.+)$",
        re.IGNORECASE,
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.application.close",
            description="Close an application by name.",
            desktop_control=desktop_control,
            keywords=("close application", "quit", "exit"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        compact = _strip_request_prefix(_compact_text(request.text))
        match = self._PATTERN.match(compact)
        if match is None:
            return None
        application = _clean_argument(match.group("application")).removeprefix("the ").strip()
        if not application:
            return None
        return DesktopCommandCandidate(
            confidence=0.88,
            reason="matched application close request",
            arguments={"application": application},
        )

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.close_application(str(candidate.arguments["application"]))


class ListWindowsCommandSkill(DesktopCommandSkill):
    """List the currently open windows from natural-language requests."""

    _PATTERNS = (
        re.compile(r"\b(?:list|show|display)\b.*\bwindows?\b"),
        re.compile(r"\bwhat(?:'s| is)\b.*\bwindows?\b"),
        re.compile(r"\bwhich\b.*\bwindows?\b"),
        re.compile(r"\bopen windows?\b"),
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.windows.list",
            description="List the currently open windows.",
            desktop_control=desktop_control,
            keywords=("windows", "open windows", "list windows"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        normalized = _normalize_text(request.text)
        if "window" not in normalized:
            return None
        if any(pattern.search(normalized) for pattern in self._PATTERNS):
            return DesktopCommandCandidate(confidence=0.9, reason="matched window listing request")
        return None

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.list_windows()


class FocusWindowCommandSkill(DesktopCommandSkill):
    """Focus a window from natural-language requests."""

    _PATTERNS = (
        re.compile(
            r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*(?:focus|activate)\s+(?:the\s+)?(?:window\s+)?(?P<title>.+)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+)*switch to\s+(?:the\s+)?(?:window\s+)?(?P<title>.+)$",
            re.IGNORECASE,
        ),
    )

    def __init__(self, *, desktop_control: DesktopControlService, logger: Any | None = None) -> None:
        super().__init__(
            name="desktop.command.window.focus",
            description="Focus a window by title.",
            desktop_control=desktop_control,
            keywords=("focus window", "switch to", "activate window"),
            logger=logger,
        )

    def parse(self, request: SkillRequest) -> DesktopCommandCandidate | None:
        normalized = _compact_text(request.text)
        for pattern in self._PATTERNS:
            match = pattern.match(normalized)
            if match is None:
                continue
            title = _clean_argument(match.group("title")).removeprefix("the ").strip()
            if not title:
                return None
            return DesktopCommandCandidate(
                confidence=0.9,
                reason="matched window focus request",
                arguments={"title": title},
            )
        return None

    def run(self, candidate: DesktopCommandCandidate) -> DesktopControlResult:
        return self.desktop_control.focus_window(str(candidate.arguments["title"]))


def build_desktop_command_skills(
    *,
    desktop_control: DesktopControlService,
    logger: Any | None = None,
) -> tuple[DesktopCommandSkill, ...]:
    """Build the default natural-language desktop command handlers."""

    return (
        CaptureScreenshotCommandSkill(desktop_control=desktop_control, logger=logger),
        ReadClipboardCommandSkill(desktop_control=desktop_control, logger=logger),
        WriteClipboardCommandSkill(desktop_control=desktop_control, logger=logger),
        TypeTextCommandSkill(desktop_control=desktop_control, logger=logger),
        PressKeyCommandSkill(desktop_control=desktop_control, logger=logger),
        OpenApplicationCommandSkill(desktop_control=desktop_control, logger=logger),
        CloseApplicationCommandSkill(desktop_control=desktop_control, logger=logger),
        ListWindowsCommandSkill(desktop_control=desktop_control, logger=logger),
        FocusWindowCommandSkill(desktop_control=desktop_control, logger=logger),
    )


class DesktopCommandPipeline:
    """Resolve and execute natural-language desktop commands."""

    def __init__(
        self,
        *,
        executor: SkillExecutor,
        intent_analyzer: IntentAnalyzer | None = None,
        router: Router | None = None,
        logger: Any | None = None,
    ) -> None:
        self.executor = executor
        self.intent_analyzer = intent_analyzer or IntentAnalyzer(logger=logger)
        self.router = router or IntentRouter(logger=logger)
        self.logger = logger

    def match(self, request: SkillRequest) -> DesktopCommandMatch | None:
        """Return the best matching desktop command for the supplied request."""

        classification = self._resolve_classification(request)
        route = self._resolve_route(request, classification)
        best = self.executor.match_best(request)
        if best is None:
            return None

        skill, match = best
        confidence = self._adjust_confidence(match.confidence, classification, route)
        if confidence < self._minimum_confidence(route):
            return None

        return DesktopCommandMatch(
            command_name=skill.name,
            confidence=confidence,
            reason=match.reason or "matched natural-language desktop command",
            intent=classification.intent.value,
            route=route.name,
        )

    def execute(self, request: SkillRequest) -> SkillResult | None:
        """Execute the best matching desktop command for the supplied request."""

        classification = self._resolve_classification(request)
        route = self._resolve_route(request, classification)
        best = self.executor.match_best(request)
        if best is None:
            return None

        skill, match = best
        confidence = self._adjust_confidence(match.confidence, classification, route)
        minimum_confidence = self._minimum_confidence(route)
        if confidence < minimum_confidence:
            return None

        result = skill.execute(request)
        _emit_log(
            self.logger,
            "info",
            "Executed desktop command",
            command=skill.name,
            confidence=confidence,
            intent=classification.intent.value,
            route=route.name,
            handled=result.handled,
        )
        return SkillResult(
            skill_name=result.skill_name,
            handled=result.handled,
            message=result.message,
            data=dict(result.data),
            confidence=confidence,
        )

    def _resolve_classification(self, request: SkillRequest) -> IntentClassification:
        """Resolve the request classification from metadata or the shared analyzer."""

        metadata = request.metadata
        intent_value = metadata.get("intent")
        if isinstance(intent_value, str):
            try:
                intent = IntentType(intent_value)
            except ValueError:
                intent = None
            if intent is not None:
                return IntentClassification(
                    intent=intent,
                    confidence=float(metadata.get("intent_confidence", 0.0)),
                    reason=metadata.get("intent_reason"),
                    matched_keywords=tuple(metadata.get("intent_matched_keywords", ())),
                )
        return self.intent_analyzer.analyze(request.text)

    def _resolve_route(self, request: SkillRequest, classification: IntentClassification) -> ModuleRoute:
        """Resolve the request route from metadata or the shared router."""

        metadata = request.metadata
        route_name = request.route or metadata.get("route_name") or metadata.get("route")
        if isinstance(route_name, str) and route_name:
            return ModuleRoute(
                name=route_name,
                confidence=float(metadata.get("route_confidence", classification.confidence)),
                reason=metadata.get("route_reason"),
                metadata={"intent": classification.intent.value},
            )
        return self.router.route(classification)

    def _minimum_confidence(self, route: ModuleRoute) -> float:
        """Mirror the Brain routing thresholds for direct desktop execution."""

        return 0.65 if route.name == "AI" else 0.35

    def _adjust_confidence(
        self,
        confidence: float,
        classification: IntentClassification,
        route: ModuleRoute,
    ) -> float:
        """Adjust command confidence using the shared Brain routing context."""

        adjusted = confidence
        if classification.intent == IntentType.COMMAND:
            adjusted += 0.05
        elif classification.intent == IntentType.QUESTION:
            adjusted -= 0.02
        elif classification.intent == IntentType.UNKNOWN:
            adjusted -= 0.03

        if route.name == "Skills":
            adjusted += 0.03
        elif route.name == "Automation":
            adjusted += 0.02

        return max(0.0, min(0.99, adjusted))


@dataclass(slots=True)
class DesktopCommandServices:
    """Container for the natural-language desktop command runtime services."""

    registry: SkillRegistry
    executor: SkillExecutor
    pipeline: DesktopCommandPipeline


def build_desktop_command_services(
    *,
    desktop_control: DesktopControlService,
    intent_analyzer: IntentAnalyzer | None = None,
    router: Router | None = None,
    registry: SkillRegistry | None = None,
    executor: SkillExecutor | None = None,
    logger: Any | None = None,
) -> DesktopCommandServices:
    """Build the natural-language desktop command runtime services."""

    resolved_registry = registry or SkillRegistry(logger=logger)
    resolved_executor = executor or SkillExecutor(registry=resolved_registry, logger=logger)
    for skill in build_desktop_command_skills(desktop_control=desktop_control, logger=logger):
        resolved_registry.register(skill)
    pipeline = DesktopCommandPipeline(
        executor=resolved_executor,
        intent_analyzer=intent_analyzer,
        router=router,
        logger=logger,
    )
    _emit_log(logger, "info", "Built desktop command services", commands=resolved_registry.count())
    return DesktopCommandServices(
        registry=resolved_registry,
        executor=resolved_executor,
        pipeline=pipeline,
    )


def register_desktop_command_services(
    container: DependencyRegistrar,
    services: DesktopCommandServices,
    *,
    logger: Any | None = None,
) -> DesktopCommandServices:
    """Register desktop command runtime services in the dependency container."""

    container.register_instance("desktop_command_registry", services.registry)
    container.register_instance("desktop_command_executor", services.executor)
    container.register_instance("desktop_command_pipeline", services.pipeline)
    container.register_instance("natural_language_command_pipeline", services.pipeline)
    _emit_log(logger, "info", "Registered desktop command services in container")
    return services


__all__ = [
    "DesktopCommandMatch",
    "DesktopCommandPipeline",
    "DesktopCommandServices",
    "build_desktop_command_services",
    "build_desktop_command_skills",
    "register_desktop_command_services",
]
