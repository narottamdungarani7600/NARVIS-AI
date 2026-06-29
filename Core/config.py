"""Configuration abstractions for the Core foundation of NARVIS.

This module defines reusable configuration types and interfaces that can be
consumed by future Voice, Vision, Memory, and Automation services without
binding them to any specific AI implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class ConfigProvider(Protocol):
    """Protocol describing a generic configuration provider."""

    def load(self) -> None:
        """Load configuration values from a source."""

    def save(self) -> None:
        """Persist configuration values to a source."""

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a configuration value by key."""


@dataclass(slots=True)
class AppConfig:
    """Structured application configuration container for NARVIS Core.

    Attributes:
        app_name: Human-readable application identifier.
        version: Application version string.
        environment: Runtime environment such as development or production.
        data_dir: Directory used for persistent data.
        log_dir: Directory used for log files.
        debug: Enables verbose diagnostic behavior.
        extra: Additional configuration values for future extension.
    """

    app_name: str = "NARVIS"
    version: str = "2.0"
    environment: str = "development"
    data_dir: Path = field(default_factory=lambda: Path("data"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    debug: bool = False
    ai_provider: str = "openai"
    ai_model: str | None = None
    ai_timeout_seconds: int = 20
    ai_max_retries: int = 3
    ai_temperature: float = 0.2
    ai_max_tokens: int = 512
    ai_stream: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Return a value from the additional configuration store."""
        return self.extra.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set an additional configuration value."""
        self.extra[key] = value

    def update(self, **values: Any) -> "AppConfig":
        """Update several configuration values at once."""
        for key, value in values.items():
            setattr(self, key, value)
        return self
