"""Storage backends for the NARVIS Memory package.

The Memory module persists records through repository implementations. The
primary backend is SQLite for durable local storage, with a JSON backup store
kept as a lightweight secondary option for testing or export workflows.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .memory import MemoryEntry, MemoryRepository, _emit_log, utc_now

_TYPE_KEY = "__narvis_type__"


def _serialize_payload(value: Any) -> Any:
    """Convert a Python value into a JSON-serializable structure."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return {_TYPE_KEY: "datetime", "value": value.isoformat()}
    if isinstance(value, Path):
        return {_TYPE_KEY: "path", "value": str(value)}
    if isinstance(value, dict):
        return {str(key): _serialize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_payload(item) for item in value]
    if isinstance(value, tuple):
        return {_TYPE_KEY: "tuple", "items": [_serialize_payload(item) for item in value]}
    if isinstance(value, set):
        return {_TYPE_KEY: "set", "items": [_serialize_payload(item) for item in sorted(value, key=str)]}
    if is_dataclass(value):
        return {
            _TYPE_KEY: "dataclass",
            "class": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
            "fields": _serialize_payload(asdict(value)),
        }
    return {
        _TYPE_KEY: "repr",
        "class": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
        "value": str(value),
    }


def _import_type(dotted_path: str) -> Any | None:
    """Import a dotted class path used by the serializer."""

    if not dotted_path or "." not in dotted_path:
        return None
    module_name, _, class_name = dotted_path.rpartition(".")
    try:
        module = __import__(module_name, fromlist=[class_name])
        return getattr(module, class_name, None)
    except Exception:
        return None


def _deserialize_payload(value: Any) -> Any:
    """Restore Python values from the repository serialization format."""

    if isinstance(value, list):
        return [_deserialize_payload(item) for item in value]
    if not isinstance(value, dict):
        return value

    payload_type = value.get(_TYPE_KEY)
    if payload_type is None:
        return {key: _deserialize_payload(item) for key, item in value.items()}

    if payload_type == "datetime":
        try:
            return datetime.fromisoformat(str(value.get("value", utc_now().isoformat())))
        except ValueError:
            return utc_now()
    if payload_type == "path":
        return Path(str(value.get("value", "")))
    if payload_type == "tuple":
        return tuple(_deserialize_payload(item) for item in value.get("items", []))
    if payload_type == "set":
        return set(_deserialize_payload(item) for item in value.get("items", []))
    if payload_type == "dataclass":
        dataclass_type = _import_type(str(value.get("class", "")))
        fields = _deserialize_payload(value.get("fields", {}))
        if dataclass_type is not None:
            try:
                return dataclass_type(**fields)
            except Exception:
                return fields
        return fields
    if payload_type == "repr":
        return value.get("value")
    return {key: _deserialize_payload(item) for key, item in value.items() if key != _TYPE_KEY}


class BaseStorage(MemoryRepository, ABC):
    """Abstract base class for memory storage backends."""

    @abstractmethod
    def save(self, entry: MemoryEntry) -> None:
        """Persist an entry."""

    @abstractmethod
    def load(self, key: str) -> MemoryEntry | None:
        """Load an entry by key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete an entry by key."""

    @abstractmethod
    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """List stored entries optionally filtered by category."""


