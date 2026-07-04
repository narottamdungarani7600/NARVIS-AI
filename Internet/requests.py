"""HTTP client abstractions for the NARVIS Internet package."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Protocol
from urllib import error, request


class HttpClient(Protocol):
    """Protocol for HTTP client implementations."""

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a GET request and return the response payload."""

    def post(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform a POST request and return the response payload."""


class BaseHttpClient(ABC):
    """Abstract base class for HTTP client implementations."""

    @abstractmethod
    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a GET request and return the response payload."""

    @abstractmethod
    def post(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform a POST request and return the response payload."""


class NullHttpClient(BaseHttpClient):
    """No-op HTTP client used as a placeholder implementation."""

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Return an empty response payload."""

        return {"url": url, "status": "not_implemented"}

    def post(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return an empty response payload."""

        return {"url": url, "status": "not_implemented", "payload": payload or {}}


class UrllibHttpClient(BaseHttpClient):
    """Small stdlib-backed HTTP client for JSON-friendly runtime requests."""

    def __init__(self, *, timeout_seconds: float = 6.0, user_agent: str = "NARVIS/1.1") -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Perform a GET request and decode JSON when available."""

        req = request.Request(url, headers=self._headers(headers), method="GET")
        return self._send(req, timeout=timeout)

    def post(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform a POST request and decode JSON when available."""

        data = json.dumps(payload or {}).encode("utf-8")
        req = request.Request(url, data=data, headers=self._headers(headers, has_body=True), method="POST")
        return self._send(req, timeout=timeout)

    def _send(self, req: request.Request, *, timeout: float | None) -> dict[str, Any]:
        """Send a request and normalize the response payload."""

        resolved_timeout = self.timeout_seconds if timeout is None else timeout
        try:
            with request.urlopen(req, timeout=resolved_timeout) as response:
                body = response.read()
                charset = response.headers.get_content_charset("utf-8")
                text = body.decode(charset, errors="replace")
                result = {
                    "url": response.geturl(),
                    "status": getattr(response, "status", 200),
                    "headers": dict(response.headers.items()),
                    "text": text,
                }
                try:
                    result["json"] = json.loads(text)
                except json.JSONDecodeError:
                    pass
                return result
        except error.HTTPError as exc:
            return {"url": req.full_url, "status": exc.code, "error": str(exc)}
        except error.URLError as exc:
            return {"url": req.full_url, "status": "error", "error": str(getattr(exc, "reason", exc))}
        except OSError as exc:
            return {"url": req.full_url, "status": "error", "error": str(exc)}

    def _headers(self, headers: dict[str, str] | None, *, has_body: bool = False) -> dict[str, str]:
        """Build the final request headers for a stdlib HTTP request."""

        resolved = {"User-Agent": self.user_agent, **dict(headers or {})}
        if has_body:
            resolved.setdefault("Content-Type", "application/json")
        return resolved


__all__ = [
    "BaseHttpClient",
    "HttpClient",
    "NullHttpClient",
    "UrllibHttpClient",
]
