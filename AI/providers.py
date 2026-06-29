"""Provider interfaces and implementations for the NARVIS Brain subsystem."""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar
from urllib import error, request

T = TypeVar("T")


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


class ProviderError(Exception):
    """Base exception for provider failures."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request exceeds its timeout."""


class ProviderRateLimitError(ProviderError):
    """Raised when a provider rate-limit is hit."""


@dataclass(slots=True)
class ProviderUsage:
    """Tracks token usage and cost for provider calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0


@dataclass(slots=True)
class ProviderResponse:
    """Normalized provider response object."""

    content: str
    provider_name: str
    model: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    is_fallback: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    """Abstract interface for AI providers."""

    name: str = "base"

    def __init__(self, logger: Any | None = None, timeout_seconds: int = 20, max_retries: int = 3) -> None:
        """Initialize shared provider state."""
        self.logger = logger
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.request_count = 0
        self.total_cost_usd = 0.0
        self.last_error: str | None = None

    @abstractmethod
    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        context: list[Any] | None = None,
    ) -> ProviderResponse:
        """Generate a response using a chat-completion-style payload."""

    async def generate_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        context: list[Any] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
    ) -> str:
        """Generate a response from a single prompt string."""
        messages = self._build_messages(prompt=prompt, system_prompt=system_prompt, context=context)
        response = await self.complete_chat(
            messages,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            context=context,
        )
        return response.content

    async def stream_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        context: list[Any] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Yield streamed response chunks for the supplied prompt."""
        response = await self.complete_chat(
            self._build_messages(prompt=prompt, system_prompt=system_prompt, context=context),
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            context=context,
        )
        if response.content:
            yield response.content

    def get_metrics(self) -> dict[str, Any]:
        """Return the current provider metrics."""
        return {
            "provider": self.name,
            "request_count": self.request_count,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "last_error": self.last_error,
        }

    def _build_messages(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        context: list[Any] | None = None,
    ) -> list[dict[str, str]]:
        """Build a chat message list from a prompt and optional history."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for item in context or []:
            messages.append(self._coerce_message(item))
        messages.append({"role": "user", "content": prompt})
        return messages

    def _coerce_message(self, item: Any) -> dict[str, str]:
        """Convert arbitrary history entries into provider-compatible messages."""
        if isinstance(item, dict) and "content" in item:
            role = str(item.get("role", "user")).strip().lower()
            return {"role": self._normalize_role(role), "content": str(item["content"])}
        if hasattr(item, "role") and hasattr(item, "content"):
            return {
                "role": self._normalize_role(str(getattr(item, "role"))),
                "content": str(getattr(item, "content")),
            }
        return {"role": "user", "content": str(item)}

    def _normalize_role(self, role: str) -> str:
        """Normalize role names to chat completion values."""
        if role in {"assistant", "system", "user"}:
            return role
        return "user"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using a simple word-based heuristic."""
        return max(1, len(text.split()))

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: str | None = None) -> float:
        """Estimate a lightweight cost for provider usage."""
        normalized_model = (model or "").lower()
        if "gpt" in normalized_model or "o4" in normalized_model:
            price_per_1k = 0.003
        elif "claude" in normalized_model:
            price_per_1k = 0.0035
        elif "gemini" in normalized_model:
            price_per_1k = 0.0025
        else:
            price_per_1k = 0.0015
        return round((prompt_tokens + completion_tokens) * price_per_1k / 1000, 6)

    def _update_metrics(self, usage: ProviderUsage) -> None:
        """Update request and cost metrics after a response."""
        self.request_count += 1
        self.total_cost_usd += usage.cost_usd

    def _log(self, level: str, message: str, **context: Any) -> None:
        """Log provider events through the configured logger."""
        _emit_log(self.logger, level, message, **context)

    async def _request_with_retry(self, request_fn: Callable[[], Awaitable[T]]) -> T:
        """Execute a request with retries and graceful error handling."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await asyncio.wait_for(request_fn(), timeout=self.timeout_seconds)
            except ProviderRateLimitError as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    raise
                delay = min(30, 2**attempt)
                self._log("warning", "Rate limited by provider; retrying", attempt=attempt + 1, delay=delay)
                await asyncio.sleep(delay)
            except asyncio.TimeoutError as exc:
                last_error = ProviderTimeoutError(str(exc))
                if attempt == self.max_retries - 1:
                    raise last_error
                self._log("warning", "Provider request timed out; retrying", attempt=attempt + 1)
                await asyncio.sleep(1)
            except ProviderError as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    raise
                self._log("warning", "Provider request failed; retrying", attempt=attempt + 1, error=str(exc))
                await asyncio.sleep(1)
            except Exception as exc:  # pragma: no cover - defensive handling
                last_error = ProviderError(str(exc))
                if attempt == self.max_retries - 1:
                    raise last_error
                self._log(
                    "warning",
                    "Provider request encountered an unexpected error; retrying",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                await asyncio.sleep(1)
        if last_error is not None:
            raise last_error
        raise ProviderError("Provider request failed")

    async def _post_json_request(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        rate_limit_message: str,
    ) -> dict[str, Any]:
        """Perform a JSON POST request on a worker thread."""

        def _request() -> dict[str, Any]:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw or "{}")
            except error.HTTPError as exc:
                if exc.code == 429:
                    raise ProviderRateLimitError(rate_limit_message) from exc
                raise ProviderError(str(exc)) from exc
            except error.URLError as exc:
                raise ProviderTimeoutError(str(exc)) from exc
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Invalid JSON response from {self.name}") from exc

        return await asyncio.to_thread(_request)

    def _build_usage(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None,
        started_at: float,
    ) -> ProviderUsage:
        """Build a usage object and update provider metrics."""
        usage = ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=self._estimate_cost(prompt_tokens, completion_tokens, model=model),
            latency_seconds=round(perf_counter() - started_at, 6),
        )
        self._update_metrics(usage)
        return usage

    def _build_fallback_response(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        notice: str | None = None,
    ) -> ProviderResponse:
        """Provide a deterministic fallback response when a provider is unavailable."""
        latest_user_message = next(
            (message["content"] for message in reversed(messages) if message.get("role") == "user"),
            "",
        )
        content = (
            f"{notice or f'{self.name} provider unavailable; using local fallback.'}\n"
            f"System prompt: {system_prompt or 'You are NARVIS.'}\n"
            f"Latest request: {latest_user_message or 'No request provided.'}"
        )
        usage = ProviderUsage(
            prompt_tokens=self._estimate_tokens(json.dumps(messages)),
            completion_tokens=self._estimate_tokens(content),
            total_tokens=self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content),
            cost_usd=0.0,
            latency_seconds=0.0,
        )
        return ProviderResponse(
            content=content,
            provider_name=self.name,
            model=model,
            usage=usage,
            is_fallback=True,
        )


class OpenAIProvider(Provider):
    """OpenAI-compatible provider implementation."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        logger: Any | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 3,
    ) -> None:
        """Initialize the OpenAI provider configuration."""
        super().__init__(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        context: list[Any] | None = None,
    ) -> ProviderResponse:
        """Generate a chat response using the OpenAI-compatible API."""
        if not self.api_key:
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                notice="OpenAI API key not configured; using local fallback.",
            )

        resolved_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2 if temperature is None else temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            self._log("warning", "Streaming requested for OpenAI; falling back to buffered response")

        async def _request() -> ProviderResponse:
            started_at = perf_counter()
            data = await self._post_json_request(
                url=self.base_url,
                payload=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                rate_limit_message="OpenAI rate limit exceeded",
            )
            choices = data.get("choices", [])
            if not choices:
                raise ProviderError("OpenAI returned no choices")
            content = self._extract_openai_content(choices[0].get("message", {}))
            usage_payload = data.get("usage", {})
            prompt_tokens = int(usage_payload.get("prompt_tokens", self._estimate_tokens(json.dumps(messages))))
            completion_tokens = int(usage_payload.get("completion_tokens", self._estimate_tokens(content)))
            usage = self._build_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=resolved_model,
                started_at=started_at,
            )
            return ProviderResponse(
                content=content,
                provider_name=self.name,
                model=resolved_model,
                usage=usage,
                is_fallback=False,
                metadata={"stream_requested": stream},
            )

        try:
            return await self._request_with_retry(_request)
        except ProviderError as exc:
            self.last_error = str(exc)
            self._log("warning", "OpenAI request failed; using fallback response", error=str(exc))
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=resolved_model,
                notice="OpenAI request failed; using local fallback.",
            )

    def _extract_openai_content(self, message: dict[str, Any]) -> str:
        """Extract content from an OpenAI chat completion message payload."""
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "".join(parts)
        return str(content)


