"""Provider-backed, read-only process information services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from ..core.exceptions import ProcessServiceError
from ..core.interfaces import EventPublisher
from ..core.models import ProcessMetadata


@runtime_checkable
class ProcessProvider(Protocol):
    """Platform adapter contract for process metadata inspection."""

    def enumerate_processes(self) -> tuple[ProcessMetadata, ...]:
        """Return metadata for currently running processes."""

    def get_process(self, pid: int) -> ProcessMetadata | None:
        """Return metadata for one process, when present."""


_Result = TypeVar("_Result")


class ProcessService:
    """Discover processes without exposing termination or execution actions."""

    DISCOVERED_EVENT = "computer.processes.discovered"

    def __init__(
        self,
        provider: ProcessProvider,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(provider, ProcessProvider):
            raise TypeError("provider must implement ProcessProvider")
        self._provider = provider
        self._provider_name = _provider_name(provider)
        self._logger = logger or NullLogger("narvis.computer.processes")
        self._event_bus = event_bus

    @property
    def provider(self) -> ProcessProvider:
        """Return the injected process information provider."""

        return self._provider

    def enumerate_running_processes(self) -> tuple[ProcessMetadata, ...]:
        """Return a deterministic snapshot of running process metadata."""

        operation = "enumerate_running_processes"
        self._log_request(operation)
        processes = self._enumerate(operation)
        self._publish(operation, count=len(processes))
        return processes

    def enumerate_processes(self) -> tuple[ProcessMetadata, ...]:
        """Alias for :meth:`enumerate_running_processes`."""

        return self.enumerate_running_processes()

    def list_processes(self) -> tuple[ProcessMetadata, ...]:
        """Alias for :meth:`enumerate_running_processes`."""

        return self.enumerate_running_processes()

    def process_metadata(self, pid: int) -> ProcessMetadata | None:
        """Return metadata for one process identifier."""

        operation = "process_metadata"
        self._log_request(operation, pid=pid)
        valid_pid = _validate_pid(pid)
        result = self._request(
            operation,
            lambda: self._provider.get_process(valid_pid),
        )
        if result is not None and not isinstance(result, ProcessMetadata):
            self._raise_invalid_result(operation, "expected ProcessMetadata or None")
        self._publish(operation, count=int(result is not None), pid=valid_pid)
        return result

    def get_metadata(self, pid: int) -> ProcessMetadata | None:
        """Alias for :meth:`process_metadata`."""

        return self.process_metadata(pid)

    def find_by_pid(self, pid: int) -> ProcessMetadata | None:
        """Look up one running process by identifier."""

        return self.process_metadata(pid)

    def lookup_by_pid(self, pid: int) -> ProcessMetadata | None:
        """Alias for :meth:`find_by_pid`."""

        return self.find_by_pid(pid)

    def find_by_name(self, name: str) -> tuple[ProcessMetadata, ...]:
        """Look up all running processes with a case-insensitive exact name."""

        operation = "find_by_name"
        self._log_request(operation, name=name)
        valid_name = _validate_name(name)
        processes = self._enumerate(operation)
        matching = tuple(
            process
            for process in processes
            if process.name.casefold() == valid_name.casefold()
        )
        self._publish(operation, count=len(matching), name=valid_name)
        return matching

    def lookup_by_name(self, name: str) -> tuple[ProcessMetadata, ...]:
        """Alias for :meth:`find_by_name`."""

        return self.find_by_name(name)

    def _enumerate(self, operation: str) -> tuple[ProcessMetadata, ...]:
        result = self._request(operation, self._provider.enumerate_processes)
        if not isinstance(result, tuple):
            self._raise_invalid_result(
                operation,
                "expected tuple[ProcessMetadata, ...]",
            )
        if not all(isinstance(process, ProcessMetadata) for process in result):
            self._raise_invalid_result(
                operation,
                "process entries must be ProcessMetadata",
            )
        return tuple(sorted(result, key=lambda process: process.pid))

    def _request(self, operation: str, request: Callable[[], _Result]) -> _Result:
        try:
            return request()
        except ProcessServiceError:
            raise
        except Exception as error:
            self._log_failure(operation, error)
            raise ProcessServiceError(
                self._provider_name,
                operation,
                str(error),
            ) from error

    def _raise_invalid_result(self, operation: str, reason: str) -> None:
        error = TypeError(reason)
        self._log_failure(operation, error)
        raise ProcessServiceError(
            self._provider_name,
            operation,
            reason,
        ) from error

    def _publish(self, operation: str, **payload: object) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.DISCOVERED_EVENT,
                    payload={
                        "operation": operation,
                        "provider": self._provider_name,
                        **payload,
                    },
                )
            )
        except Exception as error:
            self._safe_log(
                LogLevel.WARNING,
                "Unable to publish process discovery event",
                operation=operation,
                error_type=type(error).__name__,
            )

    def _log_request(self, operation: str, **context: object) -> None:
        self._safe_log(
            LogLevel.INFO,
            "Computer process request",
            operation=operation,
            provider=self._provider_name,
            **context,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        self._safe_log(
            LogLevel.ERROR,
            "Computer process request failed",
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


def _validate_pid(pid: object) -> int:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 0:
        raise ValueError("pid must be a non-negative integer")
    return pid


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("process name must be a non-empty string")
    if name != name.strip():
        raise ValueError("process name must not contain surrounding whitespace")
    return name


def _provider_name(provider: object) -> str:
    info = getattr(provider, "info", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(provider).__name__


__all__ = ["ProcessProvider", "ProcessService"]