class SQLiteMemoryStore(BaseStorage):
    """SQLite-backed repository for durable memory persistence."""

    def __init__(self, database_path: str | Path = "memory.db", logger: Any | None = None) -> None:
        self.database_path = Path(database_path)
        self.logger = logger
        self._lock = RLock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        """Create a configured SQLite connection."""

        connection = sqlite3.connect(self.database_path, timeout=30.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize_schema(self) -> None:
        """Create the required schema if it does not already exist."""

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL,
                    importance REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_entries_category ON memory_entries(category)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_entries_timestamp ON memory_entries(timestamp DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_entries_importance ON memory_entries(importance DESC)"
            )
            connection.commit()
        _emit_log(self.logger, "info", "Initialized SQLite memory schema", database_path=str(self.database_path))

    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry into SQLite."""

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_entries (key, value, category, importance, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    importance = excluded.importance,
                    timestamp = excluded.timestamp,
                    metadata = excluded.metadata
                """,
                (
                    entry.key,
                    json.dumps(_serialize_payload(entry.value), separators=(",", ":"), sort_keys=True),
                    entry.category,
                    float(entry.importance),
                    entry.timestamp.isoformat(),
                    json.dumps(_serialize_payload(entry.metadata), separators=(",", ":"), sort_keys=True),
                ),
            )
            connection.commit()
        _emit_log(
            self.logger,
            "debug",
            "Saved memory entry",
            key=entry.key,
            category=entry.category,
            importance=entry.importance,
        )

    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by key from SQLite."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT key, value, category, importance, timestamp, metadata
                FROM memory_entries
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            _emit_log(self.logger, "debug", "Memory entry not found", key=key)
            return None
        entry = self._row_to_entry(row)
        _emit_log(self.logger, "debug", "Loaded memory entry", key=key, category=entry.category)
        return entry

    def delete(self, key: str) -> None:
        """Delete a memory entry from SQLite."""

        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM memory_entries WHERE key = ?", (key,))
            connection.commit()
        _emit_log(self.logger, "debug", "Deleted memory entry", key=key, deleted=cursor.rowcount > 0)

    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """List stored entries, optionally filtered by category."""

        query = """
            SELECT key, value, category, importance, timestamp, metadata
            FROM memory_entries
        """
        parameters: tuple[Any, ...] = ()
        if category is not None:
            query += " WHERE category = ?"
            parameters = (category,)
        query += " ORDER BY importance DESC, timestamp DESC"

        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        entries = [self._row_to_entry(row) for row in rows]
        _emit_log(self.logger, "debug", "Listed memory entries", category=category, count=len(entries))
        return entries

    def search_entries(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Perform a lightweight SQLite-backed text search over memory entries."""

        normalized_query = query.strip().lower()
        if not normalized_query:
            return []

        sql = """
            SELECT key, value, category, importance, timestamp, metadata
            FROM memory_entries
            WHERE
                (? IS NULL OR category = ?)
                AND (
                    LOWER(key) LIKE ?
                    OR LOWER(value) LIKE ?
                    OR LOWER(metadata) LIKE ?
                )
            ORDER BY importance DESC, timestamp DESC
            LIMIT ?
        """
        like_value = f"%{normalized_query}%"
        parameters = (category, category, like_value, like_value, like_value, max(limit, 1))

        with self._lock, self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        entries = [self._row_to_entry(row) for row in rows]
        _emit_log(
            self.logger,
            "debug",
            "Searched memory entries",
            query=query,
            category=category,
            count=len(entries),
        )
        return entries

    def _row_to_entry(self, row: sqlite3.Row | tuple[Any, ...]) -> MemoryEntry:
        """Convert a database row into a MemoryEntry object."""

        key, value, category, importance, timestamp, metadata = tuple(row)
        return MemoryEntry(
            key=str(key),
            value=_deserialize_payload(json.loads(str(value))),
            category=str(category),
            importance=float(importance),
            timestamp=datetime.fromisoformat(str(timestamp)),
            metadata=_deserialize_payload(json.loads(str(metadata))),
        )


class JSONBackupStore(BaseStorage):
    """JSON file-backed backup store for memory entries."""

    def __init__(self, file_path: str | Path = "memory_backup.json", logger: Any | None = None) -> None:
        self.file_path = Path(file_path)
        self.logger = logger
        self._lock = RLock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")

    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry into a JSON backup file."""

        entries = {item["key"]: item for item in self._load_all()}
        entries[entry.key] = self._entry_to_dict(entry)
        with self._lock:
            self.file_path.write_text(json.dumps(list(entries.values()), indent=2, sort_keys=True), encoding="utf-8")
        _emit_log(self.logger, "debug", "Saved backup memory entry", key=entry.key)

    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by key from the JSON backup file."""

        for item in self._load_all():
            if item["key"] == key:
                return self._dict_to_entry(item)
        return None

    def delete(self, key: str) -> None:
        """Delete a memory entry from the JSON backup file."""

        entries = [item for item in self._load_all() if item["key"] != key]
        with self._lock:
            self.file_path.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
        _emit_log(self.logger, "debug", "Deleted backup memory entry", key=key)

    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """List stored entries, optionally filtered by category."""

        entries = [self._dict_to_entry(item) for item in self._load_all()]
        if category is None:
            return entries
        return [entry for entry in entries if entry.category == category]

    def _load_all(self) -> list[dict[str, Any]]:
        """Load all entries from the backup file."""

        with self._lock:
            raw_text = self.file_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return []
        return json.loads(raw_text)

    def _entry_to_dict(self, entry: MemoryEntry) -> dict[str, Any]:
        """Convert a MemoryEntry to a serializable dictionary."""

        return {
            "key": entry.key,
            "value": _serialize_payload(entry.value),
            "category": entry.category,
            "importance": entry.importance,
            "timestamp": entry.timestamp.isoformat(),
            "metadata": _serialize_payload(entry.metadata),
        }

    def _dict_to_entry(self, item: dict[str, Any]) -> MemoryEntry:
        """Convert a dictionary entry to a MemoryEntry."""

        return MemoryEntry(
            key=str(item["key"]),
            value=_deserialize_payload(item.get("value")),
            category=str(item.get("category", "general")),
            importance=float(item.get("importance", 0.0)),
            timestamp=datetime.fromisoformat(str(item.get("timestamp", utc_now().isoformat()))),
            metadata=_deserialize_payload(item.get("metadata", {})),
        )


__all__ = ["BaseStorage", "JSONBackupStore", "SQLiteMemoryStore"]