class GeminiProvider(Provider):
    """Google Gemini provider implementation."""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        logger: Any | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 3,
    ) -> None:
        """Initialize the Gemini provider configuration."""
        super().__init__(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
        self.base_url = os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        )

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        context: list[Any] | None = None,
    ) -> ProviderResponse:
        """Generate a chat response using the Gemini API."""
        resolved_model = model or "gemini-2.0-flash"
        if not self.api_key:
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=resolved_model,
                notice="Gemini API key not configured; using local fallback.",
            )

        if stream:
            self._log("warning", "Streaming requested for Gemini; falling back to buffered response")

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if message.get("role") == "assistant" else "user",
                    "parts": [{"text": message.get("content", "")}],
                }
                for message in messages
                if message.get("role") != "system"
            ],
            "generationConfig": {
                "temperature": 0.2 if temperature is None else temperature,
            },
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        async def _request() -> ProviderResponse:
            started_at = perf_counter()
            data = await self._post_json_request(
                url=f"{self.base_url}?key={self.api_key}",
                payload=payload,
                headers={"Content-Type": "application/json"},
                rate_limit_message="Gemini rate limit exceeded",
            )
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError("Gemini returned no candidates")
            content = self._extract_gemini_content(candidates[0].get("content", {}))
            usage_payload = data.get("usageMetadata", {})
            prompt_tokens = int(usage_payload.get("promptTokenCount", self._estimate_tokens(json.dumps(messages))))
            completion_tokens = int(usage_payload.get("candidatesTokenCount", self._estimate_tokens(content)))
            usage = self._build_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=resolved_model,
                started_at=started_at,
            )
            return ProviderResponse(
                content=content,
                provider_name=self.name,
                model=resolved_model,
                usage=usage,
                metadata={"stream_requested": stream},
            )

        try:
            return await self._request_with_retry(_request)
        except ProviderError as exc:
            self.last_error = str(exc)
            self._log("warning", "Gemini request failed; using fallback response", error=str(exc))
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=resolved_model,
                notice="Gemini request failed; using local fallback.",
            )

    def _extract_gemini_content(self, content: dict[str, Any]) -> str:
        """Extract text from a Gemini candidate content payload."""
        parts = content.get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))


