"""Core Brain engine for the NARVIS AI subsystem."""

from __future__ import annotations

import asyncio
from typing import Any

from Core.engine import ExecutionContext
from .context import ConversationContext, InMemoryContextManager
from .conversation import ChatHistoryManager, SessionManager
from .intent import IntentAnalyzer, IntentClassifier, RuleBasedIntentClassifier
from .prompts import PromptBuilder
from .providers import Provider, ProviderFactory
from .response import BrainResponse, ResponseBuilder
from .router import IntentRouter, Router


class BrainEngine:
    """Central orchestration component for the Brain subsystem."""

    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        context_manager: InMemoryContextManager | None = None,
        router: Router | None = None,
        response_builder: ResponseBuilder | None = None,
        provider: Provider | None = None,
        prompt_builder: PromptBuilder | None = None,
        session_manager: SessionManager | None = None,
        chat_history_manager: ChatHistoryManager | None = None,
        short_term_memory: Any | None = None,
        long_term_memory: Any | None = None,
        engine: Any | None = None,
    ) -> None:
        self.intent_classifier = intent_classifier or RuleBasedIntentClassifier()
        self.intent_analyzer = IntentAnalyzer(classifier=self.intent_classifier)
        self.context_manager = context_manager or InMemoryContextManager(
            session_manager=session_manager or SessionManager(),
            chat_history_manager=chat_history_manager or ChatHistoryManager(max_turns=50),
        )
        self.router = router or IntentRouter()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.provider = provider or ProviderFactory.create_default()
        self.response_builder = response_builder or ResponseBuilder(provider=self.provider, prompt_builder=self.prompt_builder)
        self.session_manager = self.context_manager._session_manager
        self.chat_history_manager = self.context_manager._chat_history_manager
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory
        self.engine = engine

    async def process(
        self,
        text: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> BrainResponse:
        """Process a user message and return a structured response."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        self._publish_engine_event("brain.processing", {"text": text, "conversation_id": conversation_id})
        context = self.context_manager.get_or_create(conversation_id=conversation_id, session_id=session_id)
        classification = self.intent_analyzer.analyze(text)
        route = self.router.route(classification)

        self.context_manager.record_turn(context=context, role="user", content=text, metadata=metadata or {})
        self.context_manager.update_context(
            context=context,
            last_intent=classification.intent,
            last_route=route.name,
            metadata={"conversation_id": context.conversation_id, "session_id": context.session_id},
        )

        history = self.context_manager.get_history(context.conversation_id)
        memory_summary = await self._build_memory_summary(context)
        generated_message = await self.response_builder.generate(
            text=text,
            intent=classification,
            route=route,
            context=context,
            metadata={"conversation_id": context.conversation_id, "session_id": context.session_id},
            memory_summary=memory_summary,
            history=history,
        )

        self.context_manager.record_turn(context=context, role="assistant", content=generated_message, metadata={"route": route.name})
        self._publish_engine_event("brain.completed", {"conversation_id": context.conversation_id, "route": route.name})
        return self.response_builder.build(
            text=text,
            intent=classification,
            route=route,
            context=context,
            metadata={"conversation_id": context.conversation_id, "session_id": context.session_id},
            message=generated_message,
        )

    async def chat(
        self,
        text: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> BrainResponse:
        """Process a chat message using the Brain engine."""
        return await self.process(text=text, conversation_id=conversation_id, metadata=metadata, session_id=session_id)

    async def think(
        self,
        text: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> BrainResponse:
        """Perform a reasoning-oriented pass over the supplied text."""
        return await self.process(text=text, conversation_id=conversation_id, metadata=metadata, session_id=session_id)

    async def remember(self, key: str, value: Any, importance: float = 0.0, metadata: dict[str, Any] | None = None) -> bool:
        """Persist a value to the configured memory layer."""
        if self.long_term_memory is not None:
            self.long_term_memory.store(key, value, importance=importance, metadata=metadata or {})
            if self.short_term_memory is not None:
                self.short_term_memory.store(key, value, importance=importance, metadata=metadata or {})
            return True
        if self.short_term_memory is not None:
            self.short_term_memory.store(key, value, importance=importance, metadata=metadata or {})
            return True
        return False

    async def forget(self, key: str) -> bool:
        """Delete a remembered value from the configured memory layer."""
        removed = False
        if self.long_term_memory is not None:
            entry = self.long_term_memory.recall(key)
            if entry is not None:
                self.long_term_memory.repository.delete(key)
                removed = True
        if self.short_term_memory is not None:
            entry = self.short_term_memory.recall(key)
            if entry is not None:
                self.short_term_memory.repository.delete(key)
                removed = True
        return removed

    async def summarize(self, conversation_id: str | None = None, limit: int = 10) -> str:
        """Summarize the active conversation history."""
        context = self.context_manager.get_or_create(conversation_id=conversation_id)
        history = self.context_manager.get_history(context.conversation_id)
        recent = history[-limit:] if history else []
        prompt = self.prompt_builder.build_summary_prompt(recent)
        return await self.provider.generate_response(prompt, system_prompt=self.prompt_builder.build_system_prompt())

    def receive_text(
        self,
        text: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BrainResponse:
        """Compatibility wrapper for synchronous callers."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.process(text=text, conversation_id=conversation_id, metadata=metadata))
        return asyncio.run_coroutine_threadsafe(
            self.process(text=text, conversation_id=conversation_id, metadata=metadata),
            loop=asyncio.get_running_loop(),
        ).result()

    def process_sync(self, text: str, conversation_id: str | None = None, metadata: dict[str, Any] | None = None) -> BrainResponse:
        """Synchronous wrapper for process with explicit semantics."""
        return self.receive_text(text=text, conversation_id=conversation_id, metadata=metadata)

    async def _build_memory_summary(self, context: ConversationContext) -> str | None:
        """Collect a compact memory summary for the active context."""
        if self.long_term_memory is None and self.short_term_memory is None:
            return None
        entries: list[str] = []
        if self.long_term_memory is not None:
            for entry in self.long_term_memory.repository.list_entries(category="long_term")[:5]:
                entries.append(f"{entry.key}: {entry.value}")
        if self.short_term_memory is not None:
            for entry in self.short_term_memory.repository.list_entries(category="short_term")[:5]:
                entries.append(f"{entry.key}: {entry.value}")
        return "; ".join(entries) if entries else None

    def _publish_engine_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Notify the runtime engine about Brain activity when available."""
        if self.engine is None:
            return
        execution_context = ExecutionContext(request_id=payload.get("conversation_id"), payload={"event": event_name, **payload})
        self.engine.execute(execution_context)
