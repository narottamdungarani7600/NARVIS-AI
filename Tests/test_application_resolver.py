"""Tests for universal Windows application resolution."""

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
    """Verify application resolution uses fuzzy matching across sources."""

    def setUp(self) -> None:
        self.temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_resolve_finds_path_application_with_fuzzy_name(self) -> None:
        path_root = self.temp_dir / "bin"
        path_root.mkdir(parents=True, exist_ok=True)
        executable = path_root / "Google Chrome.exe"
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(path_directories=[path_root])

        resolved = resolver.resolve("chrome")

        self.assertEqual(resolved, str(executable))
        self.assertIn(str(executable), resolver.find_path())

    def test_resolve_finds_program_files_application_with_fuzzy_name(self) -> None:
        install_root = self.temp_dir / "Program Files"
        executable = install_root / "Adobe" / "Adobe Photoshop 2024" / "Photoshop.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(program_files_roots=[install_root])

        resolved = resolver.resolve("Adobe Photoshop")

        self.assertEqual(resolved, str(executable))
        self.assertIn(str(executable), resolver.find_program_files())

    def test_resolve_uses_cache_for_repeated_lookups(self) -> None:
        path_root = self.temp_dir / "cache-bin"
        path_root.mkdir(parents=True, exist_ok=True)
        executable = path_root / "OBS Studio.exe"
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(path_directories=[path_root], cache={})

        first = resolver.resolve("obs")
        resolver._path_candidates = mock.Mock(side_effect=AssertionError("cache should satisfy second lookup"))
        second = resolver.resolve("obs")

        self.assertEqual(first, str(executable))
        self.assertEqual(second, str(executable))
        resolver._path_candidates.assert_not_called()

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

    def test_resolve_finds_shortcut_target(self) -> None:
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

    def test_launch_opens_resolved_executable(self) -> None:
        path_root = self.temp_dir / "launch-bin"
        path_root.mkdir(parents=True, exist_ok=True)
        executable = path_root / "Discord.exe"
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(path_directories=[path_root])

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
            "shortcut_target_resolver": lambda _path: None,
            "os_type": "Windows",
        }
        defaults.update(overrides)
        return ApplicationResolver(**defaults)


if __name__ == "__main__":
    unittest.main()
