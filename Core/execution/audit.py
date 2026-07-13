"""Immutable in-memory audit logging for trusted execution lifecycles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Protocol, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger

from .models import AuditEntry, AuditStage


class AuditRecorder(Protocol):
    """Audit contract consumed by the trusted gateway."""

    def record(
        self,
        *,
        request_id: str,
        action: str,
        stage: AuditStage,
        outcome: str,
        details: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Record one immutable lifecycle entry."""

    def for_request(self, request_id: str) -> tuple[AuditEntry, ...]:
        """Return entries correlated with a request."""


@runtime_checkable
class AuditBackend(Protocol):
    """Future persistence contract for immutable audit entries."""

    def append(self, entry: AuditEntry) -> None:
        """Persist one immutable audit entry."""


@runtime_checkable
class AuditExporter(Protocol):
    """Future export contract for an immutable audit snapshot."""

    def export(self, entries: tuple[AuditEntry, ...]) -> object:
        """Export a complete immutable snapshot."""


def _utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


class AuditLogger:
    """Record immutable, timestamped lifecycle entries in append-only order."""

    def __init__(
        self,
        backend: AuditBackend | None = None,
        *,
        logger: Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize in-memory storage and an optional persistence backend."""

        if backend is not None and not isinstance(backend, AuditBackend):
            raise TypeError("audit backends must implement append(entry)")
        self._backend = backend
        self._logger = logger or NullLogger("narvis.execution.audit")
        self._clock = clock or _utc_now
        self._entries: list[AuditEntry] = []
        self._lock = RLock()

    @property
    def backend(self) -> AuditBackend | None:
        """Return the configured persistence backend, if any."""

        return self._backend

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        """Return an immutable snapshot in append order."""

        with self._lock:
            return tuple(self._entries)

    def record(
        self,
        *,
        request_id: str,
        action: str,
        stage: AuditStage,
        outcome: str,
        details: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Create, retain, and optionally persist one lifecycle entry."""

        if not isinstance(stage, AuditStage):
            raise TypeError("audit stage must be an AuditStage")
        timestamp = self._clock()
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("audit clocks must return timezone-aware datetimes")
        entry = AuditEntry(
            request_id=request_id,
            action=action,
            stage=stage,
            outcome=outcome,
            details=details or {},
            timestamp=timestamp,
        )
        self.append(entry)
        return entry

    def append(self, entry: AuditEntry) -> None:
        """Append an existing immutable entry and mirror it to the backend."""

        if not isinstance(entry, AuditEntry):
            raise TypeError("audit logs accept AuditEntry instances")
        with self._lock:
            self._entries.append(entry)

        if self._backend is not None:
            try:
                self._backend.append(entry)
            except Exception as error:
                self._log(
                    LogLevel.WARNING,
                    "Unable to persist execution audit entry",
                    entry_id=entry.entry_id,
                    request_id=entry.request_id,
                    stage=entry.stage.value,
                    error_type=type(error).__name__,
                )

        self._log(
            LogLevel.INFO,
            "Execution audit entry recorded",
            entry_id=entry.entry_id,
            request_id=entry.request_id,
            action=entry.action,
            stage=entry.stage.value,
            outcome=entry.outcome,
        )

    def log(
        self,
        *,
        request_id: str,
        action: str,
        stage: AuditStage,
        outcome: str,
        details: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Record an entry using logger-oriented terminology."""

        return self.record(
            request_id=request_id,
            action=action,
            stage=stage,
            outcome=outcome,
            details=details,
        )

    def for_request(self, request_id: str) -> tuple[AuditEntry, ...]:
        """Return an immutable snapshot for one correlated request."""

        return tuple(
            entry for entry in self.entries if entry.request_id == request_id
        )

    def export(self, exporter: AuditExporter | None = None) -> object:
        """Return a snapshot or pass it to an injected future exporter."""

        snapshot = self.entries
        if exporter is None:
            return snapshot
        if not isinstance(exporter, AuditExporter):
            raise TypeError("audit exporters must implement export(entries)")
        return exporter.export(snapshot)

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a structured log without changing audit retention."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["AuditBackend", "AuditExporter", "AuditLogger", "AuditRecorder"]
