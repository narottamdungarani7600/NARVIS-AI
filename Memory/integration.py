"""High-level memory orchestration helpers for the NARVIS runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .memory import MemoryEntry
from .profile import InMemoryProfileMemory, UserProfile
from .session import InMemorySessionMemory

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_GENERIC_RETRIEVAL_EXCLUDED_CATEGORIES = frozenset(
    {
        "approval_decision",
        "capability_inventory",
        "change_journal",
        "change_proposal",
        "discovery_candidate",
        "evidence_record",
        "evaluation_record",
        "capability_gap",
        "learned_outcome",
    }
)


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

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


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Memory."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class SearchProtocol(Protocol):
    """Protocol for memory search services consumed by the integration layer."""

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search the memory repository."""


@dataclass(slots=True, frozen=True)
class MemorySnapshot:
    """Represents the current persisted memory distribution."""

    total_entries: int
    short_term_entries: int
    long_term_entries: int
    session_entries: int
    profile_entries: int
    conversation_history_entries: int


class MemoryIntegrationService:
    """Provide one runtime-facing orchestration layer over memory services."""

    def __init__(
        self,
        *,
        storage: Any,
        short_term_memory: Any,
        long_term_memory: Any,
        session_memory: Any,
        profile_memory: Any,
        memory_search: SearchProtocol,
        logger: Any | None = None,
    ) -> None:
        self.storage = storage
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory
        self.session_memory = session_memory
        self.profile_memory = profile_memory
        self.memory_search = memory_search
        self.logger = logger

    def remember(
        self,
        key: str,
        value: Any,
        *,
        scope: str = "both",
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[MemoryEntry, ...]:
        """Store a value in one or more memory scopes."""

        normalized_scope = scope.strip().lower()
        normalized_metadata = dict(metadata or {})
        stored_entries: list[MemoryEntry] = []

        if normalized_scope in {"short_term", "short", "both"}:
            stored_entries.append(
                self.short_term_memory.store(
                    f"short_term:{key}",
                    value,
                    importance=importance,
                    metadata=normalized_metadata,
                )
            )
        if normalized_scope in {"long_term", "long", "both"}:
            stored_entries.append(
                self.long_term_memory.store(
                    f"long_term:{key}",
                    value,
                    importance=importance,
                    metadata=normalized_metadata,
                )
            )
        _emit_log(self.logger, "debug", "Stored integrated memory", key=key, scope=normalized_scope, count=len(stored_entries))
        return tuple(stored_entries)

    def recall(self, key: str) -> MemoryEntry | None:
        """Recall a value from long-term or short-term memory."""

        for candidate_key in (key, f"long_term:{key}", f"short_term:{key}"):
            entry = self.long_term_memory.recall(candidate_key) or self.short_term_memory.recall(candidate_key)
            if entry is not None:
                return entry
        return None

    def forget(self, key: str) -> bool:
        """Remove a key from both long-term and short-term memory."""

        removed = False
        for candidate_key in (key, f"long_term:{key}", f"short_term:{key}"):
            entry = self.storage.load(candidate_key)
            if entry is None:
                continue
            self.storage.delete(candidate_key)
            removed = True
        _emit_log(self.logger, "debug", "Forgot integrated memory", key=key, removed=removed)
        return removed

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Search persisted memory records."""

        results = list(self.memory_search.search(query=query, category=category, limit=limit))
        if category is not None:
            return results
        return [entry for entry in results if entry.category not in _GENERIC_RETRIEVAL_EXCLUDED_CATEGORIES]

    def store_conversation_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry | None:
        """Persist one conversation turn into session-scoped history."""

        if not isinstance(self.session_memory, InMemorySessionMemory):
            return None
        turn = self.session_memory.record_turn(
            session_id=session_id,
            role=role,
            content=content,
            conversation_id=conversation_id,
            metadata=metadata,
        )
        return self.storage.load(f"history:{turn.session_id}:{turn.conversation_id or 'default'}:{turn.turn_id}")

    def remember_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        preferences: dict[str, Any] | None = None,
        traits: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UserProfile:
        """Create or update a user profile record."""

        if isinstance(self.profile_memory, InMemoryProfileMemory):
            profile = self.profile_memory.load_profile(user_id) or UserProfile(user_id=user_id)
            if display_name is not None:
                profile.display_name = display_name
            if preferences:
                profile.preferences.update(preferences)
            if traits:
                profile.traits.update(traits)
            if metadata:
                profile.metadata.update(metadata)
            self.profile_memory.save_profile(profile)
            return profile
        profile = UserProfile(
            user_id=user_id,
            display_name=display_name,
            preferences=dict(preferences or {}),
            traits=dict(traits or {}),
            metadata=dict(metadata or {}),
        )
        return profile

    def build_context_summary(
        self,
        query: str | None = None,
        limit: int = 5,
        *,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> str | None:
        """Build a concise text summary of the most relevant memories."""

        max_items = max(limit, 1)
        if query:
            entries = self.search(query, limit=max(max_items * 10, 50))
        else:
            entries = self.storage.list_entries()

        visible_entries = [
            entry
            for entry in entries
            if self._entry_is_visible_in_context(
                entry,
                session_id=session_id,
                conversation_id=conversation_id,
            )
        ]

        if query and len(visible_entries) < max_items:
            visible_entries = self._supplement_visible_entries(
                visible_entries,
                query=query,
                limit=max_items,
                session_id=session_id,
                conversation_id=conversation_id,
            )
        if not visible_entries:
            return None
        summary_lines: list[str] = []
        for entry in visible_entries[: max_items]:
            value = str(entry.value).replace("\n", " ").strip()
            summary_lines.append(f"{entry.category} {entry.key}: {value[:160]}")
        return "; ".join(summary_lines)

    def _supplement_visible_entries(
        self,
        entries: list[MemoryEntry],
        *,
        query: str,
        limit: int,
        session_id: str | None,
        conversation_id: str | None,
    ) -> list[MemoryEntry]:
        """Backfill visible scoped memory when filtered global results are too sparse."""

        seen_keys = {entry.key for entry in entries}
        supplemented = list(entries)
        for category in ("long_term", "short_term", "profile", "session"):
            for entry in self._matching_category_entries(query, category=category, limit=max(limit * 5, 10)):
                if entry.key in seen_keys:
                    continue
                if not self._entry_is_visible_in_context(
                    entry,
                    session_id=session_id,
                    conversation_id=conversation_id,
                ):
                    continue
                supplemented.append(entry)
                seen_keys.add(entry.key)
                if len(supplemented) >= limit:
                    return supplemented
        return supplemented

    def _matching_category_entries(self, query: str, *, category: str, limit: int) -> list[MemoryEntry]:
        """Return ranked category entries, falling back to a local token scan when storage prefilters are too strict."""

        entries = list(self.search(query, category=category, limit=limit))
        if entries:
            return entries

        fallback_entries = [entry for entry in self.storage.list_entries(category=category) if self._entry_matches_query(entry, query)]
        fallback_entries.sort(
            key=lambda entry: (float(entry.importance), entry.timestamp, entry.key),
            reverse=True,
        )
        return fallback_entries[:limit]

    def _entry_matches_query(self, entry: MemoryEntry, query: str) -> bool:
        """Return whether one entry lexically matches a summary query."""

        normalized_query = " ".join(str(query).strip().lower().split())
        if not normalized_query:
            return False

        search_text = entry.text_content().lower()
        if normalized_query in search_text:
            return True

        tokens = _TOKEN_PATTERN.findall(normalized_query)
        if not tokens:
            return False
        return any(token in search_text for token in tokens)

    def _entry_is_visible_in_context(
        self,
        entry: MemoryEntry,
        *,
        session_id: str | None,
        conversation_id: str | None,
    ) -> bool:
        """Return whether one persisted entry may appear in a generic context summary."""

        if entry.category == "conversation_history":
            # Conversation turns are already provided through the dedicated history/context path.
            # They must not behave like globally retrievable memory snippets.
            return False
        if entry.category in _GENERIC_RETRIEVAL_EXCLUDED_CATEGORIES:
            return False

        if entry.category != "session":
            return True

        if not session_id:
            return False
        return entry.metadata.get("session_id") == session_id

    def snapshot_counts(self) -> MemorySnapshot:
        """Return the number of stored entries by category."""

        entries = self.storage.list_entries()
        counts = {
            "short_term": 0,
            "long_term": 0,
            "session": 0,
            "profile": 0,
            "conversation_history": 0,
        }
        for entry in entries:
            if entry.category in counts:
                counts[entry.category] += 1
        return MemorySnapshot(
            total_entries=len(entries),
            short_term_entries=counts["short_term"],
            long_term_entries=counts["long_term"],
            session_entries=counts["session"],
            profile_entries=counts["profile"],
            conversation_history_entries=counts["conversation_history"],
        )


def build_memory_integration_service(
    *,
    storage: Any,
    short_term_memory: Any,
    long_term_memory: Any,
    session_memory: Any,
    profile_memory: Any,
    memory_search: SearchProtocol,
    logger: Any | None = None,
) -> MemoryIntegrationService:
    """Build the runtime memory integration service."""

    _emit_log(logger, "info", "Built memory integration service")
    return MemoryIntegrationService(
        storage=storage,
        short_term_memory=short_term_memory,
        long_term_memory=long_term_memory,
        session_memory=session_memory,
        profile_memory=profile_memory,
        memory_search=memory_search,
        logger=logger,
    )


def register_memory_integration_services(
    container: DependencyRegistrar,
    service: MemoryIntegrationService,
    *,
    logger: Any | None = None,
) -> MemoryIntegrationService:
    """Register memory integration services in the dependency container."""

    container.register_instance("memory_service", service)
    container.register_instance("memory_integration", service)
    _emit_log(logger, "info", "Registered memory integration services in container")
    return service


__all__ = [
    "MemoryIntegrationService",
    "MemorySnapshot",
    "build_memory_integration_service",
    "register_memory_integration_services",
]
