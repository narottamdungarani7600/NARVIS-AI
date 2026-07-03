"""Tests for the provider-based universal open system."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from Computer.application_resolver import ApplicationResolver
from Computer.universal_open import (
    DriveAndShellOpenProvider,
    InstalledApplicationOpenProvider,
    KnownFolderOpenProvider,
    UniversalOpenLauncher,
    UniversalOpenQuery,
    UniversalOpenResolution,
    UniversalOpenResolver,
    UniversalOpenTarget,
    WebsiteOpenProvider,
    WindowsSettingsOpenProvider,
    WindowsSystemToolProvider,
)


def _workspace_temp_dir() -> Path:
    """Create a temporary directory inside the writable workspace."""

    root = Path.cwd() / "data" / "universal_open_test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class _ProviderStub:
    """Provider stub used to exercise resolver control flow."""

    def __init__(self, provider_name: str, resolution: UniversalOpenResolution | None) -> None:
        self.provider_name = provider_name
        self.resolution = resolution
        self.requests: list[str] = []

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        self.requests.append(query.raw)
        return self.resolution


class _LauncherResolverStub:
    """Resolver stub used to validate launcher delegation."""

    def __init__(self, launch_result: bool = True) -> None:
        self.launch_result = launch_result
        self.requests: list[tuple[str, tuple[str, ...]]] = []

    def launch_path(self, app_path: str, args=()) -> bool:
        self.requests.append((app_path, tuple(args or ())))
        return self.launch_result


class UniversalOpenTests(unittest.TestCase):
    """Verify the modular universal open providers and launcher behavior."""

    def setUp(self) -> None:
        self.temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_settings_provider_resolves_wifi_settings(self) -> None:
        provider = WindowsSettingsOpenProvider()

        resolution = provider.resolve(UniversalOpenResolver._build_query("Wi-Fi Settings"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "settings")
        self.assertEqual(resolution.target.launch_target, "ms-settings:network-wifi")

    def test_known_folder_provider_resolves_documents_from_reader(self) -> None:
        documents = self.temp_dir / "Documents"
        documents.mkdir(parents=True, exist_ok=True)
        provider = KnownFolderOpenProvider(folder_reader=lambda: {"documents": documents})

        resolution = provider.resolve(UniversalOpenResolver._build_query("Documents"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "known_folder")
        self.assertEqual(resolution.target.launch_target, str(documents))

    def test_drive_provider_rejects_invalid_drive(self) -> None:
        provider = DriveAndShellOpenProvider(drive_exists=lambda _path: False)

        resolution = provider.resolve(UniversalOpenResolver._build_query("Z Drive"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertFalse(resolution.found)
        self.assertIn("not available", resolution.reason or "")

    def test_drive_provider_resolves_existing_drive(self) -> None:
        provider = DriveAndShellOpenProvider(drive_exists=lambda path: str(path).lower() == "c:\\")

        resolution = provider.resolve(UniversalOpenResolver._build_query("C Drive"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "drive")
        self.assertEqual(resolution.target.launch_target.lower(), "c:\\")

    def test_drive_and_shell_provider_resolves_recycle_bin(self) -> None:
        provider = DriveAndShellOpenProvider()

        resolution = provider.resolve(UniversalOpenResolver._build_query("Recycle Bin"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "shell_location")
        self.assertEqual(resolution.target.launch_target, "shell:RecycleBinFolder")

    def test_website_provider_requires_safe_exact_alias(self) -> None:
        provider = WebsiteOpenProvider()

        self.assertIsNotNone(provider.resolve(UniversalOpenResolver._build_query("YouTube")))  # noqa: SLF001
        self.assertIsNone(provider.resolve(UniversalOpenResolver._build_query("YouTub")))  # noqa: SLF001

    def test_website_provider_resolves_normalized_official_domains(self) -> None:
        provider = WebsiteOpenProvider()
        expectations = {
            "Instagram": "https://www.instagram.com/",
            "Facebook": "https://www.facebook.com/",
            "Linked In": "https://www.linkedin.com/",
            "Twitter": "https://x.com/",
            "Chat GPT": "https://chatgpt.com/",
            "Google Drive": "https://drive.google.com/",
        }

        for query, expected_url in expectations.items():
            with self.subTest(query=query):
                resolution = provider.resolve(UniversalOpenResolver._build_query(query))  # noqa: SLF001
                self.assertIsNotNone(resolution)
                self.assertTrue(resolution.found)
                self.assertEqual(resolution.target.launch_target, expected_url)

    def test_website_provider_does_not_guess_unknown_domains(self) -> None:
        provider = WebsiteOpenProvider()

        resolution = provider.resolve(UniversalOpenResolver._build_query("unknown social app"))  # noqa: SLF001

        self.assertIsNone(resolution)

    def test_system_tool_provider_resolves_task_manager(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        (system32 / "taskmgr.exe").write_text("", encoding="utf-8")
        (system32 / "mmc.exe").write_text("", encoding="utf-8")
        (system32 / "devmgmt.msc").write_text("", encoding="utf-8")
        (system32 / "control.exe").write_text("", encoding="utf-8")
        (system32 / "explorer.exe").write_text("", encoding="utf-8")
        (system32 / "cmd.exe").write_text("", encoding="utf-8")
        (system32 / "SnippingTool.exe").write_text("", encoding="utf-8")
        (system32 / "notepad.exe").write_text("", encoding="utf-8")
        (system32 / "mspaint.exe").write_text("", encoding="utf-8")
        (system32 / "regedit.exe").write_text("", encoding="utf-8")
        (system32 / "resmon.exe").write_text("", encoding="utf-8")
        (system32 / "msinfo32.exe").write_text("", encoding="utf-8")
        powershell = system32 / "WindowsPowerShell" / "v1.0"
        powershell.mkdir(parents=True, exist_ok=True)
        (powershell / "powershell.exe").write_text("", encoding="utf-8")
        provider = WindowsSystemToolProvider(windows_root=self.temp_dir / "Windows")

        resolution = provider.resolve(UniversalOpenResolver._build_query("Task Manager"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "system_tool")
        self.assertTrue(resolution.target.launch_target.endswith("taskmgr.exe"))

    def test_system_tool_provider_resolves_device_manager_to_elevated_shell_file(self) -> None:
        system32 = self.temp_dir / "Windows" / "System32"
        system32.mkdir(parents=True, exist_ok=True)
        (system32 / "devmgmt.msc").write_text("", encoding="utf-8")
        provider = WindowsSystemToolProvider(windows_root=self.temp_dir / "Windows")

        resolution = provider.resolve(UniversalOpenResolver._build_query("Device Manager"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.launch_kind, "shell_file")
        self.assertEqual(resolution.target.launch_verb, "runas")
        self.assertTrue(resolution.target.launch_target.endswith("devmgmt.msc"))

    def test_installed_application_provider_uses_existing_application_resolver(self) -> None:
        chrome = self.temp_dir / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True, exist_ok=True)
        chrome.write_text("", encoding="utf-8")
        resolver = ApplicationResolver(
            app_paths_reader=lambda: (
                {
                    "Name": "chrome.exe",
                    "Path": str(chrome),
                    "FriendlyAppName": "Google Chrome",
                },
            ),
            start_menu_roots=[],
            desktop_roots=[],
            path_directories=[],
            program_files_roots=[],
            windows_apps_reader=lambda: (),
            windows_aliases_reader=lambda: (),
            registry_reader=lambda: (),
            os_type="Windows",
        )
        provider = InstalledApplicationOpenProvider(application_resolver=resolver)

        resolution = provider.resolve(UniversalOpenResolver._build_query("Chrome"))  # noqa: SLF001

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "application")
        self.assertEqual(resolution.target.provider, "installed_applications")
        self.assertEqual(resolution.target.descriptor, str(chrome))

    def test_website_alias_cannot_outrank_strong_local_application_match(self) -> None:
        youtube = self.temp_dir / "Apps" / "YouTube.exe"
        youtube.parent.mkdir(parents=True, exist_ok=True)
        youtube.write_text("", encoding="utf-8")
        application_resolver = ApplicationResolver(
            app_paths_reader=lambda: (
                {
                    "Name": "YouTube.exe",
                    "Path": str(youtube),
                    "FriendlyAppName": "YouTube",
                },
            ),
            start_menu_roots=[],
            desktop_roots=[],
            path_directories=[],
            program_files_roots=[],
            windows_apps_reader=lambda: (),
            windows_aliases_reader=lambda: (),
            registry_reader=lambda: (),
            os_type="Windows",
        )
        resolver = UniversalOpenResolver(application_resolver=application_resolver, os_type="Windows")

        resolution = resolver.resolve("YouTube")

        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "application")
        self.assertEqual(resolution.target.descriptor, str(youtube))

    def test_website_alias_beats_weak_application_similarity(self) -> None:
        tabtip = self.temp_dir / "Program Files" / "Common Files" / "microsoft shared" / "ink" / "TabTip.exe"
        tabtip.parent.mkdir(parents=True, exist_ok=True)
        tabtip.write_text("", encoding="utf-8")
        application_resolver = ApplicationResolver(
            app_paths_reader=lambda: (
                {
                    "Name": "TabTip.exe",
                    "Path": str(tabtip),
                },
            ),
            start_menu_roots=[],
            desktop_roots=[],
            path_directories=[],
            program_files_roots=[],
            windows_apps_reader=lambda: (),
            windows_aliases_reader=lambda: (),
            registry_reader=lambda: (),
            metadata_reader=lambda _path: None,
            os_type="Windows",
        )
        resolver = UniversalOpenResolver(application_resolver=application_resolver, os_type="Windows")

        resolution = resolver.resolve("LinkedIn")

        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "website")
        self.assertEqual(resolution.target.launch_target, "https://www.linkedin.com/")

    def test_direct_application_match_wins_before_alias_expansion(self) -> None:
        corel_shortcut = self.temp_dir / "Start Menu" / "Programs" / "CorelDRAW 2026.lnk"
        corel_shortcut.parent.mkdir(parents=True, exist_ok=True)
        corel_shortcut.write_text("", encoding="utf-8")
        direct_target = self.temp_dir / "Windows" / "Installer" / "{corel}" / "CorelDRAWLauncher.exe"
        direct_target.parent.mkdir(parents=True, exist_ok=True)
        direct_target.write_text("", encoding="utf-8")
        broader_match = self.temp_dir / "Program Files" / "Corel" / "CorelDRAW Graphics Suite" / "27" / "Filters64" / "AsposeConverter.exe"
        broader_match.parent.mkdir(parents=True, exist_ok=True)
        broader_match.write_text("", encoding="utf-8")
        application_resolver = ApplicationResolver(
            start_menu_roots=[self.temp_dir / "Start Menu"],
            program_files_roots=[self.temp_dir / "Program Files"],
            desktop_roots=[],
            path_directories=[],
            windows_apps_reader=lambda: (),
            windows_aliases_reader=lambda: (),
            registry_reader=lambda: (),
            app_paths_reader=lambda: (),
            shortcut_target_resolver=lambda path: direct_target if path == corel_shortcut else None,
            os_type="Windows",
        )
        resolver = UniversalOpenResolver(application_resolver=application_resolver, os_type="Windows")

        resolution = resolver.resolve("CorelDRAW")

        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.descriptor, str(direct_target))
        self.assertNotEqual(resolution.target.descriptor, str(broader_match))

    def test_explicit_website_query_can_prefer_website_alias(self) -> None:
        application_resolver = ApplicationResolver(
            app_paths_reader=lambda: (),
            start_menu_roots=[],
            desktop_roots=[],
            path_directories=[],
            program_files_roots=[],
            windows_apps_reader=lambda: (),
            windows_aliases_reader=lambda: (),
            registry_reader=lambda: (),
            os_type="Windows",
        )
        resolver = UniversalOpenResolver(application_resolver=application_resolver, os_type="Windows")

        resolution = resolver.resolve("YouTube website")

        self.assertTrue(resolution.found)
        self.assertEqual(resolution.target.kind, "website")
        self.assertEqual(resolution.target.launch_target, "https://www.youtube.com/")

    def test_resolver_can_return_ambiguous_results(self) -> None:
        ambiguous_target = UniversalOpenTarget(
            kind="website",
            display_name="GitHub",
            provider="websites",
            source="github",
            launch_kind="url",
            launch_target="https://github.com/",
            confidence=0.5,
        )
        provider = _ProviderStub(
            "ambiguous",
            UniversalOpenResolution.ambiguous_result(
                "git",
                reason="multiple targets matched",
                candidates=(ambiguous_target,),
            ),
        )
        resolver = UniversalOpenResolver(
            application_resolver=self._empty_application_resolver(),
            providers=(provider,),
            os_type="Windows",
        )

        resolution = resolver.resolve("git")

        self.assertFalse(resolution.found)
        self.assertTrue(resolution.ambiguous)
        self.assertEqual(provider.requests, ["git"])

    def test_resolver_returns_not_found_when_no_provider_matches(self) -> None:
        resolver = UniversalOpenResolver(
            application_resolver=self._empty_application_resolver(),
            providers=(),
            os_type="Windows",
        )

        resolution = resolver.resolve("unknown target")

        self.assertFalse(resolution.found)
        self.assertFalse(resolution.ambiguous)
        self.assertIn("No open target matched", resolution.reason or "")

    def test_launcher_opens_folder_with_explorer(self) -> None:
        target_dir = self.temp_dir / "Documents"
        target_dir.mkdir(parents=True, exist_ok=True)
        launcher = UniversalOpenLauncher(application_resolver=_LauncherResolverStub(), os_type="Windows")
        target = UniversalOpenTarget(
            kind="known_folder",
            display_name="Documents",
            provider="known_folders",
            source="documents",
            launch_kind="explorer_path",
            launch_target=str(target_dir),
            confidence=0.99,
        )

        with mock.patch("Computer.universal_open.subprocess.Popen") as popen:
            launched = launcher.launch(target)

        self.assertTrue(launched)
        popen.assert_called_once_with(["explorer.exe", str(target_dir)])

    def test_launcher_uses_shell_handler_for_websites(self) -> None:
        launcher = UniversalOpenLauncher(application_resolver=_LauncherResolverStub(), os_type="Windows")
        target = UniversalOpenTarget(
            kind="website",
            display_name="YouTube",
            provider="websites",
            source="youtube",
            launch_kind="url",
            launch_target="https://www.youtube.com/",
            confidence=0.93,
        )

        with mock.patch("Computer.universal_open.os.startfile", create=True) as startfile:
            launched = launcher.launch(target)

        self.assertTrue(launched)
        startfile.assert_called_once_with("https://www.youtube.com/")

    def test_launcher_uses_shell_handler_with_elevation_for_device_manager(self) -> None:
        launcher = UniversalOpenLauncher(application_resolver=_LauncherResolverStub(), os_type="Windows")
        management_console = self.temp_dir / "Windows" / "System32" / "devmgmt.msc"
        management_console.parent.mkdir(parents=True, exist_ok=True)
        management_console.write_text("", encoding="utf-8")
        target = UniversalOpenTarget(
            kind="system_tool",
            display_name="Device Manager",
            provider="windows_system_tools",
            source="device_manager",
            launch_kind="shell_file",
            launch_target=str(management_console),
            launch_verb="runas",
            confidence=0.99,
        )

        with mock.patch("Computer.universal_open.os.startfile", create=True) as startfile:
            launched = launcher.launch(target)

        self.assertTrue(launched)
        startfile.assert_called_once_with(str(management_console), "runas")

    def test_launcher_delegates_paths_to_application_resolver(self) -> None:
        resolver = _LauncherResolverStub()
        launcher = UniversalOpenLauncher(application_resolver=resolver, os_type="Windows")
        target = UniversalOpenTarget(
            kind="system_tool",
            display_name="Task Manager",
            provider="windows_system_tools",
            source="task_manager",
            launch_kind="path",
            launch_target="C:\\Windows\\System32\\taskmgr.exe",
            launch_args=(),
            confidence=1.0,
        )

        launched = launcher.launch(target)

        self.assertTrue(launched)
        self.assertEqual(resolver.requests, [("C:\\Windows\\System32\\taskmgr.exe", ())])

    def _empty_application_resolver(self) -> ApplicationResolver:
        return ApplicationResolver(
            app_paths_reader=lambda: (),
            start_menu_roots=[],
            desktop_roots=[],
            path_directories=[],
            program_files_roots=[],
            windows_apps_reader=lambda: (),
            windows_aliases_reader=lambda: (),
            registry_reader=lambda: (),
            os_type="Windows",
        )


if __name__ == "__main__":
    unittest.main()
