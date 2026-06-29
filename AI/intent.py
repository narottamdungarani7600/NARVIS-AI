"""Intent classification abstractions for the NARVIS Brain subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


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


class IntentType(str, Enum):
    """Standard intent categories used by the Brain subsystem."""

    UNKNOWN = "unknown"
    GREETING = "greeting"
    QUESTION = "question"
    COMMAND = "command"
    TASK = "task"
    STATUS = "status"
    HELP = "help"


@dataclass(slots=True)
class IntentClassification:
    """Structured result of intent classification."""

    intent: IntentType
    confidence: float
    reason: str | None = None
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)


class IntentClassifier(Protocol):
    """Protocol for intent classification services."""

    def classify(self, text: str) -> IntentClassification:
        """Classify a user-provided text input into an intent."""


class BaseIntentClassifier(ABC):
    """Abstract base class for deterministic intent classifiers."""

    @abstractmethod
    def classify(self, text: str) -> IntentClassification:
        """Classify text into an intent and confidence score."""


class RuleBasedIntentClassifier(BaseIntentClassifier):
    """Deterministic intent classifier based on lightweight heuristics."""

    def __init__(
        self,
        keywords: dict[IntentType, tuple[str, ...]] | None = None,
        logger: Any | None = None,
    ) -> None:
        """Initialize the classifier with optional keyword overrides."""
        self.logger = logger
        self._keywords: dict[IntentType, tuple[str, ...]] = keywords or {
            IntentType.GREETING: ("hello", "hi", "hey", "greetings", "good morning", "good evening"),
            IntentType.QUESTION: ("what", "why", "how", "when", "where", "who", "which", "can you", "could you"),
            IntentType.COMMAND: ("run", "execute", "start", "stop", "open", "close", "launch", "turn on", "turn off"),
            IntentType.TASK: ("task", "job", "work", "process", "build", "create", "implement", "make"),
            IntentType.STATUS: ("status", "state", "health", "condition", "check", "uptime"),
            IntentType.HELP: ("help", "assist", "support", "guide", "how do i"),
        }

    def classify(self, text: str) -> IntentClassification:
        """Return the best matching intent based on keyword matches."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        normalized = self._normalize(text)
        if not normalized:
            return IntentClassification(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                reason="empty input",
            )

        scores: dict[IntentType, int] = {}
        matched: dict[IntentType, list[str]] = {}
        for intent, keywords in self._keywords.items():
            for keyword in keywords:
                score = self._keyword_score(normalized, keyword)
                if score <= 0:
                    continue
                scores[intent] = scores.get(intent, 0) + score
                matched.setdefault(intent, []).append(keyword)

        if normalized.endswith("?"):
            scores[IntentType.QUESTION] = scores.get(IntentType.QUESTION, 0) + 1
            matched.setdefault(IntentType.QUESTION, []).append("?")

        if not scores:
            result = IntentClassification(
                intent=IntentType.UNKNOWN,
                confidence=0.2,
                reason="no heuristics matched",
            )
            _emit_log(self.logger, "debug", "Intent classified", intent=result.intent.value, confidence=result.confidence)
            return result

        best_intent, best_score = max(scores.items(), key=lambda item: item[1])
        matched_keywords = tuple(dict.fromkeys(matched.get(best_intent, [])))
        confidence = min(0.99, 0.35 + (best_score * 0.12))
        result = IntentClassification(
            intent=best_intent,
            confidence=confidence,
            reason=f"matched {best_score} heuristic point(s)",
            matched_keywords=matched_keywords,
        )
        _emit_log(
            self.logger,
            "debug",
            "Intent classified",
            intent=result.intent.value,
            confidence=result.confidence,
            matched_keywords=", ".join(matched_keywords),
        )
        return result

    def _normalize(self, text: str) -> str:
        """Normalize user input for deterministic matching."""
        return " ".join(text.strip().lower().split())

    def _keyword_score(self, normalized: str, keyword: str) -> int:
        """Return a score contribution for a keyword match."""
        if normalized == keyword:
            return 3
        if normalized.startswith(f"{keyword} "):
            return 2
        if f" {keyword} " in f" {normalized} ":
            return 1
        return 0


class IntentAnalyzer:
    """High-level intent analysis service that wraps a classifier."""

    def __init__(self, classifier: IntentClassifier | None = None, logger: Any | None = None) -> None:
        """Initialize the analyzer with an injected classifier."""
        self.classifier = classifier or RuleBasedIntentClassifier(logger=logger)
        self.logger = logger

    def analyze(self, text: str) -> IntentClassification:
        """Analyze a user message and produce an intent classification."""
        result = self.classifier.classify(text)
        _emit_log(
            self.logger,
            "debug",
            "Analyzed intent",
            intent=result.intent.value,
            confidence=result.confidence,
        )
        return result

    def classify(self, text: str) -> IntentClassification:
        """Alias for :meth:`analyze` for compatibility with existing code."""
        return self.analyze(text)
