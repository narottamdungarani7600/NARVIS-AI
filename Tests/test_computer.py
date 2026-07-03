"""Tests for the Computer application manager."""

from __future__ import annotations

import unittest
from unittest import mock

from Computer.application_manager import ApplicationManager
from Computer.universal_open import UniversalOpenResolution, UniversalOpenTarget


class _FakeResolver:
    """Resolver stub used to isolate ApplicationManager behavior."""

    def __init__(self, launch_result: bool, launch_path_result: bool | None = None) -> None:
        self.launch_result = launch_result
        self.launch_path_result = launch_result if launch_path_result is None else launch_path_result
        self.requests: list[str] = []
        self.path_requests: list[tuple[str, list[str]]] = []

    def launch(self, app_name: str) -> bool:
        self.requests.append(app_name)
        return self.launch_result

    def launch_path(self, app_path: str, args: list[str] | None = None) -> bool:
        self.path_requests.append((app_path, list(args or [])))
        return self.launch_path_result


class _FakeUniversalOpenResolver:
    """Universal resolver stub used to isolate ApplicationManager behavior."""

    def __init__(self, resolution: UniversalOpenResolution) -> None:
        self.resolution = resolution
        self.requests: list[str] = []

    def resolve(self, app_name: str) -> UniversalOpenResolution:
        self.requests.append(app_name)
        return self.resolution


class _FakeUniversalOpenLauncher:
    """Universal launcher stub used to isolate ApplicationManager behavior."""

    def __init__(self, launch_result: bool) -> None:
        self.launch_result = launch_result
        self.requests: list[UniversalOpenTarget] = []

    def launch(self, target: UniversalOpenTarget) -> bool:
        self.requests.append(target)
        return self.launch_result


class ApplicationManagerTests(unittest.TestCase):
    """Verify application launch behavior remains deterministic."""

    def _success_target(self) -> UniversalOpenTarget:
        return UniversalOpenTarget(
            kind="application",
            display_name="Calculator",
            provider="installed_applications",
            source="store_apps",
            launch_kind="appsfolder",
            launch_target="shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
            confidence=1.0,
            descriptor="shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        )

    def test_open_application_uses_resolver_launch_path_on_windows(self) -> None:
        resolver = _FakeResolver(True)
        manager = ApplicationManager(resolver=resolver, os_type="Windows")

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_application("C:\\Tools\\example.exe", ["--flag"])

        self.assertTrue(result)
        self.assertEqual(resolver.path_requests, [("C:\\Tools\\example.exe", ["--flag"])])
        popen.assert_not_called()

    def test_open_app_by_name_uses_resolver_launch_on_windows(self) -> None:
        resolver = _FakeResolver(True)
        universal_resolver = _FakeUniversalOpenResolver(
            UniversalOpenResolution.success("calculator", self._success_target())
        )
        universal_launcher = _FakeUniversalOpenLauncher(True)
        manager = ApplicationManager(
            resolver=resolver,
            universal_open_resolver=universal_resolver,
            universal_open_launcher=universal_launcher,
            os_type="Windows",
        )

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("calculator")

        self.assertTrue(result)
        self.assertEqual(universal_resolver.requests, ["calculator"])
        self.assertEqual(universal_launcher.requests, [self._success_target()])
        self.assertEqual(resolver.requests, [])
        popen.assert_not_called()

    def test_open_app_by_name_returns_false_when_resolver_fails(self) -> None:
        resolver = _FakeResolver(False)
        universal_resolver = _FakeUniversalOpenResolver(
            UniversalOpenResolution.not_found("unknown application", "not found")
        )
        universal_launcher = _FakeUniversalOpenLauncher(True)
        manager = ApplicationManager(
            resolver=resolver,
            universal_open_resolver=universal_resolver,
            universal_open_launcher=universal_launcher,
            os_type="Windows",
        )

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("unknown application")

        self.assertFalse(result)
        self.assertEqual(universal_resolver.requests, ["unknown application"])
        self.assertEqual(universal_launcher.requests, [])
        self.assertEqual(resolver.requests, [])
        popen.assert_not_called()

    def test_open_app_by_name_preserves_non_windows_behavior(self) -> None:
        manager = ApplicationManager(os_type="Darwin")

        with mock.patch("Computer.application_manager.subprocess.Popen") as popen:
            result = manager.open_app_by_name("Safari")

        self.assertTrue(result)
        popen.assert_called_once_with(["open", "-a", "Safari"])


if __name__ == "__main__":
    unittest.main()