class ClaudeProvider(Provider):
    """Anthropic Claude provider implementation."""

    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        logger: Any | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 3,
    ) -> None:
        """Initialize the Claude provider configuration."""
        super().__init__(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        context: list[Any] | None = None,
    ) -> ProviderResponse:
        """Generate a chat response using the Anthropic Messages API."""
        resolved_model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        if not self.api_key:
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=resolved_model,
                notice="Anthropic API key not configured; using local fallback.",
            )

        if stream:
            self._log("warning", "Streaming requested for Claude; falling back to buffered response")

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [
                {"role": "assistant" if message.get("role") == "assistant" else "user", "content": message.get("content", "")}
                for message in messages
                if message.get("role") != "system"
            ],
            "max_tokens": max_tokens or 1024,
            "temperature": 0.2 if temperature is None else temperature,
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt

        async def _request() -> ProviderResponse:
            started_at = perf_counter()
            data = await self._post_json_request(
                url=self.base_url,
                payload=payload,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                rate_limit_message="Anthropic rate limit exceeded",
            )
            content_blocks = data.get("content", [])
            if not content_blocks:
                raise ProviderError("Claude returned no content")
            content = "".join(
                str(block.get("text", ""))
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            usage_payload = data.get("usage", {})
            prompt_tokens = int(usage_payload.get("input_tokens", self._estimate_tokens(json.dumps(messages))))
            completion_tokens = int(usage_payload.get("output_tokens", self._estimate_tokens(content)))
            usage = self._build_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=resolved_model,
                started_at=started_at,
            )
            return ProviderResponse(
                content=content,
                provider_name=self.name,
                model=resolved_model,
                usage=usage,
                metadata={"stream_requested": stream},
            )

        try:
            return await self._request_with_retry(_request)
        except ProviderError as exc:
            self.last_error = str(exc)
            self._log("warning", "Claude request failed; using fallback response", error=str(exc))
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=resolved_model,
                notice="Claude request failed; using local fallback.",
            )


