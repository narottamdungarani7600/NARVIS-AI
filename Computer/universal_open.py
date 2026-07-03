"""Universal target resolution and launching for NARVIS open commands."""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

try:  # pragma: no cover - registry access is only available on Windows
    import winreg
except Exception:  # pragma: no cover - optional dependency
    winreg = None

from .application_resolver import ApplicationResolver, _emit_log

_EXPLICIT_WEBSITE_TOKENS = frozenset({"browser", "online", "site", "url", "web", "website"})
_KNOWN_FOLDER_GUID_KEYS = {
    "desktop": "Desktop",
    "documents": "Personal",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "music": "My Music",
    "pictures": "My Pictures",
    "screenshots": "{B7BEDE81-DF94-4682-A7D8-57A52620B86F}",
    "videos": "My Video",
}
_SETTINGS_URI_PATTERN = re.compile(r"^ms-settings:[a-z0-9\-]*$", re.IGNORECASE)
_WEBSITE_URL_PATTERN = re.compile(r"^https://[^\s]+$", re.IGNORECASE)
_DRIVE_PATTERN = re.compile(r"^\s*(?P<drive>[a-z])(?:\s*:)?(?:\s+drive)?\s*$", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class UniversalOpenQuery:
    """Normalized representation of one universal open request."""

    raw: str
    normalized: str
    tokens: tuple[str, ...]
    explicit_website: bool

    def normalized_without(self, ignored: set[str] | frozenset[str]) -> str:
        """Return the normalized query with the supplied tokens removed."""

        return "".join(token for token in self.tokens if token not in ignored)


@dataclass(slots=True, frozen=True)
class UniversalOpenTarget:
    """Structured description of one resolved open target."""

    kind: str
    display_name: str
    provider: str
    source: str
    launch_kind: str
    launch_target: str
    launch_args: tuple[str, ...] = ()
    launch_verb: str | None = None
    confidence: float = 0.0
    descriptor: str | None = None


@dataclass(slots=True, frozen=True)
class UniversalOpenResolution:
    """Outcome of a universal open lookup."""

    query: str
    found: bool
    target: UniversalOpenTarget | None = None
    ambiguous: bool = False
    reason: str | None = None
    candidates: tuple[UniversalOpenTarget, ...] = ()

    @classmethod
    def success(cls, query: str, target: UniversalOpenTarget) -> UniversalOpenResolution:
        """Build a successful resolution."""

        return cls(query=query, found=True, target=target, ambiguous=False, candidates=(target,))

    @classmethod
    def not_found(cls, query: str, reason: str) -> UniversalOpenResolution:
        """Build a not-found resolution."""

        return cls(query=query, found=False, target=None, ambiguous=False, reason=reason, candidates=())

    @classmethod
    def ambiguous_result(
        cls,
        query: str,
        *,
        reason: str,
        candidates: Sequence[UniversalOpenTarget],
    ) -> UniversalOpenResolution:
        """Build an ambiguous resolution."""

        return cls(
            query=query,
            found=False,
            target=None,
            ambiguous=True,
            reason=reason,
            candidates=tuple(candidates),
        )


class UniversalOpenProvider(Protocol):
    """Protocol implemented by one modular open-target provider."""

    provider_name: str

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        """Resolve a query or return ``None`` when this provider has no match."""


@dataclass(slots=True, frozen=True)
class _StaticTargetSpec:
    """Represents one registry entry for non-application targets."""

    display_name: str
    aliases: tuple[str, ...]
    kind: str
    launch_kind: str
    launch_target: str
    launch_args: tuple[str, ...] = ()
    launch_verb: str | None = None
    source: str = ""
    confidence: float = 0.99


class InstalledApplicationOpenProvider:
    """Resolve installed applications through the existing ApplicationResolver."""

    provider_name = "installed_applications"

    def __init__(
        self,
        *,
        application_resolver: ApplicationResolver,
        alias_variants: Mapping[str, Sequence[str]] | None = None,
        reserved_aliases: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.application_resolver = application_resolver
        self.reserved_aliases = frozenset(reserved_aliases or ())
        self.alias_variants = {
            key: tuple(value)
            for key, value in (
                alias_variants
                or {
                    "aftereffects": ("Adobe After Effects",),
                    "chrome": ("Google Chrome",),
                    "coreldraw": ("CorelDRAW", "CorelDRAW Graphics Suite"),
                    "illustrator": ("Adobe Illustrator",),
                    "premierepro": ("Adobe Premiere Pro",),
                    "vscode": ("Visual Studio Code", "VS Code"),
                }
            ).items()
        }

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        direct_target = self._resolve_attempt(query, query.raw)
        if direct_target is not None and self._is_acceptable_match(query, direct_target):
            return UniversalOpenResolution.success(query.raw, direct_target)

        best: tuple[float, UniversalOpenTarget] | None = None
        for attempt in self._attempts_for(query):
            candidate = self.application_resolver._resolve_candidate(  # noqa: SLF001 - shared internal scoring
                self.application_resolver._build_query(attempt)
            )
            if candidate is None:
                continue

            confidence = self._confidence_for(query, attempt, candidate)
            target = UniversalOpenTarget(
                kind="application",
                display_name=self._display_name(candidate, fallback=attempt),
                provider=self.provider_name,
                source=candidate.source,
                launch_kind=candidate.launch_kind,
                launch_target=candidate.launch_target,
                launch_args=(),
                launch_verb=None,
                confidence=confidence,
                descriptor=self.application_resolver._candidate_descriptor(candidate),  # noqa: SLF001
            )
            if not self._is_acceptable_match(query, target):
                continue
            if best is None or confidence > best[0]:
                best = (confidence, target)
        if best is None:
            return None
        return UniversalOpenResolution.success(query.raw, best[1])

    def _attempts_for(self, query: UniversalOpenQuery) -> tuple[str, ...]:
        """Return lookup attempts for one query."""

        variants = list(self.alias_variants.get(query.normalized, ()))
        seen: set[str] = set()
        attempts: list[str] = []
        for value in variants:
            text = str(value).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            attempts.append(text)
        return tuple(attempts)

    def _resolve_attempt(self, query: UniversalOpenQuery, attempt: str) -> UniversalOpenTarget | None:
        """Resolve one specific application lookup attempt."""

        candidate = self.application_resolver._resolve_candidate(  # noqa: SLF001 - shared internal scoring
            self.application_resolver._build_query(attempt)
        )
        if candidate is None:
            return None
        confidence = self._confidence_for(query, attempt, candidate)
        return UniversalOpenTarget(
            kind="application",
            display_name=self._display_name(candidate, fallback=attempt),
            provider=self.provider_name,
            source=candidate.source,
            launch_kind=candidate.launch_kind,
            launch_target=candidate.launch_target,
            launch_args=(),
            launch_verb=None,
            confidence=confidence,
            descriptor=self.application_resolver._candidate_descriptor(candidate),  # noqa: SLF001
        )

    def _confidence_for(self, query: UniversalOpenQuery, attempt: str, candidate: Any) -> float:
        """Estimate one confidence value for the resolved application candidate."""

        exact_labels = self.application_resolver._exact_labels(candidate)  # noqa: SLF001
        if query.normalized in exact_labels:
            return 1.0

        attempt_query = self.application_resolver._build_query(attempt)  # noqa: SLF001
        if attempt_query.normalized in exact_labels:
            return 0.98 if attempt_query.normalized == query.normalized else 0.96

        structured = max(
            self.application_resolver._structured_score(self.application_resolver._build_query(query.raw), candidate),  # noqa: SLF001
            self.application_resolver._structured_score(attempt_query, candidate),  # noqa: SLF001
        )
        if structured > 0.0:
            return min(0.97 if attempt_query.normalized != query.normalized else 0.99, max(0.84, structured))

        fuzzy = max(
            self.application_resolver._fuzzy_score(self.application_resolver._build_query(query.raw), candidate),  # noqa: SLF001
            self.application_resolver._fuzzy_score(attempt_query, candidate),  # noqa: SLF001
        )
        if attempt_query.normalized != query.normalized:
            fuzzy = min(fuzzy, 0.93)
        return max(0.0, fuzzy)

    def _is_acceptable_match(self, query: UniversalOpenQuery, target: UniversalOpenTarget) -> bool:
        """Return whether one resolved application can beat a reserved website alias."""

        if self._website_alias_key(query) is None:
            return True
        return target.confidence >= 0.95

    def _website_alias_key(self, query: UniversalOpenQuery) -> str | None:
        """Return the normalized website alias key for one query when reserved."""

        normalized = query.normalized_without(_EXPLICIT_WEBSITE_TOKENS)
        if not normalized:
            normalized = query.normalized
        return normalized if normalized in self.reserved_aliases else None

    @staticmethod
    def _display_name(candidate: Any, *, fallback: str) -> str:
        """Return a readable display name for one application candidate."""

        for label in getattr(candidate, "display_labels", ()):
            if str(label).strip():
                return str(label).strip()
        descriptor = getattr(candidate, "path", None)
        if descriptor is not None:
            return Path(str(descriptor)).stem
        return fallback


class WindowsSystemToolProvider:
    """Resolve native Windows tools through curated safe launch entries."""

    provider_name = "windows_system_tools"

    def __init__(
        self,
        *,
        os_type: str | None = None,
        windows_root: str | Path | None = None,
        entries: Sequence[_StaticTargetSpec] | None = None,
    ) -> None:
        self.os_type = os_type or platform.system()
        self.windows_root = Path(os.path.expandvars(str(windows_root))) if windows_root is not None else Path(
            os.getenv("WINDIR", "C:\\Windows")
        )
        self._entries = tuple(entries) if entries is not None else self._default_entries()

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        if self.os_type != "Windows":
            return None
        return _resolve_static_target(query, self._entries, provider=self.provider_name, validator=self._is_valid_entry)

    def _default_entries(self) -> tuple[_StaticTargetSpec, ...]:
        """Return the default native Windows tool entries."""

        system32 = self.windows_root / "System32"
        powershell = system32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        return (
            _StaticTargetSpec("Command Prompt", ("cmd", "command prompt"), "system_tool", "path", str(system32 / "cmd.exe"), source="cmd"),
            _StaticTargetSpec("Windows PowerShell", ("powershell", "power shell", "windows powershell"), "system_tool", "path", str(powershell), source="powershell"),
            _StaticTargetSpec("Task Manager", ("task manager",), "system_tool", "path", str(system32 / "taskmgr.exe"), source="task_manager"),
            _StaticTargetSpec("Control Panel", ("control panel",), "system_tool", "path", str(system32 / "control.exe"), source="control_panel"),
            _StaticTargetSpec(
                "Device Manager",
                ("device manager",),
                "system_tool",
                "shell_file",
                str(system32 / "devmgmt.msc"),
                launch_verb="runas",
                source="device_manager",
            ),
            _StaticTargetSpec("Disk Management", ("disk management",), "system_tool", "path", str(system32 / "mmc.exe"), (str(system32 / "diskmgmt.msc"),), source="disk_management"),
            _StaticTargetSpec("Services", ("services",), "system_tool", "path", str(system32 / "mmc.exe"), (str(system32 / "services.msc"),), source="services"),
            _StaticTargetSpec("Event Viewer", ("event viewer",), "system_tool", "path", str(system32 / "mmc.exe"), (str(system32 / "eventvwr.msc"),), source="event_viewer"),
            _StaticTargetSpec("Registry Editor", ("registry editor", "regedit"), "system_tool", "path", str(system32 / "regedit.exe"), source="registry_editor"),
            _StaticTargetSpec("Resource Monitor", ("resource monitor",), "system_tool", "path", str(system32 / "resmon.exe"), source="resource_monitor"),
            _StaticTargetSpec("System Information", ("system information", "msinfo32"), "system_tool", "path", str(system32 / "msinfo32.exe"), source="system_information"),
            _StaticTargetSpec("Snipping Tool", ("snipping tool",), "system_tool", "path", str(system32 / "SnippingTool.exe"), source="snipping_tool"),
            _StaticTargetSpec("Notepad", ("notepad",), "system_tool", "path", str(system32 / "notepad.exe"), source="notepad"),
            _StaticTargetSpec("Paint", ("paint",), "system_tool", "path", str(system32 / "mspaint.exe"), source="paint"),
            _StaticTargetSpec("File Explorer", ("file explorer", "explorer"), "system_tool", "path", str(system32 / "explorer.exe"), source="file_explorer"),
        )

    @staticmethod
    def _is_valid_entry(spec: _StaticTargetSpec) -> bool:
        """Return whether one system-tool entry is launchable."""

        executable = Path(spec.launch_target)
        if not executable.exists():
            return False
        for argument in spec.launch_args:
            if ":" in argument and argument.endswith(".msc") and not Path(argument).exists():
                return False
        return True


class WindowsSettingsOpenProvider:
    """Resolve Windows Settings pages through safe ``ms-settings:`` URIs."""

    provider_name = "windows_settings"

    def __init__(self, entries: Sequence[_StaticTargetSpec] | None = None) -> None:
        self._entries = tuple(entries) if entries is not None else (
            _StaticTargetSpec("Settings", ("settings", "windows settings"), "settings", "uri", "ms-settings:", source="settings"),
            _StaticTargetSpec("Bluetooth Settings", ("bluetooth settings",), "settings", "uri", "ms-settings:bluetooth", source="bluetooth"),
            _StaticTargetSpec("Wi-Fi Settings", ("wi fi settings", "wifi settings", "wi-fi settings"), "settings", "uri", "ms-settings:network-wifi", source="wifi"),
            _StaticTargetSpec("Display Settings", ("display settings",), "settings", "uri", "ms-settings:display", source="display"),
            _StaticTargetSpec("Sound Settings", ("sound settings", "audio settings"), "settings", "uri", "ms-settings:sound", source="sound"),
            _StaticTargetSpec("Storage Settings", ("storage settings",), "settings", "uri", "ms-settings:storagesense", source="storage"),
            _StaticTargetSpec("Windows Update", ("windows update", "update settings"), "settings", "uri", "ms-settings:windowsupdate", source="windows_update"),
            _StaticTargetSpec("Installed Apps", ("installed apps", "installed applications"), "settings", "uri", "ms-settings:appsfeatures", source="installed_apps"),
            _StaticTargetSpec("Startup Apps", ("startup apps",), "settings", "uri", "ms-settings:startupapps", source="startup_apps"),
        )

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        return _resolve_static_target(query, self._entries, provider=self.provider_name, validator=lambda spec: True)


class KnownFolderOpenProvider:
    """Resolve user known folders through the Windows shell-folder registry."""

    provider_name = "known_folders"

    def __init__(
        self,
        *,
        os_type: str | None = None,
        folder_reader: Callable[[], Mapping[str, Path]] | None = None,
    ) -> None:
        self.os_type = os_type or platform.system()
        self._folder_reader = folder_reader if folder_reader is not None else self._read_known_folders
        self._aliases = {
            "desktop": ("desktop",),
            "documents": ("documents", "my documents"),
            "downloads": ("downloads",),
            "home": ("home", "home folder", "user home", "profile", "user folder"),
            "music": ("music",),
            "pictures": ("pictures",),
            "screenshots": ("screenshots", "screenshots folder"),
            "videos": ("videos",),
        }

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        normalized = query.normalized_without({"folder"})
        folder_key = next(
            (
                key
                for key, aliases in self._aliases.items()
                if normalized in {ApplicationResolver._normalize_name(alias) for alias in aliases}
            ),
            None,
        )
        if folder_key is None:
            return None

        folders = self._folder_reader()
        path = folders.get(folder_key)
        if path is None or not path.exists() or not path.is_dir():
            return UniversalOpenResolution.not_found(query.raw, f"Known folder '{folder_key}' is unavailable.")
        return UniversalOpenResolution.success(
            query.raw,
            UniversalOpenTarget(
                kind="known_folder",
                display_name=folder_key.replace("_", " ").title(),
                provider=self.provider_name,
                source=folder_key,
                launch_kind="explorer_path",
                launch_target=str(path),
                confidence=0.99,
                descriptor=str(path),
            ),
        )

    def _read_known_folders(self) -> Mapping[str, Path]:
        """Read known-folder locations from the Windows shell-folder registry."""

        results: dict[str, Path] = {}
        user_profile = os.getenv("USERPROFILE")
        if user_profile:
            results["home"] = Path(user_profile)

        if self.os_type != "Windows" or winreg is None:
            return results

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as shell_key:
                for folder_name, registry_name in _KNOWN_FOLDER_GUID_KEYS.items():
                    raw_value = ApplicationResolver._query_registry_value(shell_key, registry_name)
                    if not raw_value:
                        continue
                    results[folder_name] = Path(os.path.expandvars(raw_value)).expanduser()
        except OSError:
            return results
        return results


class DriveAndShellOpenProvider:
    """Resolve Windows drives and shell locations."""

    provider_name = "drives_and_shell_locations"

    def __init__(
        self,
        *,
        drive_exists: Callable[[Path], bool] | None = None,
        entries: Sequence[_StaticTargetSpec] | None = None,
    ) -> None:
        self.drive_exists = drive_exists if drive_exists is not None else lambda path: path.exists()
        self._entries = tuple(entries) if entries is not None else (
            _StaticTargetSpec("This PC", ("this pc", "my computer", "computer"), "shell_location", "explorer_shell", "shell:MyComputerFolder", source="this_pc"),
            _StaticTargetSpec("Recycle Bin", ("recycle bin",), "shell_location", "explorer_shell", "shell:RecycleBinFolder", source="recycle_bin"),
            _StaticTargetSpec("Network", ("network",), "shell_location", "explorer_shell", "shell:NetworkPlacesFolder", source="network"),
        )

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        drive_match = _DRIVE_PATTERN.match(query.raw)
        if drive_match is not None:
            drive_letter = drive_match.group("drive").upper()
            drive_path = Path(f"{drive_letter}:\\")
            if not self.drive_exists(drive_path):
                return UniversalOpenResolution.not_found(query.raw, f"Drive {drive_letter}: is not available.")
            return UniversalOpenResolution.success(
                query.raw,
                UniversalOpenTarget(
                    kind="drive",
                    display_name=f"{drive_letter} Drive",
                    provider=self.provider_name,
                    source="drive_letter",
                    launch_kind="explorer_path",
                    launch_target=str(drive_path),
                    confidence=0.99,
                    descriptor=str(drive_path),
                ),
            )

        return _resolve_static_target(query, self._entries, provider=self.provider_name, validator=lambda spec: True)


class WebsiteOpenProvider:
    """Resolve curated website aliases to safe HTTPS URLs."""

    provider_name = "websites"

    def __init__(self, entries: Sequence[_StaticTargetSpec] | None = None) -> None:
        self._entries = tuple(entries) if entries is not None else self._default_entries()
        self._normalized_aliases = {
            ApplicationResolver._normalize_name(alias): spec
            for spec in self._entries
            for alias in spec.aliases
        }
        self.normalized_aliases = frozenset(self._normalized_aliases)

    @staticmethod
    def _default_entries() -> tuple[_StaticTargetSpec, ...]:
        """Return the curated public-website registry."""

        return (
            _StaticTargetSpec("Amazon", ("amazon",), "website", "url", "https://www.amazon.com/", source="amazon", confidence=0.93),
            _StaticTargetSpec("Canva", ("canva",), "website", "url", "https://www.canva.com/", source="canva", confidence=0.93),
            _StaticTargetSpec("ChatGPT", ("chatgpt", "chat gpt"), "website", "url", "https://chatgpt.com/", source="chatgpt", confidence=0.93),
            _StaticTargetSpec("Facebook", ("facebook",), "website", "url", "https://www.facebook.com/", source="facebook", confidence=0.93),
            _StaticTargetSpec("Flipkart", ("flipkart",), "website", "url", "https://www.flipkart.com/", source="flipkart", confidence=0.93),
            _StaticTargetSpec("Gmail", ("gmail", "google mail"), "website", "url", "https://mail.google.com/", source="gmail", confidence=0.93),
            _StaticTargetSpec("GitHub", ("github",), "website", "url", "https://github.com/", source="github", confidence=0.93),
            _StaticTargetSpec("Google Drive", ("google drive", "g drive"), "website", "url", "https://drive.google.com/", source="google_drive", confidence=0.93),
            _StaticTargetSpec("Instagram", ("instagram",), "website", "url", "https://www.instagram.com/", source="instagram", confidence=0.93),
            _StaticTargetSpec("LinkedIn", ("linkedin", "linked in"), "website", "url", "https://www.linkedin.com/", source="linkedin", confidence=0.93),
            _StaticTargetSpec("Reddit", ("reddit",), "website", "url", "https://www.reddit.com/", source="reddit", confidence=0.93),
            _StaticTargetSpec("X", ("x", "twitter", "x twitter", "twitter x"), "website", "url", "https://x.com/", source="x", confidence=0.93),
            _StaticTargetSpec("YouTube", ("youtube",), "website", "url", "https://www.youtube.com/", source="youtube", confidence=0.93),
        )

    def resolve(self, query: UniversalOpenQuery) -> UniversalOpenResolution | None:
        normalized = query.normalized_without(_EXPLICIT_WEBSITE_TOKENS)
        if not normalized:
            normalized = query.normalized

        spec = self._normalized_aliases.get(normalized)
        if spec is None:
            return None

        confidence = 0.99 if query.explicit_website else spec.confidence
        return UniversalOpenResolution.success(
            query.raw,
            UniversalOpenTarget(
                kind=spec.kind,
                display_name=spec.display_name,
                provider=self.provider_name,
                source=spec.source or spec.display_name,
                launch_kind=spec.launch_kind,
                launch_target=spec.launch_target,
                launch_args=spec.launch_args,
                launch_verb=spec.launch_verb,
                confidence=confidence,
                descriptor=spec.launch_target,
            ),
        )


class UniversalOpenResolver:
    """Resolve natural-language open targets through modular providers."""

    def __init__(
        self,
        *,
        application_resolver: ApplicationResolver,
        providers: Sequence[UniversalOpenProvider] | None = None,
        logger: Any | None = None,
        os_type: str | None = None,
        cache: dict[str, UniversalOpenResolution] | None = None,
    ) -> None:
        self.application_resolver = application_resolver
        self.logger = logger or logging.getLogger(__name__)
        self.os_type = os_type or platform.system()
        if providers is None:
            website_provider = WebsiteOpenProvider()
            installed_application_provider = InstalledApplicationOpenProvider(
                application_resolver=self.application_resolver,
                reserved_aliases=website_provider.normalized_aliases,
            )
            self.providers = (
                WindowsSystemToolProvider(os_type=self.os_type),
                WindowsSettingsOpenProvider(),
                KnownFolderOpenProvider(os_type=self.os_type),
                DriveAndShellOpenProvider(),
                installed_application_provider,
                website_provider,
            )
        else:
            self.providers = tuple(providers)
        self._cache = cache if cache is not None else {}

    def resolve(self, target_name: str) -> UniversalOpenResolution:
        """Resolve a natural-language open target into a structured descriptor."""

        query = self._build_query(target_name)
        if not query.normalized:
            return UniversalOpenResolution.not_found(target_name, "No launch target was supplied.")

        cached = self._cache.get(query.raw.strip().lower())
        if cached is not None:
            return cached

        providers = self._provider_sequence(query)
        for provider in providers:
            resolution = provider.resolve(query)
            if resolution is None:
                continue
            self._cache[query.raw.strip().lower()] = resolution
            if resolution.found and resolution.target is not None:
                _emit_log(
                    self.logger,
                    "info",
                    "Resolved universal open target",
                    query=target_name,
                    kind=resolution.target.kind,
                    provider=resolution.target.provider,
                    source=resolution.target.source,
                    launch_target=resolution.target.launch_target,
                )
            return resolution

        resolution = UniversalOpenResolution.not_found(target_name, f"No open target matched '{target_name}'.")
        self._cache[query.raw.strip().lower()] = resolution
        _emit_log(self.logger, "warning", "Unable to resolve universal open target", query=target_name)
        return resolution

    def _provider_sequence(self, query: UniversalOpenQuery) -> tuple[UniversalOpenProvider, ...]:
        """Return the provider order for one query."""

        if not query.explicit_website:
            return self.providers

        websites = [provider for provider in self.providers if getattr(provider, "provider_name", "") == "websites"]
        others = [provider for provider in self.providers if getattr(provider, "provider_name", "") != "websites"]
        return tuple((*websites, *others))

    @staticmethod
    def _build_query(value: str) -> UniversalOpenQuery:
        """Build one universal open query."""

        tokens = ApplicationResolver._tokenize(value)
        return UniversalOpenQuery(
            raw=value,
            normalized=ApplicationResolver._normalize_name(value),
            tokens=tokens,
            explicit_website=any(token in _EXPLICIT_WEBSITE_TOKENS for token in tokens),
        )


class UniversalOpenLauncher:
    """Launch one structured universal open target."""

    def __init__(
        self,
        *,
        application_resolver: ApplicationResolver,
        logger: Any | None = None,
        os_type: str | None = None,
    ) -> None:
        self.application_resolver = application_resolver
        self.logger = logger or logging.getLogger(__name__)
        self.os_type = os_type or platform.system()

    def launch(self, target: UniversalOpenTarget) -> bool:
        """Launch the supplied target descriptor."""

        try:
            if target.launch_kind == "path":
                return self.application_resolver.launch_path(target.launch_target, target.launch_args)
            if target.launch_kind == "shell_file":
                path = Path(target.launch_target)
                if not path.exists() or not path.is_file():
                    return False
                return self._open_with_shell_handler(target.launch_target, verb=target.launch_verb)
            if target.launch_kind == "explorer_path":
                path = Path(target.launch_target)
                if not path.exists() or not path.is_dir():
                    return False
                subprocess.Popen(["explorer.exe", target.launch_target])
                return True
            if target.launch_kind == "explorer_shell":
                subprocess.Popen(["explorer.exe", target.launch_target])
                return True
            if target.launch_kind == "url":
                if not _WEBSITE_URL_PATTERN.match(target.launch_target):
                    return False
                return self._open_with_shell_handler(target.launch_target)
            if target.launch_kind == "uri":
                if not _SETTINGS_URI_PATTERN.match(target.launch_target):
                    return False
                return self._open_with_shell_handler(target.launch_target)
            if target.launch_kind == "shortcut":
                if hasattr(os, "startfile"):
                    os.startfile(target.launch_target)  # type: ignore[attr-defined]
                else:  # pragma: no cover - Windows-specific fallback
                    subprocess.Popen(target.launch_target)
                return True
            if target.launch_kind == "appsfolder":
                subprocess.Popen(["explorer.exe", target.launch_target])
                return True
        except Exception as error:
            _emit_log(
                self.logger,
                "warning",
                "Failed to launch universal open target",
                display_name=target.display_name,
                launch_kind=target.launch_kind,
                error=str(error),
            )
            return False

        return False

    def _open_with_shell_handler(self, launch_target: str, *, verb: str | None = None) -> bool:
        """Open one URI or URL with the Windows shell handler."""

        try:
            if hasattr(os, "startfile"):
                if verb:
                    os.startfile(launch_target, verb)  # type: ignore[attr-defined]
                else:
                    os.startfile(launch_target)  # type: ignore[attr-defined]
            else:  # pragma: no cover - Windows-specific fallback
                if verb:
                    return False
                subprocess.Popen(["explorer.exe", launch_target])
            return True
        except Exception:
            return False


def _resolve_static_target(
    query: UniversalOpenQuery,
    entries: Sequence[_StaticTargetSpec],
    *,
    provider: str,
    validator: Callable[[_StaticTargetSpec], bool],
) -> UniversalOpenResolution | None:
    """Resolve one query against a static entry registry."""

    for spec in entries:
        alias_map = {ApplicationResolver._normalize_name(alias) for alias in spec.aliases}
        if query.normalized not in alias_map:
            continue
        if not validator(spec):
            return UniversalOpenResolution.not_found(query.raw, f"{spec.display_name} is not available.")
        return UniversalOpenResolution.success(
            query.raw,
            UniversalOpenTarget(
                kind=spec.kind,
                display_name=spec.display_name,
                provider=provider,
                source=spec.source or spec.display_name,
                launch_kind=spec.launch_kind,
                launch_target=spec.launch_target,
                launch_args=spec.launch_args,
                launch_verb=spec.launch_verb,
                confidence=spec.confidence,
                descriptor=spec.launch_target,
            ),
        )
    return None


__all__ = [
    "DriveAndShellOpenProvider",
    "InstalledApplicationOpenProvider",
    "KnownFolderOpenProvider",
    "UniversalOpenLauncher",
    "UniversalOpenQuery",
    "UniversalOpenResolution",
    "UniversalOpenResolver",
    "UniversalOpenTarget",
    "UniversalOpenProvider",
    "WebsiteOpenProvider",
    "WindowsSettingsOpenProvider",
    "WindowsSystemToolProvider",
]
