"""Export-ready conversation abstractions with no file-writing capability."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
import re
from typing import Any, Protocol

from Conversation.core.models import ConversationSession, new_id, utc_now

from .exceptions import ConversationExportError
from .models import ArchiveMetadata, ConversationExport, ExportFormat

_UNSAFE_HINT = re.compile(r"[^a-zA-Z0-9_-]+")


class ExportBuilder(Protocol):
    """Replaceable contract that prepares data but never writes it."""

    def prepare(
        self,
        session: ConversationSession,
        *,
        format: ExportFormat = ExportFormat.JSON,
        archive: ArchiveMetadata | None = None,
        include_metadata: bool = True,
    ) -> ConversationExport:
        """Prepare one immutable export artifact."""


class ConversationExportBuilder:
    """Build structured, text, or Markdown artifacts entirely in memory."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory

    def prepare(
        self,
        session: ConversationSession,
        *,
        format: ExportFormat = ExportFormat.JSON,
        archive: ArchiveMetadata | None = None,
        include_metadata: bool = True,
    ) -> ConversationExport:
        """Return an export-ready artifact without opening or writing a file."""

        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        if not isinstance(format, ExportFormat):
            raise ConversationExportError("format must be an ExportFormat")
        if archive is not None and not isinstance(archive, ArchiveMetadata):
            raise ConversationExportError("archive must be ArchiveMetadata or None")
        if archive is not None and archive.conversation_id != session.session_id:
            raise ConversationExportError("archive belongs to another conversation")
        if not isinstance(include_metadata, bool):
            raise ConversationExportError("include_metadata must be a bool")

        structured = self._structured(session, archive, include_metadata)
        if format is ExportFormat.JSON:
            content: Mapping[str, Any] | str = structured
            mime_type = "application/json"
            extension = "json"
        elif format is ExportFormat.TEXT:
            content = self._text(session, archive, markdown=False)
            mime_type = "text/plain"
            extension = "txt"
        else:
            content = self._text(session, archive, markdown=True)
            mime_type = "text/markdown"
            extension = "md"
        safe_id = _UNSAFE_HINT.sub("-", session.session_id).strip("-") or "session"
        return ConversationExport(
            conversation_id=session.session_id,
            format=format,
            content=content,
            mime_type=mime_type,
            filename_hint=f"conversation-{safe_id}.{extension}",
            message_count=session.history.count,
            generated_at=self._now(),
            export_id=self._id_factory(),
        )

    @staticmethod
    def _structured(
        session: ConversationSession,
        archive: ArchiveMetadata | None,
        include_metadata: bool,
    ) -> Mapping[str, Any]:
        context = session.context
        payload: dict[str, Any] = {
            "conversation_id": session.session_id,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "closed_at": (
                session.closed_at.isoformat() if session.closed_at is not None else None
            ),
            "archived_at": (
                session.archived_at.isoformat()
                if session.archived_at is not None
                else None
            ),
            "expires_at": (
                session.expires_at.isoformat()
                if session.expires_at is not None
                else None
            ),
            "expired_at": (
                session.expired_at.isoformat()
                if session.expired_at is not None
                else None
            ),
            "context": {
                "active_topic": context.active_topic,
                "previous_topic": context.previous_topic,
                "summary": context.summary,
                "referenced_memories": context.referenced_memories,
                "referenced_skills": context.referenced_skills,
                "referenced_agents": context.referenced_agents,
            },
            "messages": tuple(
                {
                    "message_id": message.message_id,
                    "role": message.role.value,
                    "content": message.content,
                    "timestamp": message.timestamp.isoformat(),
                    **(
                        {"metadata": _export_safe(message.metadata)}
                        if include_metadata
                        else {}
                    ),
                }
                for message in session.messages
            ),
            "cleared_message_count": session.history.cleared_messages,
        }
        if include_metadata:
            payload["metadata"] = _export_safe(session.metadata)
            payload["context"]["metadata"] = _export_safe(context.metadata)
        if archive is not None:
            payload["archive"] = {
                "archive_id": archive.archive_id,
                "archived_at": archive.archived_at.isoformat(),
                "restored_at": (
                    archive.restored_at.isoformat()
                    if archive.restored_at is not None
                    else None
                ),
                "reason": archive.reason,
                "tags": archive.tags,
                "retention_until": (
                    archive.retention_until.isoformat()
                    if archive.retention_until is not None
                    else None
                ),
                **(
                    {"metadata": _export_safe(archive.metadata)}
                    if include_metadata
                    else {}
                ),
            }
        return payload

    @staticmethod
    def _text(
        session: ConversationSession,
        archive: ArchiveMetadata | None,
        *,
        markdown: bool,
    ) -> str:
        title = f"Conversation {session.session_id}"
        lines = [f"# {title}" if markdown else title]
        lines.append(f"Status: {session.status.value}")
        if archive is not None:
            lines.append(f"Archive reason: {archive.reason or 'not specified'}")
        if session.context.summary:
            lines.extend(("", "Summary", session.context.summary))
        lines.append("")
        for message in session.messages:
            role = message.role.value.capitalize()
            prefix = f"## {role}" if markdown else f"{role}:"
            lines.extend((prefix, message.content, ""))
        return "\n".join(lines).rstrip()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ConversationExportError("export clock must return an aware datetime")
        return value


def _export_safe(value: Any) -> Any:
    """Detach arbitrary metadata into export-friendly in-memory primitives."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _export_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_export_safe(item) for item in value)
    return str(value)


ConversationExporter = ConversationExportBuilder


__all__ = ["ConversationExportBuilder", "ConversationExporter", "ExportBuilder"]
