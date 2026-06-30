"""Typed dashboard models and system-metrics providers for NARVIS.

This module keeps the dashboard's data contracts and host-inspection logic
separate from the Tkinter UI so the non-visual behavior can be tested in
isolation and injected into the runtime cleanly.
"""

from __future__ import annotations

import ctypes
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping, Protocol

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


@dataclass(slots=True, frozen=True)
class LogEntry:
    """Represents a single runtime log entry displayed by the dashboard."""

    timestamp: datetime
    level: str
    source: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ModuleStatus:
    """Represents the current status of a runtime module."""

    name: str
    status: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SystemMetrics:
    """Represents the system metrics displayed in the dashboard."""

    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    python_version: str
    narvis_version: str


@dataclass(slots=True, frozen=True)
class DashboardSnapshot:
    """Represents a complete point-in-time dashboard refresh payload."""

    runtime_state: str
    metrics: SystemMetrics
    modules: tuple[ModuleStatus, ...]
    logs: tuple[LogEntry, ...]
    refreshed_at: datetime


class MetricsProvider(Protocol):
    """Protocol for services that can produce dashboard system metrics."""

    def snapshot(self, narvis_version: str) -> SystemMetrics:
        """Collect the current system metrics for the dashboard."""


@dataclass(slots=True)
class DashboardRuntimeActions:
    """Injected callbacks used by the dashboard to manage the runtime."""

    start_callback: Callable[[], None]
    stop_callback: Callable[[], None]
    restart_callback: Callable[[], None]
    running_callback: Callable[[], bool]
    test_callback: Callable[[], Mapping[str, Any]]

    def start(self) -> None:
        """Start the runtime."""

        self.start_callback()

    def stop(self) -> None:
        """Stop the runtime."""

        self.stop_callback()

    def restart(self) -> None:
        """Restart the runtime."""

        self.restart_callback()

    def is_running(self) -> bool:
        """Return whether the runtime is currently running."""

        return self.running_callback()

    def test_modules(self) -> Mapping[str, Any]:
        """Run the registered module tests or health checks."""

        return self.test_callback()


@dataclass(slots=True, frozen=True)
class _CpuSample:
    """Internal representation of aggregate CPU time counters."""

    total: int
    idle: int


@dataclass(slots=True, frozen=True)
class _MemorySnapshot:
    """Internal representation of host memory usage."""

    used_mb: float
    total_mb: float
    percent: float


class _FileTime(ctypes.Structure):
    """Windows FILETIME structure used by ``GetSystemTimes``."""

    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong),
    ]


class _MemoryStatusEx(ctypes.Structure):
    """Windows MEMORYSTATUSEX structure used by ``GlobalMemoryStatusEx``."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PlatformSystemMetricsProvider:
    """Collect system metrics using optional dependencies or platform fallbacks."""

    def __init__(self) -> None:
        self._cpu_lock = Lock()
        self._last_cpu_sample: _CpuSample | None = None

    def snapshot(self, narvis_version: str) -> SystemMetrics:
        """Collect the latest CPU, memory, and version information."""

        memory = self._read_memory()
        return SystemMetrics(
            cpu_percent=round(self._read_cpu_percent(), 1),
            ram_percent=round(memory.percent, 1),
            ram_used_mb=round(memory.used_mb, 1),
            ram_total_mb=round(memory.total_mb, 1),
            python_version=platform.python_version(),
            narvis_version=narvis_version,
        )

    def _read_cpu_percent(self) -> float:
        """Return the current host CPU usage percentage."""

        if psutil is not None:
            return float(psutil.cpu_percent(interval=None))
        if sys.platform == "win32":
            return self._read_cpu_percent_windows()
        if Path("/proc/stat").exists():
            return self._read_cpu_percent_linux()
        return 0.0

    def _read_memory(self) -> _MemorySnapshot:
        """Return the current host memory usage."""

        if psutil is not None:
            memory = psutil.virtual_memory()
            used_mb = float(memory.used) / (1024 * 1024)
            total_mb = float(memory.total) / (1024 * 1024)
            return _MemorySnapshot(used_mb=used_mb, total_mb=total_mb, percent=float(memory.percent))
        if sys.platform == "win32":
            return self._read_memory_windows()
        if Path("/proc/meminfo").exists():
            return self._read_memory_linux()
        return _MemorySnapshot(used_mb=0.0, total_mb=0.0, percent=0.0)

    def _read_cpu_percent_windows(self) -> float:
        """Collect CPU usage using the Windows ``GetSystemTimes`` API."""

        idle_time = _FileTime()
        kernel_time = _FileTime()
        user_time = _FileTime()
        success = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if success == 0:  # pragma: no cover - defensive platform handling
            return 0.0

        current = _CpuSample(
            total=self._file_time_to_int(kernel_time) + self._file_time_to_int(user_time),
            idle=self._file_time_to_int(idle_time),
        )
        return self._compute_cpu_percent(current)

    def _read_cpu_percent_linux(self) -> float:
        """Collect CPU usage by sampling ``/proc/stat`` on Linux hosts."""

        with Path("/proc/stat").open("r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()

        parts = first_line.split()
        values = [int(value) for value in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return self._compute_cpu_percent(_CpuSample(total=total, idle=idle))

    def _compute_cpu_percent(self, current: _CpuSample) -> float:
        """Compute CPU usage percentage from the current and previous samples."""

        with self._cpu_lock:
            previous = self._last_cpu_sample
            self._last_cpu_sample = current

        if previous is None:
            return 0.0

        total_delta = current.total - previous.total
        idle_delta = current.idle - previous.idle
        if total_delta <= 0:
            return 0.0

        busy = max(total_delta - idle_delta, 0)
        return (busy / total_delta) * 100.0

    def _read_memory_windows(self) -> _MemorySnapshot:
        """Collect memory usage using the Windows ``GlobalMemoryStatusEx`` API."""

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if success == 0:  # pragma: no cover - defensive platform handling
            return _MemorySnapshot(used_mb=0.0, total_mb=0.0, percent=0.0)

        total_mb = float(status.ullTotalPhys) / (1024 * 1024)
        available_mb = float(status.ullAvailPhys) / (1024 * 1024)
        used_mb = max(total_mb - available_mb, 0.0)
        return _MemorySnapshot(used_mb=used_mb, total_mb=total_mb, percent=float(status.dwMemoryLoad))

    def _read_memory_linux(self) -> _MemorySnapshot:
        """Collect memory usage by reading ``/proc/meminfo`` on Linux hosts."""

        values: dict[str, int] = {}
        with Path("/proc/meminfo").open("r", encoding="utf-8") as handle:
            for line in handle:
                key, raw_value = line.split(":", maxsplit=1)
                values[key] = int(raw_value.strip().split()[0])

        total_kb = values.get("MemTotal", 0)
        available_kb = values.get("MemAvailable", 0)
        used_kb = max(total_kb - available_kb, 0)
        total_mb = total_kb / 1024
        used_mb = used_kb / 1024
        percent = (used_kb / total_kb * 100.0) if total_kb else 0.0
        return _MemorySnapshot(used_mb=used_mb, total_mb=total_mb, percent=percent)

    @staticmethod
    def _file_time_to_int(value: _FileTime) -> int:
        """Convert a Windows FILETIME structure into an integer tick count."""

        return (value.dwHighDateTime << 32) | value.dwLowDateTime


__all__ = [
    "DashboardRuntimeActions",
    "DashboardSnapshot",
    "LogEntry",
    "MetricsProvider",
    "ModuleStatus",
    "PlatformSystemMetricsProvider",
    "SystemMetrics",
    "utc_now",
]
