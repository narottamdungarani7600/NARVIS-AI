"""Logging abstractions for the Core foundation of NARVIS.

The logger module provides reusable interfaces and a simple implementation
for structured application logging without coupling Core to any specific AI
or runtime mechanism.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Protocol


class LogLevel(str, Enum):
    """Supported log severity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Logger(Protocol):
    """Protocol for a pluggable logger implementation."""

    def log(self, level: LogLevel, message: str, **context: Any) -> None:
        """Write a log entry using the supplied severity and context."""


class BaseLogger(ABC):
    """Abstract base class for logger implementations."""

    def __init__(self, name: str = "narvis") -> None:
        self.name = name

    @abstractmethod
    def log(self, level: LogLevel, message: str, **context: Any) -> None:
        """Emit a log entry."""


class ConsoleLogger(BaseLogger):
    """Simple console-based logger suitable for local development."""

    def log(self, level: LogLevel, message: str, **context: Any) -> None:
        """Write a formatted log message to standard output."""
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        if details:
            print(f"[{level.value}] {self.name}: {message} | {details}")
        else:
            print(f"[{level.value}] {self.name}: {message}")


class NullLogger(BaseLogger):
    """No-op logger used when logging is intentionally disabled."""

    def log(self, level: LogLevel, message: str, **context: Any) -> None:
        """Silently discard log entries."""
        return None
