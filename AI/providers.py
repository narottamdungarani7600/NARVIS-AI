"""Provider interfaces and implementations for the NARVIS Brain subsystem."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request


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


@dataclass(slots=True)
class ProviderResponse:
    """Normalized provider response object."""

    content: str
    provider_name: str
    model: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    is_fallback: bool = False


class Provider(ABC):
    """Abstract interface for AI providers."""

    name: str = "base"

    def __init__(self, logger: logging.Logger | None = None, timeout_seconds: int = 20, max_retries: int = 3) -> None:
        self.logger = logger or logging.getLogger("narvis.providers")
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
        messages = self._build_messages(prompt=prompt, system_prompt=system_prompt, context=context)
        response = await self.complete_chat(
            messages,
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
        }

    def _build_messages(self, *, prompt: str, system_prompt: str | None = None, context: list[Any] | None = None) -> list[dict[str, str]]:
        """Build a chat message list from a prompt and optional history."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if context:
            for item in context:
                if isinstance(item, dict) and "role" in item and "content" in item:
                    messages.append({"role": str(item["role"]), "content": str(item["content"])})
                else:
                    messages.append({"role": "user", "content": str(item)})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using a simple word-based heuristic."""
        return max(1, len(text.split()))

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: str | None = None) -> float:
        """Estimate a lightweight cost for provider usage."""
        price_per_1k = 0.003 if model and "gpt" in model.lower() else 0.002
        return round((prompt_tokens + completion_tokens) * price_per_1k / 1000, 6)

    def _update_metrics(self, usage: ProviderUsage) -> None:
        """Update request and cost metrics after a response."""
        self.request_count += 1
        self.total_cost_usd += usage.cost_usd

    def _log(self, level: str, message: str, **context: Any) -> None:
        """Log provider events through the configured logger."""
        self.logger.log(level.upper(), message, extra=context)

    async def _request_with_retry(self, request_fn: Any) -> Any:
        """Execute a request with retries and graceful error handling."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await asyncio.wait_for(request_fn(), timeout=self.timeout_seconds)
            except ProviderRateLimitError as error:
                last_error = error
                if attempt == self.max_retries - 1:
                    raise
                delay = min(30, 2**attempt)
                self._log("warning", f"Rate limited by provider; retrying in {delay}s", attempt=attempt + 1)
                await asyncio.sleep(delay)
            except TimeoutError as error:
                last_error = ProviderTimeoutError(str(error))
                if attempt == self.max_retries - 1:
                    raise last_error
                self._log("warning", f"Provider request timed out; retrying", attempt=attempt + 1)
                await asyncio.sleep(1)
            except ProviderError as error:
                last_error = error
                if attempt == self.max_retries - 1:
                    raise
                self._log("warning", f"Provider request failed; retrying", attempt=attempt + 1, error=str(error))
                await asyncio.sleep(1)
            except Exception as error:  # pragma: no cover - defensive handling
                last_error = ProviderError(str(error))
                if attempt == self.max_retries - 1:
                    raise last_error
                self._log("warning", f"Provider request encountered an unexpected error; retrying", attempt=attempt + 1, error=str(error))
                await asyncio.sleep(1)
        if last_error is not None:
            raise last_error
        raise ProviderError("Provider request failed")


