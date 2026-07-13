"""Core Brain engine for the NARVIS AI subsystem."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Protocol

from Core.engine import ExecutionContext
from .context import ConversationContext, ContextManager, InMemoryContextManager
from .conversation import ChatHistoryManager, SessionManager
from .intent import IntentAnalyzer, IntentClassifier, IntentClassification, IntentType, RuleBasedIntentClassifier
from .prompts import PromptBuilder
from .providers import Provider, ProviderFactory, ProviderResponse
from .response import BrainResponse, ResponseBuilder
from .router import IntentRouter, Router

_INTERNET_CONTEXT_RESET_PHRASES = {
    "hello",
    "hi",
    "hey",
    "help",
    "exit",
    "quit",
    "bye",
    "thank you",
    "thanks",
}
_INTERNET_CONTEXT_RESET_PREFIXES = (
    "remember ",
    "forget ",
    "recall ",
    "save ",
    "store ",
    "note ",
    "delete memory ",
    "what do you remember ",
    "what did i tell you",
    "what did we discuss",
    "search memory for ",
)
_INTERNET_CONTEXT_RESET_PATTERNS = (
    r"\bwhat is my name\b",
    r"\bwhat's my name\b",
    r"\bwhat did i tell you\b",
)
_LOCAL_SYSTEM_CONTEXT_TOPICS = {
    "status",
    "health",
    "runtime",
    "system",
    "runtime status",
    "system status",
    "runtime health",
    "system health",
}


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


class MemoryIntegrationProtocol(Protocol):
    """Protocol for the higher-level memory integration service consumed by Brain."""

    def remember(
        self,
        key: str,
        value: Any,
        *,
        scope: str = "both",
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        """Store a value in one or more memory scopes."""

    def forget(self, key: str) -> bool:
        """Remove a value from the integrated memory service."""

    def build_context_summary(
        self,
        query: str | None = None,
        limit: int = 5,
        *,
        session_id: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> str | None:
        """Build a concise summary of relevant memory entries."""

    def store_conversation_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Persist one conversation turn."""


class SkillExecutorProtocol(Protocol):
    """Protocol for runtime skill executors consumed by Brain."""

    def execute_best(self, request: Any, minimum_confidence: float = 0.45) -> Any | None:
        """Execute the best matching skill for a request."""


class RuntimeOptimizerProtocol(Protocol):
    """Protocol for runtime optimization services consumed by Brain."""

    def get(self, namespace: str, key: str) -> Any | None:
        """Return a cached value if present."""

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: float | None = None) -> Any:
        """Cache a runtime value."""

    def invalidate(self, namespace: str, key: str | None = None) -> None:
        """Invalidate one cache entry or a complete namespace."""

    def increment_counter(self, name: str, amount: int = 1) -> int:
        """Increment a named counter."""

    def record_timing(self, name: str, duration_seconds: float) -> Any:
        """Record a duration measurement."""


