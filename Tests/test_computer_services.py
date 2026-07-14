"""Tests for Phase 10 Computer Integration Layer Sprint 2 services."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Computer.core import (
    ApplicationInfo,
    ApplicationServiceError,
    ClipboardMetadata,
    ClipboardServiceError,
    ComputerCapability,
    ComputerHealth,
    ComputerProvider,
    ComputerProviderInfo,
    ComputerRegistry,
    ComputerStatus,
    FileMetadata,
    FileSystemEntryKind,
    FileSystemServiceError,
    ProcessMetadata,
    ProcessServiceError,
)
from Computer.services import (
    ApplicationService,
    ClipboardService,
    FileSystemService,
    ProcessService,
)


class _CapturingLogger:
    """Core-compatible logger that records structured service requests."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _FailingLogger:
    """Logger double used to verify logging cannot break information reads."""

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        raise RuntimeError("logging unavailable")


class _FileSystemProvider:
    """In-memory metadata provider with no content or mutation methods."""

    def __init__(self) -> None:
        self.info = ComputerProviderInfo("filesystem.test")
        self.directory = FileMetadata(
            "/workspace/docs",
            "docs",
            FileSystemEntryKind.DIRECTORY,
        )
        self.file = FileMetadata(
            "/workspace/readme.txt",
            "readme.txt",
            FileSystemEntryKind.FILE,
            size_bytes=24,
        )
        self.directories: object = (self.directory,)
        self.files: object = (self.file,)
        self.metadata_result: object = self.file
        self.exists_result: object = True
        self.validation_result: object = True
        self.fail_operation: str | None = None
        self.requests: list[tuple[str, str]] = []

    def _record(self, operation: str, path: str) -> None:
        self.requests.append((operation, path))
        if self.fail_operation == operation:
            raise OSError("provider unavailable")

    def list_directories(self, path: str) -> tuple[FileMetadata, ...]:
        self._record("list_directories", path)
        return self.directories  # type: ignore[return-value]

    def list_files(self, path: str) -> tuple[FileMetadata, ...]:
        self._record("list_files", path)
        return self.files  # type: ignore[return-value]

    def get_metadata(self, path: str) -> FileMetadata | None:
        self._record("get_metadata", path)
        return self.metadata_result  # type: ignore[return-value]

    def exists(self, path: str) -> bool:
        self._record("exists", path)
        return self.exists_result  # type: ignore[return-value]

    def validate_path(self, path: str) -> bool:
        self._record("validate_path", path)
        return self.validation_result  # type: ignore[return-value]


class _ProcessProvider:
    """In-memory process metadata provider with no termination operation."""

    def __init__(self) -> None:
        self.info = ComputerProviderInfo("process.test")
        self.processes: object = (
            ProcessMetadata(31, "worker", status="sleeping"),
            ProcessMetadata(12, "Editor", status="running"),
            ProcessMetadata(25, "editor", status="running"),
        )
        self.process_result: object = ProcessMetadata(12, "Editor")
        self.fail_operation: str | None = None
        self.enumeration_calls = 0
        self.pid_requests: list[int] = []

    def enumerate_processes(self) -> tuple[ProcessMetadata, ...]:
        self.enumeration_calls += 1
        if self.fail_operation == "enumerate_processes":
            raise RuntimeError("process provider unavailable")
        return self.processes  # type: ignore[return-value]

    def get_process(self, pid: int) -> ProcessMetadata | None:
        self.pid_requests.append(pid)
        if self.fail_operation == "get_process":
            raise RuntimeError("process metadata unavailable")
        return self.process_result  # type: ignore[return-value]


class _ClipboardProvider:
    """In-memory read-only clipboard provider."""

    def __init__(self) -> None:
        self.info = ComputerProviderInfo("clipboard.test")
        self.available_result: object = True
        self.text_result: object = "private clipboard text"
        self.metadata_result: object = ClipboardMetadata(
            available=True,
            contains_text=True,
            text_length=22,
        )
        self.fail_operation: str | None = None
        self.requests: list[str] = []

    def _request(self, operation: str) -> None:
        self.requests.append(operation)
        if self.fail_operation == operation:
            raise RuntimeError("clipboard provider unavailable")

    def is_available(self) -> bool:
        self._request("is_available")
        return self.available_result  # type: ignore[return-value]

    def read_text(self) -> str | None:
        self._request("read_text")
        return self.text_result  # type: ignore[return-value]

    def get_metadata(self) -> ClipboardMetadata:
        self._request("get_metadata")
        return self.metadata_result  # type: ignore[return-value]