class OllamaProvider(Provider):
    """Local Ollama provider implementation."""

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        logger: Any | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 3,
    ) -> None:
        """Initialize the Ollama provider configuration."""
        super().__init__(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        context: list[Any] | None = None,
    ) -> ProviderResponse:
        """Generate a chat response using the Ollama chat API."""
        resolved_model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        payload_messages = list(messages)
        if system_prompt and not any(message.get("role") == "system" for message in payload_messages):
            payload_messages.insert(0, {"role": "system", "content": system_prompt})

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": payload_messages,
            "stream": False,
            "options": {"temperature": 0.2 if temperature is None else temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        if stream:
            self._log("warning", "Streaming requested for Ollama; falling back to buffered response")

        async def _request() -> ProviderResponse:
            started_at = perf_counter()
            data = await self._post_json_request(
                url=f"{self.base_url.rstrip('/')}/api/chat",
                payload=payload,
                headers={"Content-Type": "application/json"},
                rate_limit_message="Ollama rate limit exceeded",
            )
            message = data.get("message", {})
            content = str(message.get("content", ""))
            if not content:
                raise ProviderError("Ollama returned no message content")
            prompt_tokens = self._estimate_tokens(json.dumps(payload_messages))
            completion_tokens = self._estimate_tokens(content)
            usage = self._build_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=resolved_model,
                started_at=started_at,
            )
            return ProviderResponse(
                content=content,
                provider_name=self.name,
                model=resolved_model,
                usage=usage,
                metadata={"stream_requested": stream},
            )

        try:
            return await self._request_with_retry(_request)
        except ProviderError as exc:
            self.last_error = str(exc)
            self._log("warning", "Ollama request failed; using fallback response", error=str(exc))
            return self._build_fallback_response(
                messages,
                system_prompt=system_prompt,
                model=resolved_model,
                notice="Ollama request failed; using local fallback.",
            )


class FallbackProvider(Provider):
    """Wrap multiple providers and attempt failover in order."""

    name = "fallback"

    def __init__(self, providers: list[Provider], logger: Any | None = None) -> None:
        """Initialize the fallback chain."""
        super().__init__(logger=logger)
        self.providers = providers

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        context: list[Any] | None = None,
    ) -> ProviderResponse:
        """Try each provider in order until one succeeds."""
        last_error: Exception | None = None
        for provider in self.providers:
            try:
                response = await provider.complete_chat(
                    messages,
                    system_prompt=system_prompt,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    context=context,
                )
                if response.content:
                    return response
            except Exception as exc:  # pragma: no cover - defensive handling
                last_error = exc
                self._log("warning", "Provider failed; trying next provider", provider=provider.name, error=str(exc))
        if last_error is not None:
            raise ProviderError(str(last_error))
        raise ProviderError("No providers available")


class ProviderFactory:
    """Factory responsible for constructing provider instances."""

    @staticmethod
    def create_default(
        provider_name: str | None = None,
        logger: Any | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 3,
    ) -> Provider:
        """Create the default AI provider based on configuration or environment."""
        ProviderFactory._load_environment()
        name = (provider_name or os.getenv("NARVIS_PROVIDER", "openai")).strip().lower()

        if name == "openai":
            return OpenAIProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        if name == "gemini":
            return GeminiProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        if name == "claude":
            return ClaudeProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        if name == "ollama":
            return OllamaProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)

        providers: list[Provider] = [
            OpenAIProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries),
        ]
        if os.getenv("GOOGLE_API_KEY"):
            providers.append(GeminiProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries))
        if os.getenv("ANTHROPIC_API_KEY"):
            providers.append(ClaudeProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries))
        if os.getenv("NARVIS_ENABLE_OLLAMA_FALLBACK", "0") == "1":
            providers.append(OllamaProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries))
        if len(providers) == 1:
            return providers[0]
        return FallbackProvider(providers, logger=logger)

    @staticmethod
    def _load_environment() -> None:
        """Load `.env` values into the process environment if present."""
        candidate_paths = [
            Path(__file__).resolve().parent.parent / ".env",
            Path.cwd() / ".env",
            Path.home() / ".env",
        ]
        for candidate in candidate_paths:
            if not candidate.exists():
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for raw_line in lines:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
