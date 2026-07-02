"""Tests for the Computer application manager."""

from __future__ import annotations

import unittest
from unittest import mock

from Computer.application_manager import ApplicationManager


class ApplicationManagerTests(unittest.TestCase):
    """Verify application launch behavior remains deterministic."""

    def test_open_app_by_name_resolves_windows_aliases(self) -> None:
        manager = ApplicationManager()
        manager.os_type = "Windows"

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("calculator")

        self.assertTrue(result)
        popen.assert_called_once_with("calc.exe")

    def test_open_app_by_name_preserves_non_windows_behavior(self) -> None:
        manager = ApplicationManager()
        manager.os_type = "Darwin"

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("Safari")

        self.assertTrue(result)
        popen.assert_called_once_with(["open", "-a", "Safari"])


if __name__ == "__main__":
    unittest.main()
