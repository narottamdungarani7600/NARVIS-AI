"""Core memory abstractions and runtime wiring helpers for NARVIS.

This module defines the shared data structures used by the Memory package and
provides lightweight builder and registration helpers so the memory subsystem
can be injected into the runtime without hard-coding concrete implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .long_term import BaseLongTermMemory
    from .profile import BaseProfileMemory
    from .ranking import BaseMemoryRanker, MemoryScorer
    from .search import BaseMemorySearch
    from .session import BaseSessionMemory
    from .short_term import BaseShortTermMemory


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


def _coerce_utc_timestamp(value: datetime) -> datetime:
    """Normalize datetime values to timezone-aware UTC timestamps."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_text(value: Any) -> str:
    """Flatten a Python value into searchable plain text."""

    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, datetime):
        return _coerce_utc_timestamp(value).isoformat()
    if isinstance(value, dict):
        return " ".join(
            part
            for key, item in value.items()
            for part in (normalize_text(key), normalize_text(item))
            if part
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(part for item in value for part in (normalize_text(item),) if part)
    return str(value)


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


@dataclass(slots=True)
class MemoryEntry:
    """Represents a single memory record stored by the system."""

    key: str
    value: Any
    category: str = "general"
    importance: float = 0.0
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize fields after initialization."""

        self.timestamp = _coerce_utc_timestamp(self.timestamp)
        if self.metadata is None:
            self.metadata = {}

    def text_content(self) -> str:
        """Return a flattened text view used by search and ranking services."""

        return " ".join(
            part
            for part in (
                normalize_text(self.key),
                normalize_text(self.category),
                normalize_text(self.value),
                normalize_text(self.metadata),
            )
            if part
        )


class MemoryStore(Protocol):
    """Protocol for storage implementations used by the memory system."""

    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry."""

    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by its key."""

    def delete(self, key: str) -> None:
        """Delete a memory entry by its key."""

    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """Return stored memory entries, optionally filtered by category."""


class MemoryRepository(ABC):
    """Abstract repository interface for memory-backed services."""

    @abstractmethod
    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry."""

    @abstractmethod
    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by its key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a memory entry by its key."""

    @abstractmethod
    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """Return stored memory entries, optionally filtered by category."""


class SemanticMemory(Protocol):
    """Protocol for future semantic memory backends such as vector databases."""

    def add(self, entry: MemoryEntry) -> None:
        """Add a memory entry to the semantic memory backend."""

    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Search semantic memory using a query string."""


class DependencyRegistrar(Protocol):
    """Protocol for dependency injection containers used by Memory."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class EventPublisher(Protocol):
    """Protocol for runtime event buses used by Memory registration hooks."""

    def publish(self, event: Any) -> None:
        """Publish a runtime event."""


@dataclass(slots=True)
class MemoryServices:
    """Container for the concrete services that make up the Memory module."""

    storage: MemoryRepository
    short_term_memory: BaseShortTermMemory
    long_term_memory: BaseLongTermMemory
    session_memory: BaseSessionMemory
    profile_memory: BaseProfileMemory
    memory_search: BaseMemorySearch
    memory_ranker: BaseMemoryRanker
    memory_scorer: MemoryScorer


def build_memory_services(
    *,
    database_path: str | Path = "memory.db",
    storage: MemoryRepository | None = None,
    short_term_memory: BaseShortTermMemory | None = None,
    long_term_memory: BaseLongTermMemory | None = None,
    session_memory: BaseSessionMemory | None = None,
    profile_memory: BaseProfileMemory | None = None,
    memory_search: BaseMemorySearch | None = None,
    memory_ranker: BaseMemoryRanker | None = None,
    memory_scorer: MemoryScorer | None = None,
    logger: Any | None = None,
) -> MemoryServices:
    """Create a complete set of Memory services using constructor injection."""

    from .long_term import InMemoryLongTermMemory
    from .profile import InMemoryProfileMemory
    from .ranking import ImportanceRanker, MemoryScorer as DefaultMemoryScorer
    from .search import SimpleMemorySearch
    from .session import InMemorySessionMemory
    from .short_term import InMemoryShortTermMemory
    from .storage import SQLiteMemoryStore

    resolved_storage = storage or SQLiteMemoryStore(database_path=database_path, logger=logger)
    resolved_scorer = memory_scorer or DefaultMemoryScorer(logger=logger)
    resolved_ranker = memory_ranker or ImportanceRanker(logger=logger)
    resolved_short_term = short_term_memory or InMemoryShortTermMemory(
        repository=resolved_storage,
        scorer=resolved_scorer,
        logger=logger,
    )
    resolved_long_term = long_term_memory or InMemoryLongTermMemory(
        repository=resolved_storage,
        scorer=resolved_scorer,
        logger=logger,
    )
    resolved_session = session_memory or InMemorySessionMemory(
        repository=resolved_storage,
        logger=logger,
    )
    resolved_profile = profile_memory or InMemoryProfileMemory(
        repository=resolved_storage,
        logger=logger,
    )
    resolved_search = memory_search or SimpleMemorySearch(
        repository=resolved_storage,
        ranker=resolved_ranker,
        logger=logger,
    )

    services = MemoryServices(
        storage=resolved_storage,
        short_term_memory=resolved_short_term,
        long_term_memory=resolved_long_term,
        session_memory=resolved_session,
        profile_memory=resolved_profile,
        memory_search=resolved_search,
        memory_ranker=resolved_ranker,
        memory_scorer=resolved_scorer,
    )
    _emit_log(
        logger,
        "info",
        "Built memory services",
        database_path=str(database_path),
        storage_type=type(resolved_storage).__name__,
    )
    return services


def register_memory_services(
    container: DependencyRegistrar,
    *,
    database_path: str | Path = "memory.db",
    services: MemoryServices | None = None,
    logger: Any | None = None,
) -> MemoryServices:
    """Register the Memory module services in a dependency injection container."""

    resolved_services = services or build_memory_services(database_path=database_path, logger=logger)
    container.register_instance("memory_storage", resolved_services.storage)
    container.register_instance("memory_repository", resolved_services.storage)
    container.register_instance("short_term_memory", resolved_services.short_term_memory)
    container.register_instance("long_term_memory", resolved_services.long_term_memory)
    container.register_instance("session_memory", resolved_services.session_memory)
    container.register_instance("profile_memory", resolved_services.profile_memory)
    container.register_instance("memory_search", resolved_services.memory_search)
    container.register_instance("memory_ranker", resolved_services.memory_ranker)
    container.register_instance("memory_scorer", resolved_services.memory_scorer)
    _emit_log(logger, "info", "Registered memory services in container")
    return resolved_services


class MemoryRuntimeHook:
    """Runtime hook that registers Memory services during plugin or startup load."""

    def __init__(
        self,
        *,
        database_path: str | Path = "memory.db",
        services: MemoryServices | None = None,
        logger: Any | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.services = services
        self.logger = logger

    def load(
        self,
        container: DependencyRegistrar,
        event_bus: EventPublisher | None = None,
        logger: Any | None = None,
    ) -> None:
        """Register Memory services into the runtime and emit a ready event."""

        resolved_logger = logger or self.logger
        self.services = register_memory_services(
            container,
            database_path=self.database_path,
            services=self.services,
            logger=resolved_logger,
        )
        if event_bus is not None:
            try:
                from Core.system import SystemEvent

                event_bus.publish(
                    SystemEvent(
                        name="memory.services.registered",
                        payload={"database_path": str(self.database_path)},
                    )
                )
            except Exception:
                _emit_log(resolved_logger, "warning", "Unable to publish memory registration event")
        _emit_log(resolved_logger, "info", "Memory runtime hook completed")


__all__ = [
    "DependencyRegistrar",
    "EventPublisher",
    "MemoryEntry",
    "MemoryRepository",
    "MemoryRuntimeHook",
    "MemoryServices",
    "MemoryStore",
    "SemanticMemory",
    "build_memory_services",
    "normalize_text",
    "register_memory_services",
    "utc_now",
]
