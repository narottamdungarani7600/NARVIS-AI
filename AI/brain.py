"""Core Brain engine for the NARVIS AI subsystem."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Protocol

from Core.engine import ExecutionContext
from .context import ConversationContext, ContextManager, InMemoryContextManager
from .conversation import ChatHistoryManager, SessionManager
from .intent import IntentAnalyzer, IntentClassifier, IntentClassification, RuleBasedIntentClassifier
from .prompts import PromptBuilder
from .providers import Provider, ProviderFactory, ProviderResponse
from .response import BrainResponse, ResponseBuilder
from .router import IntentRouter, Router


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


class MemoryEntryProtocol(Protocol):
    """Protocol describing the subset of memory entry fields used by Brain."""

    key: str
    value: Any
    importance: float
    timestamp: datetime


class MemoryRepositoryProtocol(Protocol):
    """Protocol for repository operations used by the Brain engine."""

    def delete(self, key: str) -> None:
        """Delete a memory entry by key."""

    def list_entries(self, category: str | None = None) -> list[MemoryEntryProtocol]:
        """Return stored entries, optionally filtered by category."""


class MemoryStoreProtocol(Protocol):
    """Protocol for memory services consumed by the Brain engine."""

    repository: MemoryRepositoryProtocol

    def store(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Store a memory entry."""

    def recall(self, key: str) -> Any:
        """Recall a memory entry."""


class RuntimeEngineProtocol(Protocol):
    """Protocol for the runtime engine callback used by the Brain engine."""

    def execute(self, context: ExecutionContext) -> Any:
        """Execute an engine event payload."""


