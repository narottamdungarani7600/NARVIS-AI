"""Universal Windows application resolution helpers for NARVIS."""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # pragma: no cover - registry access is only available on Windows
    import winreg
except Exception:  # pragma: no cover - optional dependency
    winreg = None


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_LAUNCHABLE_SUFFIXES = {".exe", ".bat", ".cmd", ".com"}
_SHORTCUT_SUFFIXES = {".lnk", *_LAUNCHABLE_SUFFIXES}
_SKIP_DIRECTORY_NAMES = {
    "$recycle.bin",
    "__pycache__",
    "cache",
    "caches",
    "common files",
    "history",
    "logs",
    "node_modules",
    "packages",
    "temp",
    "tmp",
    "vendor",
    "windowsapps",
}


@dataclass(slots=True, frozen=True)
class _ApplicationCandidate:
    """Represents one launchable application candidate."""

    path: Path
    source: str
    labels: tuple[str, ...]


class ApplicationResolver:
    """Resolve installed Windows applications without relying on aliases."""

    def __init__(
        self,
        *,
        start_menu_roots: Sequence[str | Path] | None = None,
        desktop_roots: Sequence[str | Path] | None = None,
        path_directories: Sequence[str | Path] | None = None,
        program_files_roots: Sequence[str | Path] | None = None,
        windows_apps_root: str | Path | None = None,
        registry_reader: Callable[[], Iterable[Mapping[str, str]]] | None = None,
        shortcut_target_resolver: Callable[[Path], Path | None] | None = None,
        cache: dict[str, str] | None = None,
        os_type: str | None = None,
        logger: Any | None = None,
    ) -> None:
        """Initialize the resolver with optional dependency-injected providers."""

        self.os_type = os_type or platform.system()
        self.logger = logger or logging.getLogger(__name__)
        self.start_menu_roots = self._coerce_paths(
            self._default_start_menu_roots() if start_menu_roots is None else start_menu_roots
        )
        self.desktop_roots = self._coerce_paths(
            self._default_desktop_roots() if desktop_roots is None else desktop_roots
        )
        self.path_directories = self._coerce_paths(
            self._default_path_directories() if path_directories is None else path_directories
        )
        self.program_files_roots = self._coerce_paths(
            self._default_program_files_roots() if program_files_roots is None else program_files_roots
        )
        self.windows_apps_root = self._coerce_optional_path(
            self._default_windows_apps_root() if windows_apps_root is None else windows_apps_root
        )
        self._registry_reader = registry_reader if registry_reader is not None else self._read_registry_uninstall_entries
        self._shortcut_target_resolver = (
            shortcut_target_resolver if shortcut_target_resolver is not None else self._resolve_shortcut_target
        )
        self._resolved_cache: dict[str, str] = cache if cache is not None else {}
        self._candidate_cache: dict[str, tuple[_ApplicationCandidate, ...]] = {}

    def resolve(self, app_name: str) -> str | None:
        """Resolve an application name to an executable path."""

        normalized_name = self._normalize_name(app_name)
        if not normalized_name:
            return None

        cached = self._resolved_cache.get(normalized_name)
        if cached is not None and self._is_launchable_path(Path(cached)):
            _emit_log(self.logger, "debug", "Resolved application from cache", app_name=app_name, path=cached)
            return cached

        for source_name, candidates in (
            ("shortcuts", self._shortcut_candidates()),
            ("path", self._path_candidates()),
            ("program_files", self._program_files_candidates()),
            ("registry", self._registry_candidates()),
            ("windows_apps", self._windows_apps_candidates()),
        ):
            matched = self._select_candidate(app_name, candidates)
            if matched is None:
                continue
            resolved_path = self._finalize_candidate_path(matched.path)
            if resolved_path is None:
                continue
            resolved = str(resolved_path)
            self._resolved_cache[normalized_name] = resolved
            _emit_log(
                self.logger,
                "info",
                "Resolved application",
                app_name=app_name,
                path=resolved,
                source=source_name,
            )
            return resolved

        _emit_log(self.logger, "warning", "Unable to resolve application", app_name=app_name)
        return None

    def find_shortcuts(self) -> tuple[str, ...]:
        """Return application shortcuts discovered from Start Menu and Desktop roots."""

        results: list[str] = []
        seen: set[str] = set()
        for candidate in self._shortcut_candidates():
            resolved_path = self._finalize_candidate_path(candidate.path)
            if resolved_path is None:
                continue
            key = str(resolved_path).lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(str(resolved_path))
        return tuple(results)

    def find_registry(self) -> tuple[str, ...]:
        """Return executable candidates discovered from registry uninstall entries."""

        return tuple(str(candidate.path) for candidate in self._registry_candidates())

    def find_path(self) -> tuple[str, ...]:
        """Return executable candidates discovered from PATH directories."""

        return tuple(str(candidate.path) for candidate in self._path_candidates())

    def find_program_files(self) -> tuple[str, ...]:
        """Return executable candidates discovered from Program Files roots."""

        return tuple(str(candidate.path) for candidate in self._program_files_candidates())

    def find_windows_apps(self) -> tuple[str, ...]:
        """Return Windows App Execution Alias candidates."""

        return tuple(str(candidate.path) for candidate in self._windows_apps_candidates())

    def launch(self, app_name: str) -> bool:
        """Resolve and launch an application by name."""

        resolved = self.resolve(app_name)
        if resolved is None:
            return False

        try:
            subprocess.Popen(resolved)
            _emit_log(self.logger, "info", "Launched resolved application", app_name=app_name, path=resolved)
            return True
        except Exception as error:
            _emit_log(self.logger, "warning", "Failed to launch resolved application", app_name=app_name, error=str(error))
            return False

    def _shortcut_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached shortcut candidates in Start Menu then Desktop order."""

        return self._cached_candidates("shortcuts", self._build_shortcut_candidates)

    def _registry_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached registry-derived candidates."""

        return self._cached_candidates("registry", self._build_registry_candidates)

    def _path_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached PATH-derived candidates."""

        return self._cached_candidates("path", self._build_path_candidates)

    def _program_files_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Program Files-derived candidates."""

        return self._cached_candidates("program_files", self._build_program_files_candidates)

    def _windows_apps_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Windows App Execution Alias candidates."""

        return self._cached_candidates("windows_apps", self._build_windows_apps_candidates)

    def _build_shortcut_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Scan Start Menu and Desktop roots for executable shortcuts."""

        candidates: list[_ApplicationCandidate] = []
        for root in self.start_menu_roots:
            candidates.extend(self._scan_directory(root, source="start_menu", suffixes=_SHORTCUT_SUFFIXES, max_depth=6))
        for root in self.desktop_roots:
            candidates.extend(self._scan_directory(root, source="desktop", suffixes=_SHORTCUT_SUFFIXES, max_depth=3))
        return self._dedupe_candidates(candidates)

    def _build_registry_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build executable candidates from registry uninstall metadata."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._registry_reader():
            display_name = str(entry.get("DisplayName", "") or "").strip()
            display_icon = str(entry.get("DisplayIcon", "") or "").strip()
            install_location = str(entry.get("InstallLocation", "") or "").strip()
            for candidate_path in self._registry_entry_paths(
                display_name=display_name,
                display_icon=display_icon,
                install_location=install_location,
            ):
                labels = [display_name, candidate_path.stem, candidate_path.parent.name]
                candidate = self._candidate_from_path(candidate_path, source="registry", extra_labels=labels)
                if candidate is not None:
                    candidates.append(candidate)
        return self._dedupe_candidates(candidates)

    def _build_path_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build executable candidates from PATH directories."""

        candidates: list[_ApplicationCandidate] = []
        for directory in self.path_directories:
            if not directory.exists() or not directory.is_dir():
                continue
            try:
                for child in directory.iterdir():
                    if not child.is_file() or child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                        continue
                    candidate = self._candidate_from_path(child, source="path")
                    if candidate is not None:
                        candidates.append(candidate)
            except OSError as error:  # pragma: no cover - depends on host filesystem permissions
                _emit_log(self.logger, "debug", "Unable to inspect PATH directory", path=str(directory), error=str(error))
        return self._dedupe_candidates(candidates)

    def _build_program_files_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build executable candidates from Program Files and LocalAppData roots."""

        candidates: list[_ApplicationCandidate] = []
        for root in self.program_files_roots:
            candidates.extend(self._scan_directory(root, source="program_files", suffixes=_LAUNCHABLE_SUFFIXES, max_depth=5))
        return self._dedupe_candidates(candidates)

    def _build_windows_apps_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Windows App Execution Aliases."""

        root = self.windows_apps_root
        if root is None or not root.exists() or not root.is_dir():
            return ()

        candidates: list[_ApplicationCandidate] = []
        try:
            for child in root.iterdir():
                if not child.is_file() or child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                    continue
                candidate = self._candidate_from_path(child, source="windows_apps")
                if candidate is not None:
                    candidates.append(candidate)
        except OSError as error:  # pragma: no cover - depends on host filesystem permissions
            _emit_log(self.logger, "debug", "Unable to inspect Windows Apps directory", path=str(root), error=str(error))
        return self._dedupe_candidates(candidates)

    def _select_candidate(self, app_name: str, candidates: Iterable[_ApplicationCandidate]) -> _ApplicationCandidate | None:
        """Return the best matching candidate for a requested application name."""

        best: tuple[float, _ApplicationCandidate] | None = None
        for candidate in candidates:
            score = self._score_candidate(app_name, candidate.labels)
            if score < 0.6:
                continue
            if best is None or score > best[0]:
                best = (score, candidate)
        return best[1] if best is not None else None

    def _score_candidate(self, query: str, labels: Iterable[str]) -> float:
        """Score how well a candidate's labels match the query."""

        query_normalized = self._normalize_name(query)
        query_tokens = set(self._tokenize(query))
        query_acronym = self._acronym(query_tokens)
        best_score = 0.0

        for label in labels:
            normalized_label = self._normalize_name(label)
            label_tokens = set(self._tokenize(label))
            label_acronym = self._acronym(label_tokens)
            score = 0.0

            if not normalized_label:
                continue
            if normalized_label == query_normalized:
                score = 1.0
            elif normalized_label.startswith(query_normalized):
                score = 0.95
            elif query_normalized.startswith(normalized_label):
                score = 0.9
            elif normalized_label in query_normalized or query_normalized in normalized_label:
                score = 0.82
            elif label_tokens and query_tokens:
                overlap = len(label_tokens & query_tokens)
                if overlap:
                    score = max(score, 0.35 + (overlap / max(len(label_tokens), len(query_tokens))) * 0.5)
                    if query_tokens <= label_tokens or label_tokens <= query_tokens:
                        score += 0.1
            if query_acronym and label_acronym and query_acronym == label_acronym:
                score = max(score, 0.84)
            best_score = max(best_score, min(score, 0.99))

        return best_score

    def _registry_entry_paths(
        self,
        *,
        display_name: str,
        display_icon: str,
        install_location: str,
    ) -> tuple[Path, ...]:
        """Extract launchable paths from one registry uninstall entry."""

        candidates: list[Path] = []
        icon_path = self._clean_registry_path(display_icon)
        if icon_path is not None and self._is_launchable_path(icon_path):
            candidates.append(icon_path)

        install_root = self._coerce_optional_path(install_location)
        if install_root is not None and install_root.exists() and install_root.is_dir():
            best_from_location = self._select_candidate(
                display_name or install_root.name,
                self._scan_directory(install_root, source="registry_install", suffixes=_LAUNCHABLE_SUFFIXES, max_depth=2),
            )
            if best_from_location is not None:
                candidates.append(best_from_location.path)

        deduped: dict[str, Path] = {}
        for candidate in candidates:
            deduped.setdefault(str(candidate).lower(), candidate)
        return tuple(deduped.values())

    def _scan_directory(
        self,
        root: Path,
        *,
        source: str,
        suffixes: set[str],
        max_depth: int,
    ) -> list[_ApplicationCandidate]:
        """Scan a directory tree for executable or shortcut candidates."""

        if not root.exists() or not root.is_dir():
            return []

        candidates: list[_ApplicationCandidate] = []
        base_depth = len(root.parts)

        def _handle_walk_error(error: OSError) -> None:
            _emit_log(self.logger, "debug", "Unable to scan application directory", path=str(root), error=str(error))

        for current_root, directories, filenames in os.walk(root, onerror=_handle_walk_error):
            current_path = Path(current_root)
            depth = len(current_path.parts) - base_depth
            if depth >= max_depth:
                directories[:] = []
            else:
                directories[:] = [
                    name
                    for name in directories
                    if name.strip().lower() not in _SKIP_DIRECTORY_NAMES and not name.startswith(".")
                ]

            for filename in filenames:
                path = current_path / filename
                if path.suffix.lower() not in suffixes:
                    continue
                candidate = self._candidate_from_path(path, source=source)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _candidate_from_path(
        self,
        path: Path,
        *,
        source: str,
        extra_labels: Iterable[str] = (),
    ) -> _ApplicationCandidate | None:
        """Create a candidate record from a filesystem path."""

        labels = [
            path.stem,
            path.name,
            path.parent.name,
        ]
        labels.extend(extra_labels)
        unique_labels = tuple(label.strip() for label in labels if isinstance(label, str) and label.strip())
        if not unique_labels:
            return None
        return _ApplicationCandidate(path=path, source=source, labels=unique_labels)

    def _finalize_candidate_path(self, path: Path) -> Path | None:
        """Convert a candidate path into a launchable executable path."""

        if path.suffix.lower() == ".lnk":
            target = self._shortcut_target_resolver(path)
            if target is not None and self._is_launchable_path(target):
                return target
            return None
        if self._is_launchable_path(path):
            return path
        return None

    def _resolve_shortcut_target(self, shortcut_path: Path) -> Path | None:
        """Resolve a Windows shortcut target path when possible."""

        if self.os_type != "Windows":
            return None

        shortcut = str(shortcut_path)
        script = (
            "$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); "
            "if ($shortcut.TargetPath) { Write-Output $shortcut.TargetPath }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script, shortcut],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except Exception:  # pragma: no cover - depends on host PowerShell availability
            return None

        target = result.stdout.strip()
        if not target:
            return None
        return self._coerce_optional_path(target)

    def _read_registry_uninstall_entries(self) -> tuple[Mapping[str, str], ...]:
        """Read Windows uninstall metadata from the registry."""

        if self.os_type != "Windows" or winreg is None:
            return ()

        entries: list[dict[str, str]] = []
        registry_locations = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        )

        for hive, location in registry_locations:
            try:
                with winreg.OpenKey(hive, location) as parent_key:
                    subkey_count = winreg.QueryInfoKey(parent_key)[0]
                    for index in range(subkey_count):
                        try:
                            subkey_name = winreg.EnumKey(parent_key, index)
                            with winreg.OpenKey(parent_key, subkey_name) as subkey:
                                entry = {
                                    "DisplayName": self._query_registry_value(subkey, "DisplayName"),
                                    "DisplayIcon": self._query_registry_value(subkey, "DisplayIcon"),
                                    "InstallLocation": self._query_registry_value(subkey, "InstallLocation"),
                                }
                                if any(entry.values()):
                                    entries.append(entry)
                        except OSError:
                            continue
            except OSError:
                continue

        return tuple(entries)

    def _cached_candidates(
        self,
        key: str,
        builder: Callable[[], tuple[_ApplicationCandidate, ...]],
    ) -> tuple[_ApplicationCandidate, ...]:
        """Return cached candidates or build them once."""

        cached = self._candidate_cache.get(key)
        if cached is not None:
            return cached
        built = builder()
        self._candidate_cache[key] = built
        return built

    @staticmethod
    def _default_start_menu_roots() -> tuple[Path, ...]:
        """Return the standard Windows Start Menu roots."""

        program_data = os.getenv("ProgramData")
        appdata = os.getenv("APPDATA")
        roots = []
        if program_data:
            roots.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu")
        if appdata:
            roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu")
        return tuple(roots)

    @staticmethod
    def _default_desktop_roots() -> tuple[Path, ...]:
        """Return the standard Windows Desktop roots."""

        public_root = os.getenv("PUBLIC")
        user_profile = os.getenv("USERPROFILE")
        roots = []
        if public_root:
            roots.append(Path(public_root) / "Desktop")
        if user_profile:
            roots.append(Path(user_profile) / "Desktop")
        return tuple(roots)

    @staticmethod
    def _default_path_directories() -> tuple[Path, ...]:
        """Return PATH directories as candidate search roots."""

        raw_path = os.getenv("PATH", "")
        return tuple(Path(entry) for entry in raw_path.split(os.pathsep) if entry.strip())

    @staticmethod
    def _default_program_files_roots() -> tuple[Path, ...]:
        """Return Program Files and LocalAppData roots in lookup order."""

        roots = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.getenv(env_name)
            if value:
                roots.append(Path(value))
        return tuple(roots)

    @staticmethod
    def _default_windows_apps_root() -> Path | None:
        """Return the Windows App Execution Alias directory."""

        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            return None
        return Path(local_app_data) / "Microsoft" / "WindowsApps"

    @staticmethod
    def _coerce_paths(values: Sequence[str | Path]) -> tuple[Path, ...]:
        """Normalize and deduplicate a sequence of path-like values."""

        seen: set[str] = set()
        results: list[Path] = []
        for value in values:
            candidate = ApplicationResolver._coerce_optional_path(value)
            if candidate is None:
                continue
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)
        return tuple(results)

    @staticmethod
    def _coerce_optional_path(value: str | Path | None) -> Path | None:
        """Return a normalized ``Path`` when a path-like value is supplied."""

        if value is None:
            return None
        text = str(value).strip().strip("\"")
        if not text:
            return None
        return Path(os.path.expandvars(text)).expanduser()

    @staticmethod
    def _normalize_name(value: str) -> str:
        """Normalize an application name for fuzzy matching."""

        lowered = value.strip().lower()
        if lowered.endswith(".exe"):
            lowered = lowered[:-4]
        return "".join(character for character in lowered if character.isalnum())

    @staticmethod
    def _tokenize(value: str) -> tuple[str, ...]:
        """Split a string into lowercase alphanumeric tokens."""

        lowered = value.strip().lower()
        if lowered.endswith(".exe"):
            lowered = lowered[:-4]
        return tuple(_TOKEN_PATTERN.findall(lowered))

    @staticmethod
    def _acronym(tokens: Iterable[str]) -> str:
        """Build an acronym from a token sequence."""

        return "".join(token[0] for token in tokens if token)

    @staticmethod
    def _dedupe_candidates(candidates: Iterable[_ApplicationCandidate]) -> tuple[_ApplicationCandidate, ...]:
        """Return candidates deduplicated by path while preserving order."""

        seen: dict[str, _ApplicationCandidate] = {}
        for candidate in candidates:
            key = str(candidate.path).lower()
            seen.setdefault(key, candidate)
        return tuple(seen.values())

    @staticmethod
    def _is_launchable_path(path: Path) -> bool:
        """Return whether a path points to a launchable file."""

        return path.exists() and path.is_file() and path.suffix.lower() in _LAUNCHABLE_SUFFIXES

    @staticmethod
    def _clean_registry_path(value: str) -> Path | None:
        """Normalize a registry path field into a filesystem path."""

        if not value:
            return None
        trimmed = value.split(",", 1)[0].strip().strip("\"")
        if not trimmed:
            return None
        return ApplicationResolver._coerce_optional_path(trimmed)

    @staticmethod
    def _query_registry_value(key: Any, name: str) -> str:
        """Read a registry value and return it as a string when available."""

        try:
            value, _value_type = winreg.QueryValueEx(key, name)
        except OSError:
            return ""
        return str(value or "").strip()


__all__ = ["ApplicationResolver"]
