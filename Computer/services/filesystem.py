"""Provider-backed, read-only filesystem information services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.exceptions import FileSystemServiceError
from ..core.interfaces import EventPublisher
from ..core.models import FileMetadata, FileSystemEntryKind


@runtime_checkable
class FileSystemProvider(Protocol):
    """Platform adapter contract for metadata-only filesystem inspection."""

    def list_directories(self, path: str) -> tuple[FileMetadata, ...]:
        """Return directory metadata directly below ``path``."""

    def list_files(self, path: str) -> tuple[FileMetadata, ...]:
        """Return file metadata directly below ``path``."""

    def get_metadata(self, path: str) -> FileMetadata | None:
        """Return metadata for ``path`` without reading its contents."""

    def exists(self, path: str) -> bool:
        """Return whether ``path`` exists."""

    def validate_path(self, path: str) -> bool:
        """Return whether ``path`` is valid for the provider platform."""


_Result = TypeVar("_Result")


class FileSystemService:
    """Expose safe filesystem metadata through an injected provider only."""

    SCANNED_EVENT = "computer.filesystem.scanned"

    def __init__(
        self,
        provider: FileSystemProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, FileSystemProvider):
            raise TypeError("provider must implement FileSystemProvider")
        self._provider = provider
        self._provider_name = _provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.filesystem")
        self._event_bus = event_bus

    @property
    def provider(self) -> FileSystemProvider:
        """Return the injected platform provider."""

        return self._provider

    def list_directories(self, path: str) -> tuple[FileMetadata, ...]:
        """List directory metadata without traversing or reading files."""

        operation = "list_directories"
        self._log_request(operation, path=path)
        valid_path = _validate_path_argument(path)
        result = self._request(
            operation,
            lambda: self._provider.list_directories(valid_path),
        )
        entries = self._validate_entries(
            result,
            operation,
            required_kind=FileSystemEntryKind.DIRECTORY,
        )
        self._publish(operation, valid_path, count=len(entries))
        return entries

    def list_files(self, path: str) -> tuple[FileMetadata, ...]:
        """List file metadata without reading file contents."""

        operation = "list_files"
        self._log_request(operation, path=path)
        valid_path = _validate_path_argument(path)
        result = self._request(
            operation,
            lambda: self._provider.list_files(valid_path),
        )
        entries = self._validate_entries(
            result,
            operation,
            required_kind=FileSystemEntryKind.FILE,
        )
        self._publish(operation, valid_path, count=len(entries))
        return entries

    def get_metadata(self, path: str) -> FileMetadata | None:
        """Return filesystem metadata without opening the target."""

        operation = "get_metadata"
        self._log_request(operation, path=path)
        valid_path = _validate_path_argument(path)
        result = self._request(
            operation,
            lambda: self._provider.get_metadata(valid_path),
        )
        if result is not None and not isinstance(result, FileMetadata):
            self._raise_invalid_result(operation, "expected FileMetadata or None")
        self._publish(operation, valid_path, count=int(result is not None))
        return result

    def file_metadata(self, path: str) -> FileMetadata | None:
        """Alias for :meth:`get_metadata`."""

        return self.get_metadata(path)

    def exists(self, path: str) -> bool:
        """Return whether a filesystem path exists."""

        operation = "exists"
        self._log_request(operation, path=path)
        valid_path = _validate_path_argument(path)
        result = self._request(
            operation,
            lambda: self._provider.exists(valid_path),
        )
        if not isinstance(result, bool):
            self._raise_invalid_result(operation, "expected bool")
        self._publish(operation, valid_path, exists=result)
        return result

    def file_exists(self, path: str) -> bool:
        """Alias for :meth:`exists`."""

        return self.exists(path)

    def path_exists(self, path: str) -> bool:
        """Alias for :meth:`exists`."""

        return self.exists(path)

    def validate_path(self, path: str) -> bool:
        """Delegate platform-specific path validation to the provider."""

        operation = "validate_path"
        self._log_request(operation, path=path)
        valid_path = _validate_path_argument(path)
        result = self._request(
            operation,
            lambda: self._provider.validate_path(valid_path),
        )
        if not isinstance(result, bool):
            self._raise_invalid_result(operation, "expected bool")
        self._publish(operation, valid_path, valid=result)
        return result

    def is_valid_path(self, path: str) -> bool:
        """Alias for :meth:`validate_path`."""

        return self.validate_path(path)

    def _request(self, operation: str, request: Callable[[], _Result]) -> _Result:
        """Invoke one provider operation and translate provider failures."""

        try:
            return request()
        except FileSystemServiceError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise FileSystemServiceError(
                self._provider_name,
                operation,
                str(error),
            ) from error

    def _validate_entries(
        self,
        result: object,
        operation: str,
        *,
        required_kind: FileSystemEntryKind,
    ) -> tuple[FileMetadata, ...]:
        if not isinstance(result, tuple):
            self._raise_invalid_result(
                operation,
                "expected tuple[FileMetadata, ...]",
            )
        if not all(isinstance(entry, FileMetadata) for entry in result):
            self._raise_invalid_result(
                operation,
                "filesystem entries must be FileMetadata",
            )
        if not all(entry.kind is required_kind for entry in result):
            self._raise_invalid_result(
                operation,
                f"filesystem entries must have kind '{required_kind.value}'",
            )
        return result

    def _raise_invalid_result(self, operation: str, reason: str) -> None:
        error = TypeError(reason)
        self._log_failure(operation, error)
        raise FileSystemServiceError(
            self._provider_name,
            operation,
            reason,
        ) from error

    def _publish(self, operation: str, path: str, **payload: object) -> None:
        if self._event_bus is None:
            return
        event_payload = {
            "operation": operation,
            "path": path,
            "provider": self._provider_name,
            **payload,
        }
        try:
            self._event_bus.publish(
                SystemEvent(name=self.SCANNED_EVENT, payload=event_payload)
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish filesystem scan event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str, **context: object) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Computer filesystem request",
            operation=operation,
            provider=self._provider_name,
            **context,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Computer filesystem request failed",
            operation=operation,
            provider=self._provider_name,
            error_type=type(error).__name__,
        )

    def _safe_log(
        self,
        level: LogLevel,
        message: str,
        **context: object,
    ) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


def _validate_path_argument(path: object) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    return path


def _provider_name(provider: object) -> str:
    info = getattr(provider, "info", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(provider).__name__


__all__ = ["FileSystemProvider", "FileSystemService"]