class BrainEngine:
    """Central orchestration component for the Brain subsystem."""

    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        intent_analyzer: IntentAnalyzer | None = None,
        context_manager: ContextManager | None = None,
        router: Router | None = None,
        response_builder: ResponseBuilder | None = None,
        provider: Provider | None = None,
        prompt_builder: PromptBuilder | None = None,
        session_manager: SessionManager | None = None,
        chat_history_manager: ChatHistoryManager | None = None,
        short_term_memory: MemoryStoreProtocol | None = None,
        long_term_memory: MemoryStoreProtocol | None = None,
        engine: RuntimeEngineProtocol | None = None,
        logger: Any | None = None,
    ) -> None:
        """Initialize the Brain engine and its collaborators."""
        self.logger = logger
        self.intent_classifier = intent_classifier or RuleBasedIntentClassifier(logger=logger)
        self.intent_analyzer = intent_analyzer or IntentAnalyzer(classifier=self.intent_classifier, logger=logger)
        self.context_manager = context_manager or InMemoryContextManager(
            session_manager=session_manager or SessionManager(logger=logger),
            chat_history_manager=chat_history_manager or ChatHistoryManager(max_turns=50, logger=logger),
            logger=logger,
        )
        self.session_manager = getattr(self.context_manager, "session_manager", session_manager or SessionManager(logger=logger))
        self.chat_history_manager = getattr(
            self.context_manager,
            "chat_history_manager",
            chat_history_manager or ChatHistoryManager(max_turns=50, logger=logger),
        )
        self.router = router or IntentRouter(logger=logger)
        self.prompt_builder = prompt_builder or PromptBuilder()

        if response_builder is not None and response_builder.provider is not None:
            self.provider = response_builder.provider
        else:
            self.provider = provider or ProviderFactory.create_default(logger=logger)

        if response_builder is None:
            self.response_builder = ResponseBuilder(
                provider=self.provider,
                prompt_builder=self.prompt_builder,
                logger=logger,
            )
        else:
            self.response_builder = response_builder
            if self.response_builder.provider is None:
                self.response_builder.provider = self.provider
            if self.response_builder.prompt_builder is None:
                self.response_builder.prompt_builder = self.prompt_builder

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

        normalized_metadata = dict(metadata or {})
        self._publish_engine_event("brain.processing", {"text": text, "conversation_id": conversation_id})
        context = self.context_manager.get_or_create(conversation_id=conversation_id, session_id=session_id)
        classification = self.intent_analyzer.analyze(text)
        route = self.router.route(classification)

        _emit_log(
            self.logger,
            "info",
            "Processing Brain request",
            conversation_id=context.conversation_id,
            session_id=context.session_id,
            intent=classification.intent.value,
            route=route.name,
        )

        self.context_manager.record_turn(
            context=context,
            role="user",
            content=text,
            metadata=normalized_metadata,
        )
        self.context_manager.update_context(
            context=context,
            last_intent=classification.intent,
            last_route=route.name,
            metadata={"conversation_id": context.conversation_id, "session_id": context.session_id, **normalized_metadata},
        )

        history = self.context_manager.get_history(context.conversation_id)
        memory_summary = await self._build_memory_summary(context)
        provider_response = await self.response_builder.generate_provider_response(
            text=text,
            intent=classification,
            route=route,
            context=context,
            metadata={"conversation_id": context.conversation_id, "session_id": context.session_id, **normalized_metadata},
            memory_summary=memory_summary,
            history=history,
        )

        self.context_manager.record_turn(
            context=context,
            role="assistant",
            content=provider_response.content,
            metadata={"route": route.name, "provider": provider_response.provider_name},
        )
        self._publish_engine_event("brain.completed", {"conversation_id": context.conversation_id, "route": route.name})
        _emit_log(
            self.logger,
            "info",
            "Completed Brain request",
            conversation_id=context.conversation_id,
            provider=provider_response.provider_name,
            fallback=provider_response.is_fallback,
        )
        return self.response_builder.build(
            text=text,
            intent=classification,
            route=route,
            context=context,
            metadata={"conversation_id": context.conversation_id, "session_id": context.session_id, **normalized_metadata},
            message=provider_response.content,
            provider_response=provider_response,
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

    async def remember(
        self,
        key: str,
        value: Any,
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Persist a value to the configured memory layer."""
        normalized_metadata = dict(metadata or {})
        stored = False
        if self.long_term_memory is not None:
            self.long_term_memory.store(
                self._memory_key("long_term", key),
                value,
                importance=importance,
                metadata=normalized_metadata,
            )
            stored = True
        if self.short_term_memory is not None:
            self.short_term_memory.store(
                self._memory_key("short_term", key),
                value,
                importance=importance,
                metadata=normalized_metadata,
            )
            stored = True
        _emit_log(self.logger, "debug", "Stored memory entry", key=key, stored=stored)
        return stored

    async def forget(self, key: str) -> bool:
        """Delete a remembered value from the configured memory layer."""
        removed = False
        for memory, prefix in (
            (self.long_term_memory, "long_term"),
            (self.short_term_memory, "short_term"),
        ):
            if memory is None:
                continue
            candidate_keys = (self._memory_key(prefix, key), key)
            for candidate_key in candidate_keys:
                entry = memory.recall(candidate_key)
                if entry is not None:
                    memory.repository.delete(candidate_key)
                    removed = True
        _emit_log(self.logger, "debug", "Removed memory entry", key=key, removed=removed)
        return removed

    async def summarize(self, conversation_id: str | None = None, limit: int = 10) -> str:
        """Summarize the active conversation history."""
        context = self.context_manager.get_or_create(conversation_id=conversation_id)
        history = self.context_manager.get_history(context.conversation_id)
        recent = history[-limit:] if history else []
        if not recent:
            return "No conversation history is available to summarize."

        prompt = self.prompt_builder.build_summary_prompt(recent)
        summary = await self.provider.generate_response(
            prompt,
            system_prompt=self.prompt_builder.build_system_prompt(context=context),
            context=[],
        )
        if summary:
            return summary
        return self._build_local_summary(recent)

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
        raise RuntimeError("receive_text cannot be called from an active event loop; use 'await process(...)' instead.")

    def process_sync(
        self,
        text: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BrainResponse:
        """Synchronous wrapper for :meth:`process` with explicit semantics."""
        return self.receive_text(text=text, conversation_id=conversation_id, metadata=metadata)

    async def _build_memory_summary(self, context: ConversationContext) -> str | None:
        """Collect a compact memory summary for the active context."""
        entries: list[str] = []
        for label, memory, category in (
            ("long-term", self.long_term_memory, "long_term"),
            ("short-term", self.short_term_memory, "short_term"),
        ):
            if memory is None:
                continue
            entries.extend(self._format_memory_entries(memory, category, label))
        if not entries:
            return None
        return "; ".join(entries)

    def _format_memory_entries(self, memory: MemoryStoreProtocol, category: str, label: str) -> list[str]:
        """Format a small number of memory entries for prompt inclusion."""
        repository = getattr(memory, "repository", None)
        if repository is None or not hasattr(repository, "list_entries"):
            return []

        try:
            raw_entries = list(repository.list_entries(category=category))
        except Exception:  # pragma: no cover - defensive handling
            return []

        def _sort_key(entry: MemoryEntryProtocol) -> tuple[float, datetime]:
            timestamp = getattr(entry, "timestamp", datetime.min.replace(tzinfo=timezone.utc))
            return (float(getattr(entry, "importance", 0.0)), timestamp)

        raw_entries.sort(key=_sort_key, reverse=True)
        formatted_entries: list[str] = []
        for entry in raw_entries[:5]:
            clean_key = self._strip_memory_prefix(getattr(entry, "key", "memory"))
            clean_value = str(getattr(entry, "value", "")).strip().replace("\n", " ")
            formatted_entries.append(f"{label} {clean_key}: {clean_value[:160]}")
        return formatted_entries

    def _memory_key(self, scope: str, key: str) -> str:
        """Create a scoped memory key to avoid repository collisions."""
        return f"brain:{scope}:{key}"

    def _strip_memory_prefix(self, key: str) -> str:
        """Remove internal Brain memory prefixes from display values."""
        if key.startswith("brain:"):
            parts = key.split(":", 2)
            if len(parts) == 3:
                return parts[2]
        return key

    def _build_local_summary(self, history: list[Any]) -> str:
        """Create a deterministic summary when a provider summary is unavailable."""
        turns = [f"{getattr(turn, 'role', 'user')}: {getattr(turn, 'content', turn)}" for turn in history]
        return "Recent conversation summary: " + " | ".join(turns[-5:])

    def _publish_engine_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Notify the runtime engine about Brain activity when available."""
        if self.engine is None:
            return
        execution_context = ExecutionContext(
            request_id=payload.get("conversation_id"),
            payload={"event": event_name, **payload},
        )
        self.engine.execute(execution_context)
