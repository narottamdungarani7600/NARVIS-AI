"""High-level memory orchestration helpers for the NARVIS runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from .memory import MemoryEntry
from .profile import UserProfile
from .session import SessionTurn

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_DEFAULT_PROFILE_USER_ID = "default"
_CONVERSATION_QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "did",
        "do",
        "i",
        "in",
        "me",
        "of",
        "our",
        "the",
        "to",
        "we",
        "what",
        "you",
    }
)
_GENERIC_RETRIEVAL_EXCLUDED_CATEGORIES = frozenset(
    {
        "conversation_history",
        "approval_decision",
        "capability_inventory",
        "change_journal",
        "change_plan",
        "change_proposal",
        "discovery_candidate",
        "evidence_record",
        "evaluation_record",
        "capability_gap",
        "learned_outcome",
        "execution_authorization",
        "execution_request",
        "execution_step_request",
        "plan_step",
        "recovery_observation",
        "recovery_outcome",
        "recovery_requirement",
        "recovery_run",
        "recovery_step_run",
        "verification_observation",
        "verification_outcome",
        "verification_requirement",
        "verification_run",
        "verification_step_run",
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


@dataclass(slots=True, frozen=True)
class ProfileMemoryFact:
    """One typed value recalled from a persisted user profile."""

    user_id: str
    key: str
    value: Any


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

        max_items = max(limit, 0)
        if max_items == 0:
            return []
        results = list(self.memory_search.search(query=query, category=category, limit=max_items))
        visible = self._filter_search_results(results, category=category)
        if len(visible) >= max_items:
            return visible[:max_items]

        seen_keys = {entry.key for entry in visible}
        for entry in self.storage.list_entries(category=category):
            if entry.key in seen_keys or not self._entry_matches_query(entry, query):
                continue
            if not self._search_entry_is_visible(entry, category=category):
                continue
            visible.append(entry)
            seen_keys.add(entry.key)
            if len(visible) >= max_items:
                break
        return visible

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

        record_turn = getattr(self.session_memory, "record_turn", None)
        if not callable(record_turn):
            return None
        turn = record_turn(
            session_id=session_id,
            role=role,
            content=content,
            conversation_id=conversation_id,
            metadata=metadata,
        )
        return self.storage.load(f"history:{turn.session_id}:{turn.conversation_id or 'default'}:{turn.turn_id}")

    def recall_conversation(
        self,
        *,
        session_id: str | None,
        conversation_id: str | None = None,
        query: str | None = None,
        limit: int = 5,
        role: str | None = "user",
        exclude_content: str | None = None,
    ) -> tuple[SessionTurn, ...]:
        """Recall persisted turns from the active session and conversation only."""

        normalized_session_id = str(session_id or "").strip()
        max_items = max(limit, 0)
        get_history = getattr(self.session_memory, "get_history", None)
        if not normalized_session_id or max_items == 0 or not callable(get_history):
            return ()

        turns = list(
            get_history(
                normalized_session_id,
                conversation_id=conversation_id,
                limit=None,
            )
        )
        normalized_role = str(role or "").strip().lower()
        normalized_exclusion = self._normalize_text(exclude_content)
        query_tokens = self._conversation_query_tokens(query)
        matched: list[SessionTurn] = []
        for turn in turns:
            if normalized_role and str(turn.role).strip().lower() != normalized_role:
                continue
            normalized_content = self._normalize_text(turn.content)
            if normalized_exclusion and normalized_content == normalized_exclusion:
                continue
            if query_tokens and not all(token in normalized_content for token in query_tokens):
                continue
            matched.append(turn)
        return tuple(matched[-max_items:])

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

        normalized_user_id = self._normalize_user_id(user_id)
        load_profile = getattr(self.profile_memory, "load_profile", None)
        save_profile = getattr(self.profile_memory, "save_profile", None)
        if callable(load_profile) and callable(save_profile):
            profile = load_profile(normalized_user_id) or UserProfile(user_id=normalized_user_id)
            if display_name is not None:
                profile.display_name = display_name
            if preferences:
                profile.preferences.update(preferences)
            if traits:
                profile.traits.update(traits)
            if metadata:
                profile.metadata.update(metadata)
            save_profile(profile)
            return profile
        profile = UserProfile(
            user_id=normalized_user_id,
            display_name=display_name,
            preferences=dict(preferences or {}),
            traits=dict(traits or {}),
            metadata=dict(metadata or {}),
        )
        return profile

    def remember_profile_fact(
        self,
        user_id: str | None,
        key: str,
        value: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> UserProfile:
        """Persist one natural-language profile fact through the profile service."""

        normalized_key = self._normalize_profile_fact_key(key)
        if normalized_key == "display_name":
            return self.remember_profile(
                self._normalize_user_id(user_id),
                display_name=str(value),
                metadata=metadata,
            )
        return self.remember_profile(
            self._normalize_user_id(user_id),
            preferences={normalized_key: value},
            metadata=metadata,
        )

    def recall_profile(self, user_id: str | None = None) -> UserProfile | None:
        """Load one persisted profile without exposing repository details."""

        load_profile = getattr(self.profile_memory, "load_profile", None)
        if not callable(load_profile):
            return None
        return load_profile(self._normalize_user_id(user_id))

    def recall_profile_fact(self, user_id: str | None, key: str) -> ProfileMemoryFact | None:
        """Recall one display-name, preference, or trait value from a profile."""

        profile = self.recall_profile(user_id)
        if profile is None:
            return None
        normalized_key = self._normalize_profile_fact_key(key)
        if normalized_key == "display_name" and profile.display_name is not None:
            return ProfileMemoryFact(user_id=profile.user_id, key=normalized_key, value=profile.display_name)
        if normalized_key in profile.preferences:
            return ProfileMemoryFact(
                user_id=profile.user_id,
                key=normalized_key,
                value=profile.preferences[normalized_key],
            )
        if normalized_key in profile.traits:
            return ProfileMemoryFact(
                user_id=profile.user_id,
                key=normalized_key,
                value=profile.traits[normalized_key],
            )
        return None

    def forget_profile_fact(self, user_id: str | None, key: str) -> bool:
        """Remove one profile fact while preserving the rest of the profile."""

        profile = self.recall_profile(user_id)
        save_profile = getattr(self.profile_memory, "save_profile", None)
        if profile is None or not callable(save_profile):
            return False

        normalized_key = self._normalize_profile_fact_key(key)
        removed = False
        if normalized_key == "display_name" and profile.display_name is not None:
            profile.display_name = None
            removed = True
        if normalized_key in profile.preferences:
            profile.preferences.pop(normalized_key)
            removed = True
        if normalized_key in profile.traits:
            profile.traits.pop(normalized_key)
            removed = True
        if removed:
            save_profile(profile)
        return removed

    def build_context_summary(
        self,
        query: str | None = None,
        limit: int = 5,
        *,
        session_id: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> str | None:
        """Build a concise text summary of the most relevant memories."""

        max_items = max(limit, 1)
        normalized_user_id = self._normalize_user_id(user_id)
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
                user_id=normalized_user_id,
            )
        ]

        profile_entry = self.storage.load(f"profile:{normalized_user_id}")
        if profile_entry is not None and all(entry.key != profile_entry.key for entry in visible_entries):
            visible_entries.insert(0, profile_entry)
        if query and len(visible_entries) < max_items:
            visible_entries = self._supplement_visible_entries(
                visible_entries,
                query=query,
                limit=max_items,
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=normalized_user_id,
            )
        if not visible_entries:
            return None
        summary_lines: list[str] = []
        for entry in visible_entries[: max_items]:
            summary_lines.append(self._format_context_entry(entry))
        return "; ".join(summary_lines)

    def _supplement_visible_entries(
        self,
        entries: list[MemoryEntry],
        *,
        query: str,
        limit: int,
        session_id: str | None,
        conversation_id: str | None,
        user_id: str,
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
                    user_id=user_id,
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

    def _filter_search_results(
        self,
        entries: list[MemoryEntry],
        *,
        category: str | None,
    ) -> list[MemoryEntry]:
        """Apply the established generic-retrieval isolation policy."""

        return [entry for entry in entries if self._search_entry_is_visible(entry, category=category)]

    def _search_entry_is_visible(self, entry: MemoryEntry, *, category: str | None) -> bool:
        """Return whether a search result is visible for the requested category."""

        if category is not None:
            return entry.category == category
        return entry.category not in _GENERIC_RETRIEVAL_EXCLUDED_CATEGORIES

    def _normalize_text(self, value: Any) -> str:
        """Normalize text for deterministic conversation comparisons."""

        return " ".join(str(value or "").strip().lower().split())

    def _conversation_query_tokens(self, query: str | None) -> tuple[str, ...]:
        """Extract meaningful tokens from an explicit conversation query."""

        tokens = (
            token
            for token in _TOKEN_PATTERN.findall(self._normalize_text(query))
            if token not in _CONVERSATION_QUERY_STOP_WORDS
        )
        return tuple(dict.fromkeys(tokens))

    def _normalize_user_id(self, user_id: str | None) -> str:
        """Resolve the stable local profile identity used by the current runtime."""

        return str(user_id or "").strip() or _DEFAULT_PROFILE_USER_ID

    def _normalize_profile_fact_key(self, key: str) -> str:
        """Normalize natural profile labels to stable profile dictionary keys."""

        normalized = "_".join(_TOKEN_PATTERN.findall(str(key or "").lower())).strip("_")
        if normalized.startswith("my_"):
            normalized = normalized[3:]
        if normalized in {"name", "full_name", "display_name"}:
            return "display_name"
        return normalized or "memory"

    def _format_context_entry(self, entry: MemoryEntry) -> str:
        """Format one persisted entry for provider-backed AI context."""

        if entry.category == "profile":
            profile = UserProfile.from_value(str(entry.metadata.get("user_id", "")), entry.value)
            if profile is not None:
                details: list[str] = []
                if profile.display_name:
                    details.append(f"display name={profile.display_name}")
                details.extend(f"{key}={value}" for key, value in sorted(profile.preferences.items()))
                details.extend(f"{key}={value}" for key, value in sorted(profile.traits.items()))
                if details:
                    return f"profile {entry.key}: " + ", ".join(details)[:160]
        value = str(entry.value).replace("\n", " ").strip()
        return f"{entry.category} {entry.key}: {value[:160]}"

    def _entry_is_visible_in_context(
        self,
        entry: MemoryEntry,
        *,
        session_id: str | None,
        conversation_id: str | None,
        user_id: str,
    ) -> bool:
        """Return whether one persisted entry may appear in a generic context summary."""

        if entry.category == "conversation_history":
            # Conversation turns are already provided through the dedicated history/context path.
            # They must not behave like globally retrievable memory snippets.
            return False
        if entry.category in _GENERIC_RETRIEVAL_EXCLUDED_CATEGORIES:
            return False

        if entry.category == "profile":
            return entry.metadata.get("user_id") == user_id

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
    "ProfileMemoryFact",
    "build_memory_integration_service",
    "register_memory_integration_services",
]
