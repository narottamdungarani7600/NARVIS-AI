"""Structured response abstractions for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import ConversationContext
from .intent import IntentClassification
from .prompts import PromptBuilder
from .providers import Provider
from .router import ModuleRoute


@dataclass(slots=True)
class BrainResponse:
    """Structured response emitted by the Brain engine."""

    message: str
    intent: IntentClassification
    route: ModuleRoute
    context: ConversationContext
    metadata: dict[str, Any] = field(default_factory=dict)


class ResponseBuilder:
    """Builds standardized Brain responses for downstream consumers."""

    def __init__(self, provider: Provider | None = None, prompt_builder: PromptBuilder | None = None) -> None:
        self.provider = provider
        self.prompt_builder = prompt_builder or PromptBuilder()

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
        """Generate a response using the configured provider and prompt builder."""
        if self.provider is None:
            return self._fallback_response(text, intent, route, memory_summary)
        prompt = self.prompt_builder.build_user_prompt(
            user_text=text,
            history=history or [],
            memory_summary=memory_summary,
            intent=intent,
        )
        system_prompt = self.prompt_builder.build_system_prompt(intent=intent, memory_summary=memory_summary)
        return await self.provider.generate_response(prompt, system_prompt=system_prompt, context=history or [])

    def build(
        self,
        text: str,
        intent: IntentClassification,
        route: ModuleRoute,
        context: ConversationContext,
        metadata: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> BrainResponse:
        """Create a structured response from the supplied processing results."""
        final_message = message or self._fallback_response(text, intent, route)
        return BrainResponse(
            message=final_message,
            intent=intent,
            route=route,
            context=context,
            metadata=metadata or {},
        )

    def _fallback_response(self, text: str, intent: IntentClassification, route: ModuleRoute, memory_summary: str | None = None) -> str:
        """Create a deterministic response when no provider is configured."""
        memory_note = f" Memory: {memory_summary}" if memory_summary else ""
        return (
            f"I understood your request as {intent.intent.value} and routed it to {route.name}."
            f"{memory_note}\n"
            f"Input: {text}"
        )
