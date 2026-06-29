"""Intent classification abstractions for the NARVIS Brain subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


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
    """Deterministic intent classifier based on keyword heuristics."""

    def __init__(self) -> None:
        self._keywords: dict[IntentType, tuple[str, ...]] = {
            IntentType.GREETING: ("hello", "hi", "hey", "greetings", "good morning", "good evening"),
            IntentType.QUESTION: ("what", "why", "how", "when", "where", "who", "can you"),
            IntentType.COMMAND: ("run", "execute", "start", "stop", "open", "close", "launch"),
            IntentType.TASK: ("task", "job", "work", "process", "build", "create"),
            IntentType.STATUS: ("status", "state", "health", "condition", "check"),
            IntentType.HELP: ("help", "assist", "support", "guide"),
        }

    def classify(self, text: str) -> IntentClassification:
        """Return the best matching intent based on keyword matches."""
        normalized = text.strip().lower()
        if not normalized:
            return IntentClassification(intent=IntentType.UNKNOWN, confidence=0.0, reason="empty input")

        scores: list[tuple[IntentType, int]] = []
        for intent, keywords in self._keywords.items():
            matches = sum(1 for keyword in keywords if keyword in normalized)
            if matches:
                scores.append((intent, matches))

        if not scores:
            return IntentClassification(intent=IntentType.UNKNOWN, confidence=0.0, reason="no keywords matched")

        best_intent, best_score = max(scores, key=lambda item: item[1])
        confidence = min(0.99, 0.5 + (best_score * 0.1))
        reason = f"matched {best_score} keyword(s)"
        return IntentClassification(intent=best_intent, confidence=confidence, reason=reason)


class IntentAnalyzer:
    """High-level intent analysis service that wraps a classifier."""

    def __init__(self, classifier: IntentClassifier | None = None) -> None:
        self.classifier = classifier or RuleBasedIntentClassifier()

    def analyze(self, text: str) -> IntentClassification:
        """Analyze a user message and produce an intent classification."""
        return self.classifier.classify(text)

    def classify(self, text: str) -> IntentClassification:
        """Alias for analyze for compatibility with existing code."""
        return self.analyze(text)
