"""Structured response abstractions for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .context import ConversationContext
from .intent import IntentClassification
from .prompts import PromptBuilder
from .providers import Provider, ProviderError, ProviderResponse, ProviderUsage
from .router import ModuleRoute


def _utc_now() -> datetime:
    """Return the current timestamp in UTC."""
    return datetime.now(timezone.utc)


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


@dataclass(slots=True)
class ResponseGenerationOptions:
    """Runtime generation settings for provider-backed responses."""

    model: str | None = None
    max_tokens: int | None = None
    temperature: float = 0.2
    stream: bool = False


@dataclass(slots=True)
class BrainResponse:
    """Structured response emitted by the Brain engine."""

    message: str
    intent: IntentClassification
    route: ModuleRoute
    context: ConversationContext
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_name: str | None = None
    model: str | None = None
    usage: ProviderUsage | None = None
    is_fallback: bool = False
    generated_at: datetime = field(default_factory=_utc_now)


class ResponseBuilder:
    """Build standardized Brain responses for downstream consumers."""

    def __init__(
        self,
        provider: Provider | None = None,
        prompt_builder: PromptBuilder | None = None,
        options: ResponseGenerationOptions | None = None,
        logger: Any | None = None,
    ) -> None:
        """Initialize the response builder with injected collaborators."""
        self.provider = provider
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.options = options or ResponseGenerationOptions()
        self.logger = logger

    async def generate_provider_response(
        self,
        text: str,
        intent: IntentClassification,
        route: ModuleRoute,
        context: ConversationContext,
        metadata: dict[str, Any] | None = None,
        memory_summary: str | None = None,
        history: list[Any] | None = None,
    ) -> ProviderResponse:
        """Generate a provider response using the configured prompt strategy."""
        if self.provider is None:
            return self._fallback_provider_response(text, intent, route, memory_summary=memory_summary)

        messages = self.prompt_builder.build_messages(
            user_text=text,
            history=history or [],
            memory_summary=memory_summary,
            intent=intent,
            route=route,
            context=context,
            metadata=metadata or {},
        )
        system_prompt = self.prompt_builder.build_system_prompt(
            intent=intent,
            memory_summary=memory_summary,
            route=route,
            context=context,
        )
        try:
            response = await self.provider.complete_chat(
                messages,
                system_prompt=system_prompt,
                model=self.options.model,
                max_tokens=self.options.max_tokens,
                temperature=self.options.temperature,
                stream=self.options.stream,
                context=history or [],
            )
        except ProviderError as exc:
            _emit_log(self.logger, "warning", "Provider raised an error; using local fallback", error=str(exc))
            return self._fallback_provider_response(text, intent, route, memory_summary=memory_summary)
        except Exception as exc:  # pragma: no cover - defensive handling
            _emit_log(self.logger, "warning", "Unexpected provider error; using local fallback", error=str(exc))
            return self._fallback_provider_response(text, intent, route, memory_summary=memory_summary)

        _emit_log(
            self.logger,
            "debug",
            "Generated provider response",
            provider=response.provider_name,
            model=response.model,
            fallback=response.is_fallback,
        )
        return response

    async def generate(
        self,
        text: str,
        intent: IntentClassification,
        route: ModuleRoute,
        context: ConversationContext,
        metadata: dict[str, Any] | None = None,
        memory_summary: str | None = None,
        history: list[Any] | None = None,
    ) -> str:
        """Generate only the response text for compatibility with existing callers."""
        response = await self.generate_provider_response(
            text=text,
            intent=intent,
            route=route,
            context=context,
            metadata=metadata,
            memory_summary=memory_summary,
            history=history,
        )
        return response.content

    def build(
        self,
        text: str,
        intent: IntentClassification,
        route: ModuleRoute,
        context: ConversationContext,
        metadata: dict[str, Any] | None = None,
        message: str | None = None,
        provider_response: ProviderResponse | None = None,
    ) -> BrainResponse:
        """Create a structured response from the supplied processing results."""
        resolved_provider_response = provider_response or self._fallback_provider_response(text, intent, route)
        final_message = message or resolved_provider_response.content
        combined_metadata = dict(metadata or {})
        combined_metadata.setdefault("route_reason", route.reason)
        combined_metadata.setdefault("intent_reason", intent.reason)
        combined_metadata.update(resolved_provider_response.metadata)
        return BrainResponse(
            message=final_message,
            intent=intent,
            route=route,
            context=context,
            metadata=combined_metadata,
            provider_name=resolved_provider_response.provider_name,
            model=resolved_provider_response.model,
            usage=resolved_provider_response.usage,
            is_fallback=resolved_provider_response.is_fallback,
        )

    def _fallback_provider_response(
        self,
        text: str,
        intent: IntentClassification,
        route: ModuleRoute,
        memory_summary: str | None = None,
    ) -> ProviderResponse:
        """Create a deterministic response when no provider is configured."""
        memory_note = f" Memory: {memory_summary}" if memory_summary else ""
        content = (
            f"I understood your request as {intent.intent.value} and routed it to {route.name}."
            f"{memory_note}\n"
            f"Input: {text}"
        )
        return ProviderResponse(
            content=content,
            provider_name="local-fallback",
            usage=ProviderUsage(
                prompt_tokens=max(1, len(text.split())),
                completion_tokens=max(1, len(content.split())),
                total_tokens=max(1, len(text.split())) + max(1, len(content.split())),
                cost_usd=0.0,
                latency_seconds=0.0,
            ),
            is_fallback=True,
        )