class _ApplicationProvider(ComputerProvider):
    """Registered provider supporting both read-only discovery modes."""

    def __init__(
        self,
        name: str,
        *,
        installed: object | None = None,
        running: object | None = None,
        fail_operation: str | None = None,
    ) -> None:
        super().__init__(ComputerProviderInfo(name, version="1.2.0"))
        self.installed = (
            installed
            if installed is not None
            else (
                ApplicationInfo(
                    f"{name}.editor",
                    "Editor",
                    version="2.0",
                    provider_name=name,
                ),
            )
        )
        self.running = (
            running
            if running is not None
            else (
                ApplicationInfo(
                    f"{name}.terminal",
                    "Terminal",
                    is_running=True,
                    process_id=42,
                    provider_name=name,
                ),
            )
        )
        self.fail_operation = fail_operation
        self.installed_calls = 0
        self.running_calls = 0

    def initialize(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def health(self) -> ComputerHealth:
        return ComputerHealth(ComputerStatus.HEALTHY)

    def capabilities(self) -> tuple[ComputerCapability, ...]:
        return ()

    def discover_installed_applications(self) -> tuple[ApplicationInfo, ...]:
        self.installed_calls += 1
        if self.fail_operation == "discover_installed_applications":
            raise RuntimeError("installed discovery unavailable")
        return self.installed  # type: ignore[return-value]

    def discover_running_applications(self) -> tuple[ApplicationInfo, ...]:
        self.running_calls += 1
        if self.fail_operation == "discover_running_applications":
            raise RuntimeError("running discovery unavailable")
        return self.running  # type: ignore[return-value]


class _FoundationOnlyProvider(ComputerProvider):
    """Provider without either optional application discovery protocol."""

    def __init__(self, name: str) -> None:
        super().__init__(ComputerProviderInfo(name))

    def initialize(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def health(self) -> ComputerHealth:
        return ComputerHealth()

    def capabilities(self) -> tuple[ComputerCapability, ...]:
        return ()


class InformationModelTests(unittest.TestCase):
    """Verify Sprint 2 models are strongly typed and immutable."""

    def test_models_are_typed_detached_and_read_only(self) -> None:
        attributes = {"hidden": False}
        timestamp = datetime(2026, 7, 14, tzinfo=timezone.utc)
        file = FileMetadata(
            "/workspace/file.txt",
            "file.txt",
            FileSystemEntryKind.FILE,
            size_bytes=10,
            modified_at=timestamp,
            attributes=attributes,
        )
        process = ProcessMetadata(0, "kernel", memory_bytes=0, cpu_percent=0.0)
        clipboard = ClipboardMetadata(True, True, 4, updated_at=timestamp)
        application = ApplicationInfo("app.id", "App", process_id=0)
        attributes["hidden"] = True

        self.assertTrue(file.is_file)
        self.assertFalse(file.is_directory)
        self.assertFalse(file.attributes["hidden"])
        self.assertEqual(process.pid, 0)
        self.assertEqual(clipboard.text_length, 4)
        self.assertEqual(application.application_id, "app.id")
        with self.assertRaises(TypeError):
            file.attributes["new"] = True  # type: ignore[index]

    def test_models_reject_invalid_provider_metadata(self) -> None:
        with self.assertRaises(TypeError):
            FileMetadata("/file", "file", "file")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ProcessMetadata(-1, "invalid")
        with self.assertRaises(ValueError):
            ClipboardMetadata(False, contains_text=True, text_length=1)
        with self.assertRaises(ValueError):
            ApplicationInfo("app", "App", process_id=-1)


class FileSystemServiceTests(unittest.TestCase):
    """Verify filesystem inspection, empty results, failures, and events."""

    def setUp(self) -> None:
        self.provider = _FileSystemProvider()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(FileSystemService.SCANNED_EVENT, self.events.append)
        self.service = FileSystemService(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_all_filesystem_requests_are_provider_backed_logged_and_published(
        self,
    ) -> None:
        directories = self.service.list_directories("/workspace")
        files = self.service.list_files("/workspace")
        metadata = self.service.file_metadata("/workspace/readme.txt")
        exists = self.service.file_exists("/workspace/readme.txt")
        valid = self.service.validate_path("/workspace/readme.txt")

        self.assertEqual(directories, (self.provider.directory,))
        self.assertEqual(files, (self.provider.file,))
        self.assertIs(metadata, self.provider.file)
        self.assertTrue(exists)
        self.assertTrue(valid)
        self.assertEqual(len(self.provider.requests), 5)
        self.assertEqual(len(self.events), 5)
        self.assertEqual(self.events[0].payload["count"], 1)
        self.assertEqual(self.events[1].payload["operation"], "list_files")
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Computer filesystem request"
        ]
        self.assertEqual(len(request_logs), 5)

    def test_empty_and_missing_filesystem_results_are_preserved(self) -> None:
        self.provider.directories = ()
        self.provider.files = ()
        self.provider.metadata_result = None
        self.provider.exists_result = False
        self.provider.validation_result = False

        self.assertEqual(self.service.list_directories("/empty"), ())
        self.assertEqual(self.service.list_files("/empty"), ())
        self.assertIsNone(self.service.get_metadata("/missing"))
        self.assertFalse(self.service.exists("/missing"))
        self.assertFalse(self.service.is_valid_path("/invalid"))

    def test_provider_failures_and_invalid_results_are_typed(self) -> None:
        self.provider.fail_operation = "list_files"
        with self.assertRaises(FileSystemServiceError) as raised:
            self.service.list_files("/workspace")
        self.assertEqual(raised.exception.provider_name, "filesystem.test")
        self.assertIsInstance(raised.exception.__cause__, OSError)

        self.provider.fail_operation = None
        self.provider.directories = [self.provider.directory]
        with self.assertRaises(FileSystemServiceError):
            self.service.list_directories("/workspace")

    def test_service_exposes_no_content_or_mutation_operations(self) -> None:
        for operation in ("read_file", "write_file", "delete", "rename"):
            self.assertFalse(hasattr(self.service, operation))


class ProcessServiceTests(unittest.TestCase):
    """Verify process discovery and lookup without process control."""

    def setUp(self) -> None:
        self.provider = _ProcessProvider()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(ProcessService.DISCOVERED_EVENT, self.events.append)
        self.service = ProcessService(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_enumeration_metadata_and_name_pid_lookup_publish_events(self) -> None:
        processes = self.service.enumerate_running_processes()
        metadata = self.service.process_metadata(12)
        by_name = self.service.find_by_name("EDITOR")
        by_pid = self.service.find_by_pid(12)

        self.assertEqual([process.pid for process in processes], [12, 25, 31])
        self.assertEqual([process.pid for process in by_name], [12, 25])
        self.assertEqual(metadata, ProcessMetadata(12, "Editor"))
        self.assertEqual(by_pid, metadata)
        self.assertEqual(self.provider.pid_requests, [12, 12])
        self.assertEqual(len(self.events), 4)
        self.assertEqual(self.events[2].payload["count"], 2)
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Computer process request"
        ]
        self.assertEqual(len(request_logs), 4)

    def test_empty_results_and_missing_pid_are_supported(self) -> None:
        self.provider.processes = ()
        self.provider.process_result = None

        self.assertEqual(self.service.list_processes(), ())
        self.assertEqual(self.service.lookup_by_name("missing"), ())
        self.assertIsNone(self.service.lookup_by_pid(99))

    def test_provider_failure_and_invalid_results_are_typed(self) -> None:
        self.provider.fail_operation = "enumerate_processes"
        with self.assertRaises(ProcessServiceError) as raised:
            self.service.enumerate_processes()
        self.assertEqual(raised.exception.provider_name, "process.test")

        self.provider.fail_operation = None
        self.provider.process_result = "invalid"
        with self.assertRaises(ProcessServiceError):
            self.service.get_metadata(12)

    def test_service_exposes_no_process_control(self) -> None:
        self.assertFalse(hasattr(self.service, "terminate"))
        self.assertFalse(hasattr(self.service, "kill"))
        self.assertFalse(hasattr(self.service, "execute"))


class ClipboardServiceTests(unittest.TestCase):
    """Verify text-only clipboard reads, metadata, failures, and privacy."""

    def setUp(self) -> None:
        self.provider = _ClipboardProvider()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(ClipboardService.READ_EVENT, self.events.append)
        self.service = ClipboardService(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_availability_text_read_and_metadata_are_logged(self) -> None:
        self.assertTrue(self.service.is_available())
        self.assertEqual(self.service.read_text(), "private clipboard text")
        self.assertEqual(self.service.metadata().text_length, 22)

        self.assertEqual(
            self.provider.requests,
            ["is_available", "read_text", "get_metadata"],
        )
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].payload["text_length"], 22)
        self.assertNotIn("text", self.events[0].payload)
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Computer clipboard request"
        ]
        self.assertEqual(len(request_logs), 3)

    def test_empty_text_clipboard_returns_none_and_publishes_metadata_only(
        self,
    ) -> None:
        self.provider.available_result = False
        self.provider.text_result = None
        self.provider.metadata_result = ClipboardMetadata(False)

        self.assertFalse(self.service.available())
        self.assertIsNone(self.service.read())
        self.assertFalse(self.service.get_metadata().available)
        self.assertFalse(self.events[0].payload["contains_text"])
        self.assertEqual(self.events[0].payload["text_length"], 0)

    def test_provider_failure_and_invalid_non_text_result_are_typed(self) -> None:
        self.provider.fail_operation = "read_text"
        with self.assertRaises(ClipboardServiceError) as raised:
            self.service.read_text()
        self.assertEqual(raised.exception.provider_name, "clipboard.test")

        self.provider.fail_operation = None
        self.provider.text_result = b"binary clipboard data"
        with self.assertRaises(ClipboardServiceError):
            self.service.read_text()

    def test_service_exposes_no_clipboard_write_operation(self) -> None:
        for operation in ("write", "write_text", "copy", "clear"):
            self.assertFalse(hasattr(self.service, operation))


