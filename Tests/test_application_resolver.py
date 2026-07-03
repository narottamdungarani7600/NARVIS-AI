"""Tests for the universal Windows application resolver."""

from __future__ import annotations

import subprocess
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
    """Verify source priority, exact-match wins, and guarded fallback behavior."""

    def setUp(self) -> None:
        self.temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_exact_match_wins_over_higher_priority_partial_match(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        cmd_executable = system32 / "cmd.exe"
        cmd_executable.write_text("", encoding="utf-8")
        chrome = self.temp_dir / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True, exist_ok=True)
        chrome.write_text("", encoding="utf-8")
        start_menu_root = self.temp_dir / "Start Menu"
        shortcut = start_menu_root / "Programs" / "Git CMD.lnk"
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        shortcut.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            path_directories=[system32],
            start_menu_roots=[start_menu_root],
            app_paths_reader=lambda: (
                {
                    "Name": "chrome.exe",
                    "Path": str(chrome),
                    "FriendlyAppName": "",
                },
            ),
            shortcut_target_resolver=lambda path: cmd_executable if path == shortcut else None,
        )

        resolved = resolver.resolve("CMD")

        self.assertEqual(resolved, str(cmd_executable))

    def test_resolve_prefers_app_paths_for_photoshop(self) -> None:
        photoshop = self.temp_dir / "Adobe" / "Adobe Photoshop 2025" / "Photoshop.exe"
        photoshop.parent.mkdir(parents=True, exist_ok=True)
        photoshop.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            app_paths_reader=lambda: (
                {
                    "Name": "Photoshop.exe",
                    "Path": str(photoshop),
                    "FriendlyAppName": "Adobe Photoshop",
                },
            ),
        )

        resolved = resolver.resolve("Photoshop")

        self.assertEqual(resolved, str(photoshop))

    def test_resolve_uses_store_app_for_calculator(self) -> None:
        resolver = self._build_resolver(
            windows_apps_reader=lambda: (
                {
                    "Name": "Calculator",
                    "Path": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
                    "AppUserModelID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
                },
            ),
        )

        resolved = resolver.resolve("Calculator")

        self.assertEqual(resolved, "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")

    def test_launch_store_app_uses_explorer(self) -> None:
        resolver = self._build_resolver(
            windows_apps_reader=lambda: (
                {
                    "Name": "Calculator",
                    "Path": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
                    "AppUserModelID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
                },
            ),
        )

        with mock.patch("Computer.application_resolver.subprocess.Popen") as popen:
            launched = resolver.launch("Calculator")

        self.assertTrue(launched)
        popen.assert_called_once_with(["explorer.exe", "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"])

    def test_resolve_coreldraw_does_not_fall_back_to_chrome(self) -> None:
        chrome = self.temp_dir / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True, exist_ok=True)
        chrome.write_text("", encoding="utf-8")
        corel = self.temp_dir / "Corel" / "CorelDRAW Graphics Suite" / "27" / "Programs64" / "CorelDrw.exe"
        corel.parent.mkdir(parents=True, exist_ok=True)
        corel.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            app_paths_reader=lambda: (
                {
                    "Name": "chrome.exe",
                    "Path": str(chrome),
                    "FriendlyAppName": "",
                },
                {
                    "Name": "CorelDrw.exe",
                    "Path": str(corel),
                    "FriendlyAppName": "",
                },
            ),
            windows_apps_reader=lambda: (
                {
                    "Name": "CorelDRAW 2026",
                    "Path": "{6D809377-6AF0-444B-8957-A3773F02200E}\\Corel\\CorelDRAW Graphics Suite\\27\\Programs64\\CorelDrw.exe",
                    "AppUserModelID": "{6D809377-6AF0-444B-8957-A3773F02200E}\\Corel\\CorelDRAW Graphics Suite\\27\\Programs64\\CorelDrw.exe",
                },
            ),
        )

        resolved = resolver.resolve("CorelDRAW")

        self.assertNotEqual(resolved, str(chrome))
        self.assertIn("Corel", resolved or "")

    def test_resolve_coreldraw_prefers_launchable_shortcut_over_non_packaged_appsfolder_entry(self) -> None:
        start_menu_root = self.temp_dir / "Start Menu"
        shortcut = start_menu_root / "Programs" / "CorelDRAW 2026.lnk"
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        shortcut.write_text("", encoding="utf-8")
        advertised_launcher = self.temp_dir / "Windows" / "Installer" / "{corel}" / "AdvertisedCorelDraw.exe"
        advertised_launcher.parent.mkdir(parents=True, exist_ok=True)
        advertised_launcher.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            start_menu_roots=[start_menu_root],
            windows_apps_reader=lambda: (
                {
                    "Name": "CorelDRAW 2026",
                    "Path": "{6D809377-6AF0-444B-8957-A3773F02200E}\\Corel\\CorelDRAW Graphics Suite\\27\\Programs64\\CorelDrw.exe",
                    "AppUserModelID": "{6D809377-6AF0-444B-8957-A3773F02200E}\\Corel\\CorelDRAW Graphics Suite\\27\\Programs64\\CorelDrw.exe",
                },
            ),
            shortcut_target_resolver=lambda path: advertised_launcher if path == shortcut else None,
        )

        resolved = resolver.resolve("CorelDRAW")

        self.assertEqual(resolved, str(advertised_launcher))

    def test_launch_shortcut_candidate_uses_shell_startfile(self) -> None:
        start_menu_root = self.temp_dir / "Start Menu"
        shortcut = start_menu_root / "Programs" / "CorelDRAW 2026.lnk"
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        shortcut.write_text("", encoding="utf-8")
        advertised_launcher = self.temp_dir / "Windows" / "Installer" / "{corel}" / "AdvertisedCorelDraw.exe"
        advertised_launcher.parent.mkdir(parents=True, exist_ok=True)
        advertised_launcher.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            start_menu_roots=[start_menu_root],
            shortcut_target_resolver=lambda path: advertised_launcher if path == shortcut else None,
        )

        with mock.patch("Computer.application_resolver.os.startfile", create=True) as startfile:
            launched = resolver.launch("CorelDRAW")

        self.assertTrue(launched)
        startfile.assert_called_once_with(str(shortcut))

    def test_launch_cmd_uses_separate_console_window(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        cmd_executable = system32 / "cmd.exe"
        cmd_executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver(path_directories=[system32])
        expected_flags = (
            getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

        with mock.patch.object(resolver, "_read_pe_subsystem", return_value=3), mock.patch(
            "Computer.application_resolver.subprocess.Popen"
        ) as popen:
            launched = resolver.launch("CMD")

        self.assertTrue(launched)
        popen.assert_called_once_with([str(cmd_executable)], creationflags=expected_flags)

    def test_metadata_stage_can_resolve_calculator_from_calc_exe(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        calc = system32 / "calc.exe"
        calc.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            path_directories=[system32],
            metadata_reader=lambda path: {
                "ProductName": "Windows Calculator",
                "FileDescription": "Calculator",
            }
            if path == calc
            else None,
        )

        resolved = resolver.resolve("Calculator")

        self.assertEqual(resolved, str(calc))

    def test_final_fuzzy_fallback_can_resolve_coreldrw(self) -> None:
        corel = self.temp_dir / "Corel" / "CorelDRAW Graphics Suite" / "27" / "Programs64" / "CorelDrw.exe"
        corel.parent.mkdir(parents=True, exist_ok=True)
        corel.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            app_paths_reader=lambda: (
                {
                    "Name": "CorelDrw.exe",
                    "Path": str(corel),
                    "FriendlyAppName": "",
                },
            ),
        )

        resolved = resolver.resolve("Corel Drw")

        self.assertEqual(resolved, str(corel))

    def test_cache_satisfies_repeated_lookup(self) -> None:
        photoshop = self.temp_dir / "Adobe" / "Adobe Photoshop 2025" / "Photoshop.exe"
        photoshop.parent.mkdir(parents=True, exist_ok=True)
        photoshop.write_text("", encoding="utf-8")
        resolver = self._build_resolver(
            cache={},
            app_paths_reader=lambda: (
                {
                    "Name": "Photoshop.exe",
                    "Path": str(photoshop),
                    "FriendlyAppName": "Adobe Photoshop",
                },
            ),
        )

        first = resolver.resolve("Photoshop")
        resolver._resolve_candidate = mock.Mock(side_effect=AssertionError("cache should satisfy second lookup"))
        second = resolver.resolve("Photoshop")

        self.assertEqual(first, str(photoshop))
        self.assertEqual(second, str(photoshop))
        resolver._resolve_candidate.assert_not_called()

    def test_launch_path_uses_same_console_isolation_strategy(self) -> None:
        executable = self.temp_dir / "Tools" / "terminal.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        resolver = self._build_resolver()
        expected_flags = (
            getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

        with mock.patch.object(resolver, "_read_pe_subsystem", return_value=3), mock.patch(
            "Computer.application_resolver.subprocess.Popen"
        ) as popen:
            launched = resolver.launch_path(str(executable), ["-NoExit"])

        self.assertTrue(launched)
        popen.assert_called_once_with([str(executable), "-NoExit"], creationflags=expected_flags)

    def test_shortcut_target_resolution_quotes_paths_with_spaces(self) -> None:
        shortcut = Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\CorelDRAW 2026.lnk")
        expected_target = r"C:\Windows\Installer\{corel}\AdvertisedCorelDraw.exe"
        resolver = self._build_resolver()

        with mock.patch("Computer.application_resolver.subprocess.run") as run:
            run.return_value = mock.Mock(stdout=expected_target + "\n")
            target = resolver._resolve_shortcut_target(shortcut)

        self.assertEqual(target, Path(expected_target))
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["powershell", "-NoProfile", "-Command"])
        self.assertEqual(len(command), 4)
        self.assertIn("CorelDRAW 2026.lnk", command[3])

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
            "windows_aliases_reader": lambda: (),
            "windows_apps_reader": lambda: (),
            "shortcut_target_resolver": lambda _path: None,
            "metadata_reader": lambda _path: None,
            "os_type": "Windows",
        }
        defaults.update(overrides)
        return ApplicationResolver(**defaults)


if __name__ == "__main__":
    unittest.main()
