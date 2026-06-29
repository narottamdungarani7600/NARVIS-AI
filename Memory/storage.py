"""Storage abstractions for the NARVIS Memory package.

This module provides reusable repository interfaces and concrete implementations
for SQLite persistence and JSON backup support without embedding AI logic.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import MemoryEntry, MemoryRepository


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

    def __init__(self, database_path: str | Path = "memory.db") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create the required schema if it does not already exist."""
        with sqlite3.connect(self.database_path) as connection:
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
            connection.commit()

    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry into SQLite."""
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO memory_entries (
                    key, value, category, importance, timestamp, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.key,
                    json.dumps(entry.value, default=str),
                    entry.category,
                    entry.importance,
                    entry.timestamp.isoformat(),
                    json.dumps(entry.metadata, default=str),
                ),
            )
            connection.commit()

    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by key from SQLite."""
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT key, value, category, importance, timestamp, metadata FROM memory_entries WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def delete(self, key: str) -> None:
        """Delete a memory entry from SQLite."""
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("DELETE FROM memory_entries WHERE key = ?", (key,))
            connection.commit()

    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """List stored entries, optionally filtered by category."""
        with sqlite3.connect(self.database_path) as connection:
            if category is None:
                rows = connection.execute(
                    "SELECT key, value, category, importance, timestamp, metadata FROM memory_entries"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT key, value, category, importance, timestamp, metadata FROM memory_entries WHERE category = ?",
                    (category,),
                ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: tuple[Any, ...]) -> MemoryEntry:
        """Convert a database row into a MemoryEntry object."""
        key, value, category, importance, timestamp, metadata = row
        return MemoryEntry(
            key=key,
            value=json.loads(value),
            category=category,
            importance=float(importance),
            timestamp=datetime.fromisoformat(timestamp),
            metadata=json.loads(metadata),
        )


class JSONBackupStore(BaseStorage):
    """JSON file-backed backup store for memory entries."""

    def __init__(self, file_path: str | Path = "memory_backup.json") -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")

    def save(self, entry: MemoryEntry) -> None:
        """Persist a memory entry into a JSON backup file."""
        entries = self._load_all()
        existing = {item["key"]: item for item in entries}
        existing[entry.key] = self._entry_to_dict(entry)
        self.file_path.write_text(json.dumps(list(existing.values()), indent=2), encoding="utf-8")

    def load(self, key: str) -> MemoryEntry | None:
        """Load a memory entry by key from the JSON backup file."""
        for item in self._load_all():
            if item["key"] == key:
                return self._dict_to_entry(item)
        return None

    def delete(self, key: str) -> None:
        """Delete a memory entry from the JSON backup file."""
        entries = [item for item in self._load_all() if item["key"] != key]
        self.file_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def list_entries(self, category: str | None = None) -> list[MemoryEntry]:
        """List stored entries, optionally filtered by category."""
        entries = self._load_all()
        if category is None:
            return [self._dict_to_entry(item) for item in entries]
        return [self._dict_to_entry(item) for item in entries if item.get("category") == category]

    def _load_all(self) -> list[dict[str, Any]]:
        """Load all entries from the backup file."""
        return json.loads(self.file_path.read_text(encoding="utf-8"))

    def _entry_to_dict(self, entry: MemoryEntry) -> dict[str, Any]:
        """Convert a MemoryEntry to a serializable dictionary."""
        return {
            "key": entry.key,
            "value": entry.value,
            "category": entry.category,
            "importance": entry.importance,
            "timestamp": entry.timestamp.isoformat(),
            "metadata": entry.metadata,
        }

    def _dict_to_entry(self, item: dict[str, Any]) -> MemoryEntry:
        """Convert a dictionary entry to a MemoryEntry."""
        return MemoryEntry(
            key=item["key"],
            value=item["value"],
            category=item.get("category", "general"),
            importance=float(item.get("importance", 0.0)),
            timestamp=datetime.fromisoformat(item.get("timestamp", datetime.now(timezone.utc).isoformat())),
            metadata=item.get("metadata", {}),
        )
