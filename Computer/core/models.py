"""Strongly typed models for the NARVIS Computer service foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any


class ComputerStatus(str, Enum):
    """Provider health states understood by the Computer service layer."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"


class FileSystemEntryKind(str, Enum):
    """Read-only filesystem entry kinds returned by providers."""

    FILE = "file"
    DIRECTORY = "directory"
    OTHER = "other"


def _require_normalized_text(value: object, field_name: str) -> str:
    """Return validated non-empty text without changing caller input."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


def _immutable_mapping(
    value: Mapping[str, Any],
    field_name: str,
) -> Mapping[str, Any]:
    """Validate and detach a mapping used by an immutable model."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


def _validate_optional_text(value: object, field_name: str) -> None:
    """Validate optional textual metadata without normalizing provider data."""

    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")


def _validate_optional_datetime(value: object, field_name: str) -> None:
    """Validate an optional provider-supplied timestamp."""

    if value is not None and not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime or None")


@dataclass(slots=True, frozen=True)
class ComputerCapability:
    """One inert capability advertised by a computer provider."""

    name: str
    description: str = ""
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "capability name")
        if not isinstance(self.description, str):
            raise TypeError("capability description must be a string")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "capability attributes"),
        )

    @property
    def capability_id(self) -> str:
        """Return the stable capability identifier."""

        return self.name


@dataclass(slots=True, frozen=True)
class ComputerProviderInfo:
    """Immutable identity and descriptive metadata for a provider."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    vendor: str = ""
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "provider name")
        _require_normalized_text(self.version, "provider version")
        if not isinstance(self.description, str):
            raise TypeError("provider description must be a string")
        if not isinstance(self.vendor, str):
            raise TypeError("provider vendor must be a string")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "provider attributes"),
        )

    @property
    def provider_id(self) -> str:
        """Return the registry identifier for this provider."""

        return self.name


@dataclass(slots=True, frozen=True)
class ComputerHealth:
    """A provider-supplied health observation with detached details."""

    status: ComputerStatus = ComputerStatus.UNKNOWN
    message: str = ""
    details: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComputerStatus):
            raise TypeError("computer health status must be a ComputerStatus")
        if not isinstance(self.message, str):
            raise TypeError("computer health message must be a string")
        object.__setattr__(
            self,
            "details",
            _immutable_mapping(self.details, "computer health details"),
        )

    @property
    def is_healthy(self) -> bool:
        """Return whether this observation represents full health."""

        return self.status is ComputerStatus.HEALTHY


@dataclass(slots=True, frozen=True)
class FileMetadata:
    """Metadata for one filesystem entry without any file-content access."""

    path: str
    name: str
    kind: FileSystemEntryKind
    size_bytes: int | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    accessed_at: datetime | None = None
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_normalized_text(self.path, "file path")
        _require_normalized_text(self.name, "file name")
        if not isinstance(self.kind, FileSystemEntryKind):
            raise TypeError("file kind must be a FileSystemEntryKind")
        if self.size_bytes is not None and (
            not isinstance(self.size_bytes, int) or self.size_bytes < 0
        ):
            raise ValueError("file size_bytes must be a non-negative integer or None")
        _validate_optional_datetime(self.created_at, "file created_at")
        _validate_optional_datetime(self.modified_at, "file modified_at")
        _validate_optional_datetime(self.accessed_at, "file accessed_at")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "file attributes"),
        )

    @property
    def is_file(self) -> bool:
        """Return whether the entry represents a regular file."""

        return self.kind is FileSystemEntryKind.FILE

    @property
    def is_directory(self) -> bool:
        """Return whether the entry represents a directory."""

        return self.kind is FileSystemEntryKind.DIRECTORY


@dataclass(slots=True, frozen=True)
class ProcessMetadata:
    """Safe descriptive metadata for one running process."""

    pid: int
    name: str
    status: str = ""
    executable: str | None = None
    username: str | None = None
    started_at: datetime | None = None
    memory_bytes: int | None = None
    cpu_percent: float | None = None
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid < 0:
            raise ValueError("process pid must be a non-negative integer")
        _require_normalized_text(self.name, "process name")
        if not isinstance(self.status, str):
            raise TypeError("process status must be a string")
        _validate_optional_text(self.executable, "process executable")
        _validate_optional_text(self.username, "process username")
        _validate_optional_datetime(self.started_at, "process started_at")
        if self.memory_bytes is not None and (
            not isinstance(self.memory_bytes, int) or self.memory_bytes < 0
        ):
            raise ValueError(
                "process memory_bytes must be a non-negative integer or None"
            )
        if self.cpu_percent is not None and (
            not isinstance(self.cpu_percent, (int, float))
            or isinstance(self.cpu_percent, bool)
            or self.cpu_percent < 0
        ):
            raise ValueError(
                "process cpu_percent must be a non-negative number or None"
            )
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "process attributes"),
        )


@dataclass(slots=True, frozen=True)
class ClipboardMetadata:
    """Non-content clipboard state for a text-only clipboard provider."""

    available: bool
    contains_text: bool = False
    text_length: int = 0
    updated_at: datetime | None = None
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.available, bool):
            raise TypeError("clipboard available must be a bool")
        if not isinstance(self.contains_text, bool):
            raise TypeError("clipboard contains_text must be a bool")
        if (
            not isinstance(self.text_length, int)
            or isinstance(self.text_length, bool)
            or self.text_length < 0
        ):
            raise ValueError("clipboard text_length must be a non-negative integer")
        if not self.available and (self.contains_text or self.text_length):
            raise ValueError("an unavailable clipboard cannot contain text")
        if not self.contains_text and self.text_length:
            raise ValueError("clipboard text_length requires contains_text")
        _validate_optional_datetime(self.updated_at, "clipboard updated_at")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "clipboard attributes"),
        )


@dataclass(slots=True, frozen=True)
class ApplicationInfo:
    """Read-only metadata for an installed or running application."""

    application_id: str
    name: str
    version: str | None = None
    publisher: str | None = None
    executable: str | None = None
    is_running: bool = False
    process_id: int | None = None
    provider_name: str = ""
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_normalized_text(self.application_id, "application id")
        _require_normalized_text(self.name, "application name")
        _validate_optional_text(self.version, "application version")
        _validate_optional_text(self.publisher, "application publisher")
        _validate_optional_text(self.executable, "application executable")
        if not isinstance(self.is_running, bool):
            raise TypeError("application is_running must be a bool")
        if self.process_id is not None and (
            not isinstance(self.process_id, int)
            or isinstance(self.process_id, bool)
            or self.process_id < 0
        ):
            raise ValueError(
                "application process_id must be a non-negative integer or None"
            )
        if not isinstance(self.provider_name, str):
            raise TypeError("application provider_name must be a string")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "application attributes"),
        )


# Descriptive aliases retained for callers that prefer metadata-oriented names.
ApplicationMetadata = ApplicationInfo
FileSystemEntry = FileMetadata
ProcessInfo = ProcessMetadata


__all__ = [
    "ApplicationInfo",
    "ApplicationMetadata",
    "ClipboardMetadata",
    "ComputerCapability",
    "ComputerHealth",
    "ComputerProviderInfo",
    "ComputerStatus",
    "FileMetadata",
    "FileSystemEntry",
    "FileSystemEntryKind",
    "ProcessInfo",
    "ProcessMetadata",
]