class ApplicationServiceTests(unittest.TestCase):
    """Verify registry-backed installed and running application discovery."""

    def setUp(self) -> None:
        self.registry = ComputerRegistry()
        self.second = _ApplicationProvider("applications.second")
        self.first = _ApplicationProvider("applications.first")
        self.unsupported = _FoundationOnlyProvider("foundation.only")
        self.registry.register(self.second)
        self.registry.register(self.unsupported)
        self.registry.register(self.first)
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(ApplicationService.DISCOVERED_EVENT, self.events.append)
        self.service = ApplicationService(
            self.registry,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_registered_installed_and_running_discovery_are_deterministic(self) -> None:
        providers = self.service.enumerate_registered_providers()
        installed = self.service.discover_installed_applications()
        running = self.service.discover_running_applications()

        self.assertEqual(
            [provider.name for provider in providers],
            ["applications.first", "applications.second", "foundation.only"],
        )
        self.assertEqual(
            [application.provider_name for application in installed],
            ["applications.first", "applications.second"],
        )
        self.assertTrue(all(application.is_running for application in running))
        self.assertEqual(self.unsupported.capabilities(), ())
        self.assertEqual(len(self.events), 3)
        self.assertEqual(self.events[1].payload["provider_count"], 2)
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Computer application request"
        ]
        self.assertEqual(len(request_logs), 3)

    def test_empty_registry_and_empty_provider_results_publish_empty_discovery(
        self,
    ) -> None:
        events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(ApplicationService.DISCOVERED_EVENT, events.append)
        empty_service = ApplicationService(
            ComputerRegistry(),
            event_bus=event_bus,
        )

        self.assertEqual(empty_service.registered_providers(), ())
        self.assertEqual(empty_service.discover_installed(), ())
        self.assertEqual(empty_service.discover_running(), ())
        self.assertEqual([event.payload["count"] for event in events], [0, 0, 0])

    def test_provider_failures_and_invalid_results_are_typed(self) -> None:
        registry = ComputerRegistry()
        failing = _ApplicationProvider(
            "applications.failure",
            fail_operation="discover_installed_applications",
        )
        registry.register(failing)
        service = ApplicationService(registry)

        with self.assertRaises(ApplicationServiceError) as raised:
            service.discover_installed_applications()
        self.assertEqual(raised.exception.provider_name, "applications.failure")

        failing.fail_operation = None
        failing.running = [ApplicationInfo("invalid", "Invalid")]
        with self.assertRaises(ApplicationServiceError):
            service.discover_running_applications()

    def test_event_and_logging_failures_do_not_change_successful_discovery(
        self,
    ) -> None:
        event_bus = EventBus()
        event_bus.subscribe(
            ApplicationService.DISCOVERED_EVENT,
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        service = ApplicationService(
            self.registry,
            logger=_FailingLogger(),
            event_bus=event_bus,
        )

        self.assertEqual(len(service.discover_installed()), 2)

    def test_service_exposes_no_application_launch_operation(self) -> None:
        for operation in ("launch", "open", "execute", "terminate"):
            self.assertFalse(hasattr(self.service, operation))


if __name__ == "__main__":
    unittest.main()
