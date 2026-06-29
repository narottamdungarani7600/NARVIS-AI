"""Weather provider abstractions for the NARVIS Internet package.

This module defines reusable interfaces for weather information retrieval and
can later be implemented by REST-based or third-party services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class WeatherReport:
    """Represents a weather report payload."""

    location: str
    condition: str = "unknown"
    temperature_c: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class WeatherProvider(Protocol):
    """Protocol for weather provider services."""

    def fetch(self, location: str) -> WeatherReport:
        """Fetch a weather report for the given location."""


class BaseWeatherProvider(ABC):
    """Abstract base class for weather provider implementations."""

    @abstractmethod
    def fetch(self, location: str) -> WeatherReport:
        """Fetch a weather report for the given location."""


class NullWeatherProvider(BaseWeatherProvider):
    """No-op weather provider used as a placeholder implementation."""

    def fetch(self, location: str) -> WeatherReport:
        """Return an empty weather report."""
        return WeatherReport(location=location)