@dataclass(slots=True)
class BrainPlanStep:
    """Represents one stage in the Brain 2.0 reasoning pipeline."""

    name: str
    status: str = "pending"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrainExecutionResult:
    """Represents a handled non-provider execution path."""

    source: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    handled: bool = True


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
        skill_executor: SkillExecutorProtocol | None = None,
        memory_integration: MemoryIntegrationProtocol | None = None,
        runtime_optimizer: RuntimeOptimizerProtocol | None = None,
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
        self.skill_executor = skill_executor
        self.memory_integration = memory_integration
        self.runtime_optimizer = runtime_optimizer

    async def process(
        self,
        text: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> BrainResponse:
        """Process a user message and return a structured response."""
        started_at = perf_counter()
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        normalized_metadata = dict(metadata or {})
        self._publish_engine_event("brain.processing", {"text": text, "conversation_id": conversation_id})
        context = self.context_manager.get_or_create(conversation_id=conversation_id, session_id=session_id)
        classification = self.intent_analyzer.analyze(text)
        route = self.router.route(classification)
        plan = self._build_plan(text=text, classification=classification, route=route)
        self._set_plan_step_status(plan, "capture_context", "completed")
        self._set_plan_step_status(plan, "classify_intent", "completed")
        self._set_plan_step_status(plan, "select_route", "completed")

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
            metadata={
                "conversation_id": context.conversation_id,
                "session_id": context.session_id,
                "plan": self._serialize_plan(plan),
                **normalized_metadata,
            },
        )
        if self.memory_integration is not None and context.session_id is not None:
            self.memory_integration.store_conversation_turn(
                session_id=context.session_id,
                conversation_id=context.conversation_id,
                role="user",
                content=text,
                metadata={"route": route.name, "intent": classification.intent.value, **normalized_metadata},
            )

        history = self.context_manager.get_history(context.conversation_id)
        memory_summary = await self._build_memory_summary(context, query=text)
        execution_result = self._execute_runtime_capability(
            text=text,
            context=context,
            classification=classification,
            route=route,
            metadata=normalized_metadata,
        )
        if execution_result is not None and execution_result.handled:
            provider_response = self._build_execution_provider_response(
                text=text,
                execution_result=execution_result,
            )
            self._set_plan_step_status(plan, "execute_route", "completed")
        else:
            provider_response = await self.response_builder.generate_provider_response(
                text=text,
                intent=classification,
                route=route,
                context=context,
                metadata={"conversation_id": context.conversation_id, "session_id": context.session_id, **normalized_metadata},
                memory_summary=memory_summary,
                history=history,
            )
            self._set_plan_step_status(plan, "generate_response", "completed")

        self._update_runtime_context(
            context=context,
            execution_result=execution_result,
            text=text,
            classification=classification,
            route=route,
        )

        self.context_manager.record_turn(
            context=context,
            role="assistant",
            content=provider_response.content,
            metadata={"route": route.name, "provider": provider_response.provider_name},
        )
        if self.memory_integration is not None and context.session_id is not None:
            self.memory_integration.store_conversation_turn(
                session_id=context.session_id,
                conversation_id=context.conversation_id,
                role="assistant",
                content=provider_response.content,
                metadata={
                    "route": route.name,
                    "provider": provider_response.provider_name,
                    "intent": classification.intent.value,
                },
            )
        self._set_plan_step_status(plan, "persist_memory", "completed")
        self._publish_engine_event("brain.completed", {"conversation_id": context.conversation_id, "route": route.name})
        _emit_log(
            self.logger,
            "info",
            "Completed Brain request",
            conversation_id=context.conversation_id,
            provider=provider_response.provider_name,
            fallback=provider_response.is_fallback,
        )
        response = self.response_builder.build(
            text=text,
            intent=classification,
            route=route,
            context=context,
            metadata={
                "conversation_id": context.conversation_id,
                "session_id": context.session_id,
                "plan": self._serialize_plan(plan),
                **normalized_metadata,
            },
            message=provider_response.content,
            provider_response=provider_response,
        )
        if self.runtime_optimizer is not None:
            self.runtime_optimizer.increment_counter("brain.requests", amount=1)
            self.runtime_optimizer.record_timing("brain.process", perf_counter() - started_at)
        return response

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
        if self.memory_integration is not None:
            stored_entries = self.memory_integration.remember(
                key=key,
                value=value,
                scope="both",
                importance=importance,
                metadata=normalized_metadata,
            )
            stored = bool(stored_entries)
            _emit_log(self.logger, "debug", "Stored memory entry", key=key, stored=stored)
            return stored

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
        if self.memory_integration is not None:
            removed = self.memory_integration.forget(key)
            _emit_log(self.logger, "debug", "Removed memory entry", key=key, removed=removed)
            return removed

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

    async def _build_memory_summary(self, context: ConversationContext, query: str | None = None) -> str | None:
        """Collect a compact memory summary for the active context."""
        cache_key = None
        if self.runtime_optimizer is not None and query:
            query_digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:16]
            user_id = str(context.metadata.get("user_id") or "default").strip() or "default"
            cache_key = f"{user_id}:{context.session_id or '-'}:{context.conversation_id}:{query_digest}"
            cached = self.runtime_optimizer.get("brain.memory_summary", cache_key)
            if cached is not None:
                return cached

        entries: list[str] = []
        if self.memory_integration is not None:
            try:
                summary_arguments: dict[str, Any] = {
                    "query": query,
                    "limit": 5,
                    "session_id": context.session_id,
                    "conversation_id": context.conversation_id,
                }
                user_id = str(context.metadata.get("user_id") or "").strip()
                if user_id:
                    summary_arguments["user_id"] = user_id
                integrated_summary = self.memory_integration.build_context_summary(
                    **summary_arguments,
                )
            except Exception:  # pragma: no cover - defensive handling
                integrated_summary = None
            if integrated_summary:
                entries.append(integrated_summary)

        if self.memory_integration is None:
            for label, memory, category in (
                ("long-term", self.long_term_memory, "long_term"),
                ("short-term", self.short_term_memory, "short_term"),
            ):
                if memory is None:
                    continue
                entries.extend(self._format_memory_entries(memory, category, label))
        if not entries:
            return None
        summary = "; ".join(dict.fromkeys(entries))
        if cache_key is not None and self.runtime_optimizer is not None:
            self.runtime_optimizer.set("brain.memory_summary", cache_key, summary, ttl_seconds=15.0)
        return summary

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

    def _build_plan(self, text: str, classification: IntentClassification, route: Any) -> list[BrainPlanStep]:
        """Create a lightweight execution plan for the current request."""

        steps = [
            BrainPlanStep(name="capture_context", details={"conversation_length": len(text)}),
            BrainPlanStep(name="classify_intent", details={"intent": classification.intent.value}),
            BrainPlanStep(name="select_route", details={"route": route.name}),
        ]
        if route.name in {"Skills", "Automation", "Core"}:
            steps.append(BrainPlanStep(name="execute_route", details={"strategy": "skill_execution"}))
        else:
            steps.append(BrainPlanStep(name="generate_response", details={"strategy": "provider_generation"}))
        steps.append(BrainPlanStep(name="persist_memory", details={"enabled": self.memory_integration is not None}))
        return steps

    def _set_plan_step_status(self, plan: list[BrainPlanStep], step_name: str, status: str) -> None:
        """Update one plan step by name when it exists."""

        for step in plan:
            if step.name == step_name:
                step.status = status
                return

    def _serialize_plan(self, plan: list[BrainPlanStep]) -> list[dict[str, Any]]:
        """Convert a plan into a JSON-friendly structure."""

        return [
            {
                "name": step.name,
                "status": step.status,
                "details": dict(step.details),
            }
            for step in plan
        ]

    def _execute_runtime_capability(
        self,
        *,
        text: str,
        context: ConversationContext,
        classification: IntentClassification,
        route: Any,
        metadata: dict[str, Any],
    ) -> BrainExecutionResult | None:
        """Attempt to execute the request through the runtime skill framework."""

        if self.skill_executor is None:
            return None

        minimum_confidence = 0.65 if route.name == "AI" else 0.35
        try:
            from Skills.framework import SkillRequest

            request = SkillRequest(
                text=text,
                route=route.name,
                metadata={
                    **dict(metadata),
                    "intent": classification.intent.value,
                    "intent_confidence": classification.confidence,
                    "intent_reason": classification.reason,
                    "intent_matched_keywords": list(classification.matched_keywords),
                    "route_name": route.name,
                    "route_confidence": getattr(route, "confidence", classification.confidence),
                    "route_reason": getattr(route, "reason", None),
                    "context_last_route": context.last_route,
                    "context_last_intent": context.last_intent.value if context.last_intent is not None else None,
                    "context_last_skill": context.metadata.get("last_skill_name"),
                    "context_last_memory_key": context.metadata.get("last_memory_key"),
                    "context_last_memory_action": context.metadata.get("last_memory_action"),
                    "context_last_internet_topic": context.metadata.get("last_internet_topic"),
                    "context_last_internet_search_text": context.metadata.get("last_internet_search_text"),
                    "context_last_internet_intent_kind": context.metadata.get("last_internet_intent_kind"),
                    "context_last_internet_routing_signals": context.metadata.get("last_internet_routing_signals"),
                },
                conversation_id=context.conversation_id,
                session_id=context.session_id,
            )
            result = self.skill_executor.execute_best(request, minimum_confidence=minimum_confidence)
        except Exception as error:  # pragma: no cover - defensive handling
            _emit_log(self.logger, "warning", "Runtime skill execution failed", error=str(error))
            return None

        if result is None or not getattr(result, "handled", False):
            return None
        return BrainExecutionResult(
            source="skills-runtime",
            message=str(getattr(result, "message", "")),
            metadata={
                "skill_name": getattr(result, "skill_name", "unknown"),
                "skill_confidence": float(getattr(result, "confidence", 0.0)),
                "skill_data": dict(getattr(result, "data", {})),
            },
        )

    def _build_execution_provider_response(
        self,
        *,
        text: str,
        execution_result: BrainExecutionResult,
    ) -> ProviderResponse:
        """Create a provider-like response from a direct runtime execution."""

        usage = self.response_builder._fallback_provider_response(  # noqa: SLF001 - reuse deterministic token heuristic
            text=text,
            intent=IntentClassification(intent=self.intent_analyzer.classify(text).intent, confidence=1.0),
            route=self.router.route(self.intent_analyzer.classify(text)),
        ).usage
        return ProviderResponse(
            content=execution_result.message,
            provider_name=execution_result.source,
            model="runtime-skill",
            usage=usage,
            is_fallback=False,
            metadata=dict(execution_result.metadata),
        )

    def _update_runtime_context(
        self,
        *,
        context: ConversationContext,
        execution_result: BrainExecutionResult | None,
        text: str,
        classification: IntentClassification,
        route: Any,
    ) -> None:
        """Persist lightweight skill-routing context for safe conversational follow-ups."""

        updates: dict[str, Any] = {}
        if execution_result is not None and execution_result.handled:
            metadata = dict(execution_result.metadata)
            skill_name = str(metadata.get("skill_name") or "").strip()
            if skill_name:
                updates["last_skill_name"] = skill_name
            skill_data = metadata.get("skill_data")
            if skill_name == "memory.manage" and isinstance(skill_data, dict):
                memory_key = str(skill_data.get("key") or "").strip()
                memory_action = str(skill_data.get("action") or "").strip()
                if memory_key:
                    updates["last_memory_key"] = memory_key
                if memory_action:
                    updates["last_memory_action"] = memory_action
                if memory_action in {"store", "forget"}:
                    invalidate = getattr(self.runtime_optimizer, "invalidate", None)
                    if callable(invalidate):
                        invalidate("brain.memory_summary")
                updates.update(self._clear_internet_context_fields())
            elif skill_name == "internet.query" and isinstance(skill_data, dict):
                topic = str(skill_data.get("query") or "").strip()
                search_text = str(skill_data.get("search_text") or "").strip()
                intent_kind = str(skill_data.get("intent_kind") or "").strip()
                routing_signals = skill_data.get("routing_signals")
                if topic:
                    updates["last_internet_topic"] = topic
                if search_text:
                    updates["last_internet_search_text"] = search_text
                if intent_kind:
                    updates["last_internet_intent_kind"] = intent_kind
                if isinstance(routing_signals, list):
                    updates["last_internet_routing_signals"] = list(routing_signals)
            else:
                updates.update(self._clear_internet_context_fields())
        elif self._should_invalidate_internet_context(text=text, classification=classification, route=route):
            updates.update(self._clear_internet_context_fields())

        if updates:
            self.context_manager.update_context(context=context, metadata=updates)

    def _clear_internet_context_fields(self) -> dict[str, Any]:
        """Return the metadata patch that invalidates internet follow-up reuse."""

        return {
            "last_internet_topic": None,
            "last_internet_search_text": None,
            "last_internet_intent_kind": None,
            "last_internet_routing_signals": None,
        }

    def _should_invalidate_internet_context(
        self,
        *,
        text: str,
        classification: IntentClassification,
        route: Any,
    ) -> bool:
        """Return whether the current turn should invalidate internet follow-up context."""

        if classification.intent in {IntentType.GREETING, IntentType.HELP, IntentType.STATUS}:
            return True
        if getattr(route, "name", None) in {"Core", "Automation"}:
            return True

        normalized = " ".join(str(text).strip().lower().split())
        if not normalized:
            return False
        if normalized in _INTERNET_CONTEXT_RESET_PHRASES:
            return True
        if normalized.startswith(_INTERNET_CONTEXT_RESET_PREFIXES):
            return True
        if self._is_local_system_context_query(normalized):
            return True
        return any(re.search(pattern, normalized) for pattern in _INTERNET_CONTEXT_RESET_PATTERNS)

    def _is_local_system_context_query(self, normalized_text: str) -> bool:
        """Return whether the text is a local/system identity-style query."""

        candidate = self._normalize_context_topic(normalized_text)
        return candidate in _LOCAL_SYSTEM_CONTEXT_TOPICS

    def _normalize_context_topic(self, text: str) -> str:
        """Normalize a user-facing topic candidate for context invalidation checks."""

        candidate = re.sub(r"\s+(?:kya|kaun)\s+hai$", "", text, flags=re.IGNORECASE).strip(" .?!")
        return " ".join(candidate.split())

    def _publish_engine_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Notify the runtime engine about Brain activity when available."""
        if self.engine is None:
            return
        execution_context = ExecutionContext(
            request_id=payload.get("conversation_id"),
            payload={"event": event_name, **payload},
        )
        self.engine.execute(execution_context)
