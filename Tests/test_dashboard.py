"""Tests for the Dashboard runtime service."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from Core.logger import LogLevel
from Core.system import HealthReport
from Dashboard.dashboard import DashboardLogBuffer, DashboardLogger, DashboardModule
from Dashboard.status import DashboardRuntimeActions, SystemMetrics


class _FakeLogger:
    """Simple logger stub that records forwarded log calls."""

    def __init__(self) -> None:
        self.messages: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.messages.append((level, message, context))


class _FakeMetricsProvider:
    """Metrics provider stub used to avoid host-specific assertions."""

    def snapshot(self, narvis_version: str) -> SystemMetrics:
        return SystemMetrics(
            cpu_percent=12.5,
            ram_percent=48.0,
            ram_used_mb=1024.0,
            ram_total_mb=2048.0,
            python_version="3.12.0",
            narvis_version=narvis_version,
        )


class DashboardModuleTests(unittest.TestCase):
    """Exercise the non-UI dashboard behavior."""

    def setUp(self) -> None:
        self._base_logger = _FakeLogger()
        self._log_buffer = DashboardLogBuffer(capacity=16)
        self._logger = DashboardLogger(self._base_logger, self._log_buffer)
        self._health_reports = {
            "brain_engine": HealthReport(name="brain_engine", status="ok", details={"module": "AI"}),
            "dashboard": HealthReport(name="dashboard", status="ok", details={"module": "Dashboard"}),
        }
        self._running = True

        def _test_modules() -> Mapping[str, HealthReport]:
            return self._health_reports

        self._actions = DashboardRuntimeActions(
            start_callback=lambda: self._set_running(True),
            stop_callback=lambda: self._set_running(False),
            restart_callback=self._restart_runtime,
            running_callback=lambda: self._running,
            test_callback=_test_modules,
        )
        self._dashboard = DashboardModule(
            narvis_version="2.0",
            logger=self._logger,
            runtime_actions=self._actions,
            health_provider=lambda: self._health_reports,
            log_buffer=self._log_buffer,
            metrics_provider=_FakeMetricsProvider(),
        )

    def _set_running(self, value: bool) -> None:
        self._running = value

    def _restart_runtime(self) -> None:
        self._running = False
        self._running = True

    def test_snapshot_uses_running_health_reports(self) -> None:
        snapshot = self._dashboard.get_snapshot()

        self.assertEqual(snapshot.runtime_state, "running")
        self.assertEqual(snapshot.metrics.narvis_version, "2.0")
        self.assertEqual(snapshot.modules[0].status, "ok")

    def test_snapshot_marks_modules_stopped_when_runtime_is_stopped(self) -> None:
        self._set_running(False)

        snapshot = self._dashboard.get_snapshot()

        self.assertEqual(snapshot.runtime_state, "stopped")
        self.assertTrue(all(module.status == "stopped" for module in snapshot.modules))

    def test_test_modules_logs_summary(self) -> None:
        statuses = self._dashboard.test_modules()

        self.assertEqual(len(statuses), 2)
        self.assertTrue(any(message == "Module test completed" for _, message, _ in self._base_logger.messages))


if __name__ == "__main__":
    unittest.main()
