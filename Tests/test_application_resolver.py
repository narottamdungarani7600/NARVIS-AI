"""Tests for safer Windows application resolution."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from Computer.application_resolver import ApplicationResolver


def _workspace_temp_dir() -> Path:
    """Create a temporary directory inside the writable workspace."""

    root = Path.cwd() / "data" / "resolver_test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ApplicationResolverTests(unittest.TestCase):
    """Verify application resolution prioritizes trusted Windows sources."""

    def setUp(self) -> None:
        self.temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_resolve_prefers_app_paths_registry_before_path(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        (system32 / "pacjsworker.exe").write_text("", encoding="utf-8")
        photoshop = self.temp_dir / "Adobe" / "Adobe Photoshop 2024" / "Photoshop.exe"
        photoshop.parent.mkdir(parents=True, exist_ok=True)
        photoshop.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            path_directories=[system32],
            app_paths_reader=lambda: (
                {
                    "Name": "photoshop.exe",
                    "FriendlyAppName": "Adobe Photoshop",
                    "Path": str(photoshop),
                },
            ),
        )

        resolved = resolver.resolve("Photoshop")

        self.assertEqual(resolved, str(photoshop))

    def test_resolve_finds_start_menu_shortcut_target(self) -> None:
        start_menu_root = self.temp_dir / "Start Menu"
        shortcut = start_menu_root / "Programs" / "Microsoft Edge.lnk"
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        shortcut.write_text("", encoding="utf-8")
        executable = self.temp_dir / "Microsoft" / "Edge" / "msedge.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            start_menu_roots=[start_menu_root],
            shortcut_target_resolver=lambda path: executable if path == shortcut else None,
        )

        resolved = resolver.resolve("Microsoft Edge")

        self.assertEqual(resolved, str(executable))
        self.assertIn(str(executable), resolver.find_shortcuts())

    def test_resolve_finds_windows_apps_entry(self) -> None:
        executable = self.temp_dir / "Spotify" / "Spotify.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            windows_apps_reader=lambda: (
                {
                    "Name": "Spotify",
                    "Path": str(executable),
                },
            ),
        )

        resolved = resolver.resolve("Spotify")

        self.assertEqual(resolved, str(executable))
        self.assertIn(str(executable), resolver.find_windows_apps())

    def test_resolve_finds_registry_application(self) -> None:
        executable = self.temp_dir / "VideoLAN" / "VLC" / "vlc.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            registry_reader=lambda: (
                {
                    "DisplayName": "VLC media player",
                    "DisplayIcon": f'"{executable}",0',
                    "InstallLocation": str(executable.parent),
                },
            ),
        )

        resolved = resolver.resolve("vlc")

        self.assertEqual(resolved, str(executable))
        self.assertIn(str(executable), resolver.find_registry())

    def test_resolve_path_candidate_requires_explicit_system_request(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        pacjsworker = system32 / "pacjsworker.exe"
        pacjsworker.write_text("", encoding="utf-8")
        resolver = self._build_resolver(path_directories=[system32])

        self.assertIsNone(resolver.resolve("Photoshop"))
        self.assertEqual(resolver.resolve("pacjsworker"), str(pacjsworker))

    def test_resolve_program_files_prefers_product_folder_over_filename_similarity(self) -> None:
        install_root = self.temp_dir / "Program Files"
        actual = install_root / "Adobe" / "Adobe Photoshop 2024" / "Photoshop.exe"
        actual.parent.mkdir(parents=True, exist_ok=True)
        actual.write_text("", encoding="utf-8")
        misleading = install_root / "Utilities" / "Photoshop Launcher.exe"
        misleading.parent.mkdir(parents=True, exist_ok=True)
        misleading.write_text("", encoding="utf-8")
        resolver = self._build_resolver(program_files_roots=[install_root])

        resolved = resolver.resolve("Adobe Photoshop")

        self.assertEqual(resolved, str(actual))
        self.assertIn(str(actual), resolver.find_program_files())

    def test_resolve_uses_cache_for_repeated_lookups(self) -> None:
        executable = self.temp_dir / "Discord" / "Discord.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            cache={},
            app_paths_reader=lambda: (
                {
                    "Name": "discord.exe",
                    "FriendlyAppName": "Discord",
                    "Path": str(executable),
                },
            ),
        )

        first = resolver.resolve("discord")
        resolver._app_paths_candidates = mock.Mock(side_effect=AssertionError("cache should satisfy second lookup"))
        second = resolver.resolve("discord")

        self.assertEqual(first, str(executable))
        self.assertEqual(second, str(executable))
        resolver._app_paths_candidates.assert_not_called()

    def test_launch_opens_resolved_executable(self) -> None:
        executable = self.temp_dir / "Apps" / "Discord.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            app_paths_reader=lambda: (
                {
                    "Name": "discord.exe",
                    "FriendlyAppName": "Discord",
                    "Path": str(executable),
                },
            ),
        )

        with mock.patch("Computer.application_resolver.subprocess.Popen") as popen:
            launched = resolver.launch("discord")

        self.assertTrue(launched)
        popen.assert_called_once_with(str(executable))

    def _build_resolver(self, **overrides: object) -> ApplicationResolver:
        """Build a resolver with deterministic, test-local search roots."""

        defaults = {
            "start_menu_roots": [],
            "desktop_roots": [],
            "path_directories": [],
            "program_files_roots": [],
            "windows_apps_root": self.temp_dir / "WindowsApps",
            "registry_reader": lambda: (),
            "app_paths_reader": lambda: (),
            "windows_apps_reader": lambda: (),
            "shortcut_target_resolver": lambda _path: None,
            "os_type": "Windows",
        }
        defaults.update(overrides)
        return ApplicationResolver(**defaults)


if __name__ == "__main__":
    unittest.main()
