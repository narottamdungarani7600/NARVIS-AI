"""HTTP client abstractions for the NARVIS Internet package.

This module defines reusable interfaces for remote HTTP access and is intended
for future support of REST APIs and backend service integrations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class HttpClient(Protocol):
    """Protocol for HTTP client implementations."""

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a GET request and return the response payload."""

    def post(self, url: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a POST request and return the response payload."""


class BaseHttpClient(ABC):
    """Abstract base class for HTTP client implementations."""

    @abstractmethod
    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a GET request and return the response payload."""

    @abstractmethod
    def post(self, url: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a POST request and return the response payload."""


class NullHttpClient(BaseHttpClient):
    """No-op HTTP client used as a placeholder implementation."""

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Return an empty response payload."""
        return {"url": url, "status": "not_implemented"}

    def post(self, url: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Return an empty response payload."""
        return {"url": url, "status": "not_implemented", "payload": payload or {}}
