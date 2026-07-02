"""Tests for the Computer application manager."""

from __future__ import annotations

import unittest
from unittest import mock

from Computer.application_manager import ApplicationManager


class _FakeResolver:
    """Resolver stub used to isolate ApplicationManager behavior."""

    def __init__(self, resolved_path: str | None) -> None:
        self.resolved_path = resolved_path
        self.requests: list[str] = []

    def resolve(self, app_name: str) -> str | None:
        self.requests.append(app_name)
        return self.resolved_path


class ApplicationManagerTests(unittest.TestCase):
    """Verify application launch behavior remains deterministic."""

    def test_open_app_by_name_uses_resolver_on_windows(self) -> None:
        resolver = _FakeResolver(r"C:\Program Files\Calculator\calc.exe")
        manager = ApplicationManager(resolver=resolver, os_type="Windows")

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("calculator")

        self.assertTrue(result)
        self.assertEqual(resolver.requests, ["calculator"])
        popen.assert_called_once_with([r"C:\Program Files\Calculator\calc.exe"])

    def test_open_app_by_name_returns_false_when_resolver_fails(self) -> None:
        resolver = _FakeResolver(None)
        manager = ApplicationManager(resolver=resolver, os_type="Windows")

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("unknown application")

        self.assertFalse(result)
        self.assertEqual(resolver.requests, ["unknown application"])
        popen.assert_not_called()

    def test_open_app_by_name_preserves_non_windows_behavior(self) -> None:
        manager = ApplicationManager(os_type="Darwin")

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("Safari")

        self.assertTrue(result)
        popen.assert_called_once_with(["open", "-a", "Safari"])


if __name__ == "__main__":
    unittest.main()
