"""Safer Windows application resolution helpers for NARVIS."""

from __future__ import annotations

import json
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
_PROTECTED_DIRECTORY_NAMES = {
    "$recycle.bin",
    "__pycache__",
    "application data",
    "cache",
    "caches",
    "common files",
    "history",
    "logs",
    "modifiableroot",
    "msixvc",
    "node_modules",
    "package cache",
    "packages",
    "system volume information",
    "temp",
    "tmp",
    "vendor",
    "windowsapps",
}
_SYSTEM_DIRECTORY_NAMES = {"system32", "syswow64"}


@dataclass(slots=True, frozen=True)
class _ApplicationCandidate:
    """Represents one launchable application candidate."""

    path: Path
    source: str
    display_labels: tuple[str, ...] = ()
    folder_labels: tuple[str, ...] = ()
    filename_labels: tuple[str, ...] = ()


class ApplicationResolver:
    """Resolve installed Windows applications without relying on brittle aliases."""

    def __init__(
        self,
        *,
        start_menu_roots: Sequence[str | Path] | None = None,
        desktop_roots: Sequence[str | Path] | None = None,
        path_directories: Sequence[str | Path] | None = None,
        program_files_roots: Sequence[str | Path] | None = None,
        windows_apps_root: str | Path | None = None,
        registry_reader: Callable[[], Iterable[Mapping[str, str]]] | None = None,
        app_paths_reader: Callable[[], Iterable[Mapping[str, str]]] | None = None,
        windows_apps_reader: Callable[[], Iterable[Mapping[str, str]]] | None = None,
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
        self.desktop_roots = self._coerce_paths(() if desktop_roots is None else desktop_roots)
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
        self._app_paths_reader = app_paths_reader if app_paths_reader is not None else self._read_app_paths_entries
        self._windows_apps_reader = (
            windows_apps_reader if windows_apps_reader is not None else self._read_windows_apps_entries
        )
        self._shortcut_target_resolver = (
            shortcut_target_resolver if shortcut_target_resolver is not None else self._resolve_shortcut_target
        )
        self._resolved_cache: dict[str, str] = cache if cache is not None else {}
        self._candidate_cache: dict[str, tuple[_ApplicationCandidate, ...]] = {}

    def resolve(self, app_name: str) -> str | None:
        """Resolve an application name to a launchable executable path."""

        normalized_name = self._normalize_name(app_name)
        if not normalized_name:
            return None

        cached = self._resolved_cache.get(normalized_name)
        if cached is not None and self._is_launchable_path(Path(cached)):
            _emit_log(self.logger, "debug", "Resolved application from cache", app_name=app_name, path=cached)
            return cached

        search_plan = (
            ("app_paths", lambda: self._select_candidate(app_name, self._app_paths_candidates(), minimum_score=0.84)),
            ("shortcuts", lambda: self._select_candidate(app_name, self._shortcut_candidates(), minimum_score=0.82)),
            ("windows_apps", lambda: self._select_candidate(app_name, self._windows_apps_candidates(), minimum_score=0.82)),
            ("registry", lambda: self._select_candidate(app_name, self._registry_candidates(), minimum_score=0.78)),
            ("path", lambda: self._select_candidate(app_name, self._path_candidates(), minimum_score=0.96)),
            (
                "program_files",
                lambda: self._resolve_program_files_candidate(
                    app_name,
                    self._program_files_primary_roots(),
                    source="program_files",
                ),
            ),
            (
                "program_files_x86",
                lambda: self._resolve_program_files_candidate(
                    app_name,
                    self._program_files_secondary_roots(),
                    source="program_files_x86",
                ),
            ),
        )

        for source_name, resolver in search_plan:
            candidate = resolver()
            if candidate is None:
                continue
            resolved_path = self._finalize_candidate_path(candidate.path)
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
        """Return application targets discovered from Start Menu shortcuts."""

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
        """Return executable candidates discovered from installed-program registry entries."""

        return tuple(str(candidate.path) for candidate in self._registry_candidates())

    def find_path(self) -> tuple[str, ...]:
        """Return executable candidates discovered from PATH directories."""

        return tuple(str(candidate.path) for candidate in self._path_candidates())

    def find_program_files(self) -> tuple[str, ...]:
        """Return executable candidates discovered from Program Files roots."""

        return tuple(str(candidate.path) for candidate in self._program_files_catalog_candidates())

    def find_windows_apps(self) -> tuple[str, ...]:
        """Return executable candidates discovered from Windows Apps."""

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

    def _app_paths_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached App Paths candidates."""

        return self._cached_candidates("app_paths", self._build_app_paths_candidates)

    def _shortcut_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Start Menu shortcut candidates."""

        return self._cached_candidates("shortcuts", self._build_shortcut_candidates)

    def _windows_apps_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Windows Apps candidates."""

        return self._cached_candidates("windows_apps", self._build_windows_apps_candidates)

    def _registry_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached registry uninstall candidates."""

        return self._cached_candidates("registry", self._build_registry_candidates)

    def _path_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached PATH candidates."""

        return self._cached_candidates("path", self._build_path_candidates)

    def _program_files_catalog_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Program Files catalog candidates."""

        return self._cached_candidates("program_files_catalog", self._build_program_files_catalog_candidates)

    def _build_app_paths_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from the App Paths registry."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._app_paths_reader():
            name = str(entry.get("Name", "") or "").strip()
            friendly_name = str(entry.get("FriendlyAppName", "") or "").strip()
            executable_path = self._clean_registry_path(str(entry.get("Path", "") or ""))
            if executable_path is None or not self._is_launchable_path(executable_path):
                continue
            candidate = self._candidate_from_path(
                executable_path,
                source="app_paths",
                display_labels=(friendly_name, name, executable_path.stem),
                root=executable_path.parent,
            )
            if candidate is not None:
                candidates.append(candidate)
        return self._dedupe_candidates(candidates)

    def _build_shortcut_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Start Menu shortcuts."""

        candidates: list[_ApplicationCandidate] = []
        for root in (*self.start_menu_roots, *self.desktop_roots):
            candidates.extend(self._scan_shortcuts(root, source="start_menu"))
        return self._dedupe_candidates(candidates)

    def _build_windows_apps_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Windows Apps (shell:AppsFolder and aliases)."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._windows_apps_reader():
            display_name = str(entry.get("Name", "") or "").strip()
            executable_path = self._clean_registry_path(str(entry.get("Path", "") or ""))
            if executable_path is None or not self._is_launchable_path(executable_path):
                continue
            candidate = self._candidate_from_path(
                executable_path,
                source="windows_apps",
                display_labels=(display_name,),
                root=executable_path.parent,
            )
            if candidate is not None:
                candidates.append(candidate)

        if candidates:
            return self._dedupe_candidates(candidates)

        root = self.windows_apps_root
        if root is None or not root.exists() or not root.is_dir():
            return ()

        try:
            for child in root.iterdir():
                if not child.is_file() or child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                    continue
                candidate = self._candidate_from_path(child, source="windows_apps", root=root)
                if candidate is not None:
                    candidates.append(candidate)
        except OSError:
            return ()

        return self._dedupe_candidates(candidates)

    def _build_registry_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from installed-program registry entries."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._registry_reader():
            display_name = str(entry.get("DisplayName", "") or "").strip()
            display_icon = str(entry.get("DisplayIcon", "") or "").strip()
            install_location = str(entry.get("InstallLocation", "") or "").strip()

            icon_path = self._clean_registry_path(display_icon)
            if icon_path is not None and self._is_launchable_path(icon_path):
                candidate = self._candidate_from_path(
                    icon_path,
                    source="registry",
                    display_labels=(display_name,),
                    root=icon_path.parent,
                )
                if candidate is not None:
                    candidates.append(candidate)

            install_root = self._coerce_optional_path(install_location)
            if install_root is None or not install_root.exists() or not install_root.is_dir():
                continue
            candidates.extend(
                self._scan_directory_launchers(
                    install_root,
                    source="registry",
                    max_depth=2,
                    display_label=display_name,
                )
            )

        return self._dedupe_candidates(candidates)

    def _build_path_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from PATH directories."""

        candidates: list[_ApplicationCandidate] = []
        for directory in self.path_directories:
            if not directory.exists() or not directory.is_dir():
                continue
            try:
                for child in directory.iterdir():
                    if not child.is_file() or child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                        continue
                    candidate = self._candidate_from_path(child, source="path", root=directory)
                    if candidate is not None:
                        candidates.append(candidate)
            except OSError:
                continue
        return self._dedupe_candidates(candidates)

    def _build_program_files_catalog_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build a cautious catalog of Program Files launchers."""

        candidates: list[_ApplicationCandidate] = []
        roots = self._program_files_primary_roots() + self._program_files_secondary_roots()
        for index, root in enumerate(roots):
            source = "program_files" if index == 0 else "program_files_x86"
            candidates.extend(self._scan_directory_launchers(root, source=source, max_depth=4))
        return self._dedupe_candidates(candidates)

    def _resolve_program_files_candidate(
        self,
        app_name: str,
        roots: tuple[Path, ...],
        *,
        source: str,
    ) -> _ApplicationCandidate | None:
        """Resolve one application by scoring Program Files folders before filenames."""

        if not roots:
            return None

        query_normalized = self._normalize_name(app_name)
        query_tokens = self._tokenize(app_name)
        candidates: list[_ApplicationCandidate] = []

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue

            for current_root, directories, _filenames in os.walk(root, topdown=True, onerror=lambda _error: None):
                current_path = Path(current_root)
                depth = self._relative_depth(root, current_path)
                directories[:] = self._filter_directory_names(directories)
                if depth >= 4:
                    directories[:] = []

                if depth == 0:
                    continue

                folder_labels = self._folder_labels_from_directory(current_path, root=root)
                if self._best_label_score(query_normalized, query_tokens, folder_labels) < 0.55:
                    continue

                try:
                    for child in current_path.iterdir():
                        if not child.is_file() or child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                            continue
                        candidate = self._candidate_from_path(
                            child,
                            source=source,
                            root=root,
                            display_labels=(current_path.name,),
                        )
                        if candidate is not None:
                            candidates.append(candidate)
                except OSError:
                    continue

        return self._select_candidate(app_name, self._dedupe_candidates(candidates), minimum_score=0.72)

    def _scan_shortcuts(self, root: Path, *, source: str) -> list[_ApplicationCandidate]:
        """Scan one shortcut root for launchable shortcut candidates."""

        if not root.exists() or not root.is_dir():
            return []

        candidates: list[_ApplicationCandidate] = []
        for current_root, directories, filenames in os.walk(root, topdown=True, onerror=lambda _error: None):
            current_path = Path(current_root)
            depth = self._relative_depth(root, current_path)
            directories[:] = self._filter_directory_names(directories)
            if depth >= 6:
                directories[:] = []

            for filename in filenames:
                shortcut = current_path / filename
                if shortcut.suffix.lower() != ".lnk":
                    continue
                target = self._shortcut_target_resolver(shortcut)
                target_path = target if target is not None else shortcut
                candidate = self._candidate_from_path(
                    target_path,
                    source=source,
                    display_labels=(shortcut.stem,),
                    root=root,
                )
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _scan_directory_launchers(
        self,
        root: Path,
        *,
        source: str,
        max_depth: int,
        display_label: str = "",
    ) -> list[_ApplicationCandidate]:
        """Scan a directory tree and collect direct launchable files from app folders."""

        if not root.exists() or not root.is_dir():
            return []

        candidates: list[_ApplicationCandidate] = []
        for current_root, directories, _filenames in os.walk(root, topdown=True, onerror=lambda _error: None):
            current_path = Path(current_root)
            depth = self._relative_depth(root, current_path)
            directories[:] = self._filter_directory_names(directories)
            if depth >= max_depth:
                directories[:] = []

            try:
                for child in current_path.iterdir():
                    if not child.is_file() or child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                        continue
                    candidate = self._candidate_from_path(
                        child,
                        source=source,
                        root=root,
                        display_labels=(display_label,),
                    )
                    if candidate is not None:
                        candidates.append(candidate)
            except OSError:
                continue

        return candidates

    def _select_candidate(
        self,
        app_name: str,
        candidates: Iterable[_ApplicationCandidate],
        *,
        minimum_score: float,
    ) -> _ApplicationCandidate | None:
        """Return the highest-scoring candidate above the supplied threshold."""

        best: tuple[float, _ApplicationCandidate] | None = None
        for candidate in candidates:
            score = self._score_candidate(app_name, candidate)
            if score < minimum_score:
                continue
            if best is None or score > best[0]:
                best = (score, candidate)
        return best[1] if best is not None else None

    def _score_candidate(self, app_name: str, candidate: _ApplicationCandidate) -> float:
        """Score one candidate using source-specific weighting."""

        query_normalized = self._normalize_name(app_name)
        query_tokens = self._tokenize(app_name)
        display_score = self._best_label_score(query_normalized, query_tokens, candidate.display_labels)
        folder_score = self._best_label_score(query_normalized, query_tokens, candidate.folder_labels)
        filename_score = self._best_label_score(query_normalized, query_tokens, candidate.filename_labels)

        if self._is_system_path(candidate.path) and not self._is_explicit_system_request(query_normalized, candidate):
            if candidate.source in {"path", "registry", "windows_apps", "program_files", "program_files_x86"}:
                return 0.0

        if not self._candidate_is_viable(candidate, display_score, folder_score, filename_score):
            return 0.0

        if candidate.source == "app_paths":
            return max(display_score, filename_score, folder_score)
        if candidate.source in {"start_menu", "desktop", "windows_apps"}:
            return max(display_score, folder_score, filename_score)
        if candidate.source == "registry":
            return display_score * 0.55 + folder_score * 0.3 + filename_score * 0.15
        if candidate.source == "path":
            return max(filename_score, display_score, folder_score)
        if candidate.source in {"program_files", "program_files_x86"}:
            return folder_score * 0.5 + display_score * 0.35 + filename_score * 0.15
        return max(display_score, folder_score, filename_score)

    def _candidate_is_viable(
        self,
        candidate: _ApplicationCandidate,
        display_score: float,
        folder_score: float,
        filename_score: float,
    ) -> bool:
        """Return whether a candidate has enough signal for its source."""

        if candidate.source == "app_paths":
            return max(display_score, filename_score, folder_score) >= 0.84
        if candidate.source in {"start_menu", "desktop", "windows_apps"}:
            return max(display_score, folder_score, filename_score) >= 0.82
        if candidate.source == "registry":
            return display_score >= 0.68 or max(folder_score, filename_score) >= 0.9
        if candidate.source == "path":
            return filename_score >= 0.96 or max(display_score, folder_score) >= 0.9
        if candidate.source in {"program_files", "program_files_x86"}:
            return max(folder_score, display_score) >= 0.55 and max(folder_score, display_score, filename_score) >= 0.72
        return max(display_score, folder_score, filename_score) >= 0.8

    def _best_label_score(
        self,
        query_normalized: str,
        query_tokens: tuple[str, ...],
        labels: Iterable[str],
    ) -> float:
        """Return the highest score across a label collection."""

        best = 0.0
        for label in labels:
            best = max(best, self._score_label(query_normalized, query_tokens, label))
        return best

    def _score_label(self, query_normalized: str, query_tokens: tuple[str, ...], label: str) -> float:
        """Score how strongly one label matches the query."""

        normalized_label = self._normalize_name(label)
        if not normalized_label:
            return 0.0

        label_tokens = self._tokenize(label)
        query_token_set = set(query_tokens)
        label_token_set = set(label_tokens)

        if normalized_label == query_normalized:
            return 1.0
        if query_tokens and label_tokens and query_tokens == label_tokens:
            return 0.98
        if query_token_set and label_token_set and query_token_set <= label_token_set:
            return 0.9 if len(query_token_set) > 1 else 0.86
        if query_token_set and label_token_set and label_token_set <= query_token_set:
            return 0.84
        if query_normalized in normalized_label and len(query_normalized) >= 4:
            return 0.82
        if normalized_label in query_normalized and len(normalized_label) >= 4:
            return 0.8

        overlap = len(query_token_set & label_token_set)
        if overlap:
            overlap_ratio = overlap / max(len(query_token_set), len(label_token_set))
            return 0.52 + overlap_ratio * 0.28

        label_acronym = self._acronym(label_tokens)
        query_acronym = self._acronym(query_tokens)
        if query_acronym and label_acronym and query_acronym == label_acronym:
            return 0.84

        short_query_prefix = "".join(token for token in query_tokens if len(token) <= 3)
        if short_query_prefix and label_acronym.startswith(short_query_prefix):
            return 0.72

        return 0.0

    def _finalize_candidate_path(self, path: Path) -> Path | None:
        """Convert a candidate path into a launchable executable path."""

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

    def _read_app_paths_entries(self) -> tuple[Mapping[str, str], ...]:
        """Read application paths from the Windows App Paths registry."""

        if self.os_type != "Windows" or winreg is None:
            return ()

        entries: list[dict[str, str]] = []
        registry_locations = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
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
                                    "Name": subkey_name,
                                    "Path": self._query_registry_default_value(subkey),
                                    "FriendlyAppName": self._query_registry_value(subkey, "FriendlyAppName"),
                                }
                                if any(entry.values()):
                                    entries.append(entry)
                        except OSError:
                            continue
            except OSError:
                continue

        return tuple(entries)

    def _read_registry_uninstall_entries(self) -> tuple[Mapping[str, str], ...]:
        """Read installed-program metadata from the Windows uninstall registry."""

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

    def _read_windows_apps_entries(self) -> tuple[Mapping[str, str], ...]:
        """Read app display names and paths from shell:AppsFolder when possible."""

        if self.os_type != "Windows":
            return ()

        script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$folder = $shell.Namespace('shell:AppsFolder'); "
            "$items = foreach ($item in $folder.Items()) { "
            "  $path = ''; "
            "  try { $path = $item.Path } catch { $path = '' }; "
            "  if ($path) { [PSCustomObject]@{ Name = $item.Name; Path = $path } } "
            "}; "
            "$items | ConvertTo-Json -Compress"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception:  # pragma: no cover - depends on host PowerShell availability
            return ()

        payload = result.stdout.strip()
        if not payload:
            return ()

        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return ()

        if isinstance(decoded, dict):
            decoded = [decoded]
        if not isinstance(decoded, list):
            return ()

        entries: list[dict[str, str]] = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name", "") or "").strip()
            path = str(item.get("Path", "") or "").strip()
            if not name and not path:
                continue
            entries.append({"Name": name, "Path": path})
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

    def _candidate_from_path(
        self,
        path: Path,
        *,
        source: str,
        root: Path | None = None,
        display_labels: Iterable[str] = (),
    ) -> _ApplicationCandidate | None:
        """Create a candidate record from a filesystem path."""

        executable_path = self._coerce_optional_path(path)
        if executable_path is None:
            return None

        candidate = _ApplicationCandidate(
            path=executable_path,
            source=source,
            display_labels=self._dedupe_strings(display_labels),
            folder_labels=self._folder_labels_from_path(executable_path, root=root),
            filename_labels=self._dedupe_strings((executable_path.stem, executable_path.name)),
        )
        if not (candidate.display_labels or candidate.folder_labels or candidate.filename_labels):
            return None
        return candidate

    def _folder_labels_from_path(self, path: Path, *, root: Path | None = None) -> tuple[str, ...]:
        """Build folder labels for a candidate path."""

        labels = [path.parent.name]
        if root is not None:
            labels.extend(self._folder_labels_from_directory(path.parent, root=root))
        return self._dedupe_strings(labels)

    def _folder_labels_from_directory(self, directory: Path, *, root: Path) -> tuple[str, ...]:
        """Build searchable labels from a directory relative to a root."""

        labels: list[str] = []
        try:
            relative_parts = directory.relative_to(root).parts
        except ValueError:
            relative_parts = ()

        for part in relative_parts:
            if not part or part == ".":
                continue
            labels.append(part)

        if len(relative_parts) >= 2:
            labels.append(relative_parts[-2])
            labels.append(relative_parts[-1])

        return self._dedupe_strings(labels)

    def _program_files_primary_roots(self) -> tuple[Path, ...]:
        """Return the Program Files roots used before PATH fallback."""

        return self.program_files_roots[:1]

    def _program_files_secondary_roots(self) -> tuple[Path, ...]:
        """Return the Program Files (x86) roots used after Program Files."""

        return self.program_files_roots[1:2]

    def _filter_directory_names(self, directories: list[str]) -> list[str]:
        """Return the subdirectories worth traversing."""

        return [
            name
            for name in directories
            if name.strip().lower() not in _PROTECTED_DIRECTORY_NAMES and not name.startswith(".")
        ]

    def _is_explicit_system_request(self, query_normalized: str, candidate: _ApplicationCandidate) -> bool:
        """Return whether the caller explicitly asked for this system executable."""

        for label in (*candidate.display_labels, *candidate.folder_labels, *candidate.filename_labels):
            if self._normalize_name(label) == query_normalized:
                return True
        return False

    def _is_system_path(self, path: Path) -> bool:
        """Return whether a path points inside the Windows system directories."""

        windows_root = os.getenv("WINDIR")
        if windows_root:
            try:
                normalized = str(path.resolve()).lower()
            except OSError:
                normalized = str(path).lower()
            if normalized.startswith(str(Path(windows_root)).lower()):
                return True
        return any(part.lower() in _SYSTEM_DIRECTORY_NAMES for part in path.parts)

    @staticmethod
    def _relative_depth(root: Path, current_path: Path) -> int:
        """Return the depth of a path relative to a root."""

        return len(current_path.parts) - len(root.parts)

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
    def _default_path_directories() -> tuple[Path, ...]:
        """Return PATH directories as candidate search roots."""

        raw_path = os.getenv("PATH", "")
        return tuple(Path(entry) for entry in raw_path.split(os.pathsep) if entry.strip())

    @staticmethod
    def _default_program_files_roots() -> tuple[Path, ...]:
        """Return Program Files roots in lookup order."""

        roots = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
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
        """Normalize an application name for matching."""

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
    def _dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
        """Return normalized string values in insertion order without duplicates."""

        seen: set[str] = set()
        results: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(text)
        return tuple(results)

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
    def _query_registry_default_value(key: Any) -> str:
        """Read an unnamed registry value and return it as a string."""

        try:
            value, _value_type = winreg.QueryValueEx(key, "")
        except OSError:
            try:
                value = winreg.QueryValue(key, None)
            except OSError:
                return ""
        return str(value or "").strip()

    @staticmethod
    def _query_registry_value(key: Any, name: str) -> str:
        """Read a registry value and return it as a string when available."""

        try:
            value, _value_type = winreg.QueryValueEx(key, name)
        except OSError:
            return ""
        return str(value or "").strip()


__all__ = ["ApplicationResolver"]