class OpenAIProvider(Provider):
    """OpenAI-compatible provider implementation."""

    name = "openai"

    def __init__(self, api_key: str | None = None, logger: logging.Logger | None = None, timeout_seconds: int = 20, max_retries: int = 3) -> None:
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
            return self._fallback_response(messages, system_prompt=system_prompt, model=model)

        payload = {
            "model": model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": messages,
            "stream": stream,
            "temperature": temperature if temperature is not None else 0.2,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        async def _request() -> ProviderResponse:
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            request_data = json.dumps(payload).encode("utf-8")
            req = request.Request(self.base_url, data=request_data, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    data = json.loads(raw)
            except error.HTTPError as exc:
                if exc.code == 429:
                    raise ProviderRateLimitError("OpenAI rate limit exceeded") from exc
                raise ProviderError(str(exc)) from exc
            except error.URLError as exc:
                raise ProviderTimeoutError(str(exc)) from exc

            if stream:
                content = ""
            else:
                choices = data.get("choices", [])
                if not choices:
                    raise ProviderError("OpenAI returned no choices")
                content = choices[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                prompt_tokens = int(usage.get("prompt_tokens", self._estimate_tokens(json.dumps(messages))))
                completion_tokens = int(usage.get("completion_tokens", self._estimate_tokens(str(content))))
                total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
                cost = self._estimate_cost(prompt_tokens, completion_tokens, model=payload["model"])
                response_obj = ProviderResponse(
                    content=str(content),
                    provider_name=self.name,
                    model=payload["model"],
                    usage=ProviderUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cost_usd=cost,
                    ),
                    is_fallback=False,
                )
                self._update_metrics(response_obj.usage)
                return response_obj
            return ProviderResponse(content="", provider_name=self.name, model=payload["model"], is_fallback=False)

        try:
            response = await self._request_with_retry(_request)
        except ProviderError as exc:
            self.last_error = str(exc)
            self._log("warning", "OpenAI request failed; using fallback response", error=str(exc))
            return self._fallback_response(messages, system_prompt=system_prompt, model=model)
        return response

    def _fallback_response(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, model: str | None = None) -> ProviderResponse:
        """Provide a deterministic fallback response."""
        content = f"NARVIS fallback response. System: {system_prompt or 'You are NARVIS.'}"
        usage = ProviderUsage(prompt_tokens=self._estimate_tokens(json.dumps(messages)), completion_tokens=self._estimate_tokens(content), total_tokens=self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content), cost_usd=0.0)
        return ProviderResponse(content=content, provider_name=self.name, model=model, usage=usage, is_fallback=True)


class GeminiProvider(Provider):
    """Google Gemini provider implementation."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, logger: logging.Logger | None = None, timeout_seconds: int = 20, max_retries: int = 3) -> None:
        super().__init__(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
        self.base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent")

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
        if not self.api_key:
            return self._fallback_response(messages, system_prompt=system_prompt, model=model)

        payload = {
            "contents": [{"parts": [{"text": msg.get("content", "")}] } for msg in messages if msg.get("role") != "system"],
            "generationConfig": {"temperature": temperature if temperature is not None else 0.2},
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        async def _request() -> ProviderResponse:
            url = f"{self.base_url}?key={self.api_key}"
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    data = json.loads(raw)
            except error.HTTPError as exc:
                if exc.code == 429:
                    raise ProviderRateLimitError("Gemini rate limit exceeded") from exc
                raise ProviderError(str(exc)) from exc
            except error.URLError as exc:
                raise ProviderTimeoutError(str(exc)) from exc

            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError("Gemini returned no candidates")
            content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            usage = data.get("usageMetadata", {})
            prompt_tokens = int(usage.get("promptTokenCount", self._estimate_tokens(json.dumps(messages))))
            completion_tokens = int(usage.get("candidatesTokenCount", self._estimate_tokens(str(content))))
            total_tokens = int(usage.get("totalTokenCount", prompt_tokens + completion_tokens))
            response_obj = ProviderResponse(
                content=str(content),
                provider_name=self.name,
                model=model or "gemini-2.0-flash",
                usage=ProviderUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens, cost_usd=self._estimate_cost(prompt_tokens, completion_tokens, model=model or "gemini-2.0-flash")),
                is_fallback=False,
            )
            self._update_metrics(response_obj.usage)
            return response_obj

        try:
            response = await self._request_with_retry(_request)
        except ProviderError as exc:
            self.last_error = str(exc)
            self._log("warning", "Gemini request failed; using fallback response", error=str(exc))
            return self._fallback_response(messages, system_prompt=system_prompt, model=model)
        return response

    def _fallback_response(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, model: str | None = None) -> ProviderResponse:
        """Provide a deterministic fallback response."""
        content = f"NARVIS fallback response. System: {system_prompt or 'You are NARVIS.'}"
        usage = ProviderUsage(prompt_tokens=self._estimate_tokens(json.dumps(messages)), completion_tokens=self._estimate_tokens(content), total_tokens=self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content), cost_usd=0.0)
        return ProviderResponse(content=content, provider_name=self.name, model=model, usage=usage, is_fallback=True)


class ClaudeProvider(Provider):
    """Anthropic Claude provider implementation."""

    name = "claude"

    def __init__(self, api_key: str | None = None, logger: logging.Logger | None = None, timeout_seconds: int = 20, max_retries: int = 3) -> None:
        super().__init__(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")

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
        """Prepare Claude support for future expansion."""
        return self._fallback_response(messages, system_prompt=system_prompt, model=model)

    def _fallback_response(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, model: str | None = None) -> ProviderResponse:
        """Provide a deterministic fallback response."""
        content = f"Claude provider is ready for configuration. System: {system_prompt or 'You are NARVIS.'}"
        usage = ProviderUsage(prompt_tokens=self._estimate_tokens(json.dumps(messages)), completion_tokens=self._estimate_tokens(content), total_tokens=self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content), cost_usd=0.0)
        return ProviderResponse(content=content, provider_name=self.name, model=model, usage=usage, is_fallback=True)


class OllamaProvider(Provider):
    """Local Ollama provider implementation."""

    name = "ollama"

    def __init__(self, base_url: str | None = None, logger: logging.Logger | None = None, timeout_seconds: int = 20, max_retries: int = 3) -> None:
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
        """Prepare Ollama support for future deployment."""
        return self._fallback_response(messages, system_prompt=system_prompt, model=model)

    def _fallback_response(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, model: str | None = None) -> ProviderResponse:
        """Provide a deterministic fallback response."""
        content = f"Ollama provider is ready for local inference. System: {system_prompt or 'You are NARVIS.'}"
        usage = ProviderUsage(prompt_tokens=self._estimate_tokens(json.dumps(messages)), completion_tokens=self._estimate_tokens(content), total_tokens=self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content), cost_usd=0.0)
        return ProviderResponse(content=content, provider_name=self.name, model=model, usage=usage, is_fallback=True)


class FallbackProvider(Provider):
    """Wraps multiple providers and attempts failover in order."""

    def __init__(self, providers: list[Provider], logger: logging.Logger | None = None) -> None:
        super().__init__(logger=logger)
        self.providers = providers
        self.name = "fallback"

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
                return await provider.complete_chat(
                    messages,
                    system_prompt=system_prompt,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    context=context,
                )
            except Exception as exc:  # pragma: no cover - defensive handling
                last_error = exc
                self._log("warning", f"Provider {provider.name} failed; trying next provider", error=str(exc))
        if last_error is not None:
            raise ProviderError(str(last_error))
        raise ProviderError("No providers available")


class ProviderFactory:
    """Factory responsible for constructing provider instances."""

    @staticmethod
    def create_default(
        provider_name: str | None = None,
        logger: logging.Logger | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 3,
    ) -> Provider:
        """Create the default AI provider based on configuration or environment."""
        ProviderFactory._load_environment()
        name = (provider_name or os.getenv("NARVIS_PROVIDER", "openai")).lower()
        if name == "gemini":
            return GeminiProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        if name == "claude":
            return ClaudeProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)
        if name == "ollama":
            return OllamaProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)

        providers: list[Provider] = [OpenAIProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries)]
        if os.getenv("GOOGLE_API_KEY"):
            providers.append(GeminiProvider(logger=logger, timeout_seconds=timeout_seconds, max_retries=max_retries))
        if len(providers) == 1:
            return providers[0]
        return FallbackProvider(providers, logger=logger)

    @staticmethod
    def _load_environment() -> None:
        """Load .env values into the process environment if present."""
        candidate_paths = [Path(__file__).resolve().parent.parent / ".env", Path.cwd() / ".env", Path.home() / ".env"]
        for candidate in candidate_paths:
            if not candidate.exists():
                continue
            for raw_line in candidate.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
