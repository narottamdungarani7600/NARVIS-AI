"""Universal Windows application resolution helpers for NARVIS."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
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
_NOISE_LABEL_FRAGMENTS = (
    "uninstall",
    "unins",
    "readme",
    "manual",
    "guide",
    "help",
    "options",
    "repair",
    "setup",
    "update",
)


@dataclass(slots=True, frozen=True)
class _ApplicationQuery:
    """Normalized representation of one requested application name."""

    raw: str
    normalized: str
    tokens: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class _ApplicationCandidate:
    """Represents one launchable application candidate."""

    source: str
    launch_kind: str
    launch_target: str
    path: Path | None = None
    display_labels: tuple[str, ...] = ()
    folder_labels: tuple[str, ...] = ()
    filename_labels: tuple[str, ...] = ()


MetadataReader = Callable[[Path], Mapping[str, str] | Iterable[str] | None]


class ApplicationResolver:
    """Resolve installed Windows applications without relying on hardcoded aliases."""

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
        windows_aliases_reader: Callable[[], Iterable[Mapping[str, str]]] | None = None,
        windows_apps_reader: Callable[[], Iterable[Mapping[str, str]]] | None = None,
        shortcut_target_resolver: Callable[[Path], Path | None] | None = None,
        metadata_reader: MetadataReader | None = None,
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
        self._app_paths_reader = app_paths_reader if app_paths_reader is not None else self._read_app_paths_entries
        self._windows_aliases_reader = (
            windows_aliases_reader if windows_aliases_reader is not None else self._read_windows_alias_entries
        )
        self._windows_apps_reader = windows_apps_reader if windows_apps_reader is not None else self._read_store_app_entries
        self._shortcut_target_resolver = (
            shortcut_target_resolver if shortcut_target_resolver is not None else self._resolve_shortcut_target
        )
        self._metadata_reader = metadata_reader if metadata_reader is not None else self._read_file_metadata
        self._resolved_cache: dict[str, str] = cache if cache is not None else {}
        self._candidate_cache: dict[str, tuple[_ApplicationCandidate, ...]] = {}
        self._metadata_cache: dict[str, tuple[str, ...]] = {}

    def resolve(self, app_name: str) -> str | None:
        """Resolve an application name into a Windows launch target."""

        query = self._build_query(app_name)
        if not query.normalized:
            return None

        cached = self._resolved_cache.get(query.normalized)
        if cached:
            return cached

        candidate = self._resolve_candidate(query)
        if candidate is None:
            _emit_log(self.logger, "warning", "Unable to resolve application", app_name=app_name)
            return None

        resolved = self._candidate_descriptor(candidate)
        self._resolved_cache[query.normalized] = resolved
        _emit_log(
            self.logger,
            "info",
            "Resolved application",
            app_name=app_name,
            path=resolved,
            source=candidate.source,
        )
        return resolved

    def find_shortcuts(self) -> tuple[str, ...]:
        """Return launch targets discovered from Start Menu and Desktop shortcuts."""

        return self._descriptors(self._start_menu_candidates() + self._desktop_candidates())

    def find_registry(self) -> tuple[str, ...]:
        """Return launch targets discovered from installed-program registry entries."""

        return self._descriptors(self._registry_candidates())

    def find_path(self) -> tuple[str, ...]:
        """Return launch targets discovered from PATH directories."""

        return self._descriptors(self._path_candidates())

    def find_program_files(self) -> tuple[str, ...]:
        """Return launch targets discovered from Program Files roots."""

        return self._descriptors(self._program_files_candidates() + self._program_files_x86_candidates())

    def find_windows_apps(self) -> tuple[str, ...]:
        """Return launch targets discovered from Windows aliases and Store apps."""

        return self._descriptors(self._execution_alias_candidates() + self._store_app_candidates())

    def launch(self, app_name: str) -> bool:
        """Resolve and launch an application by name."""

        query = self._build_query(app_name)
        if not query.normalized:
            return False

        candidate = self._resolve_candidate(query)
        if candidate is None:
            _emit_log(self.logger, "warning", "Unable to resolve application", app_name=app_name)
            return False

        descriptor = self._candidate_descriptor(candidate)
        self._resolved_cache[query.normalized] = descriptor

        try:
            self._launch_candidate(candidate, descriptor)
            _emit_log(self.logger, "info", "Launched resolved application", app_name=app_name, path=descriptor)
            return True
        except Exception as error:
            _emit_log(self.logger, "warning", "Failed to launch resolved application", app_name=app_name, error=str(error))
            return False

    def launch_path(self, app_path: str | Path, args: Sequence[str] | None = None) -> bool:
        """Launch one concrete application path using the Windows-safe process strategy."""

        candidate_path = self._coerce_optional_path(app_path)
        if candidate_path is None:
            return False

        descriptor = str(candidate_path)
        arguments = [str(argument) for argument in tuple(args or ())]
        try:
            self._launch_path_command(descriptor, path=candidate_path, args=arguments)
            _emit_log(self.logger, "info", "Launched application path", path=descriptor, args=arguments)
            return True
        except Exception as error:
            _emit_log(self.logger, "warning", "Failed to launch application path", path=descriptor, error=str(error))
            return False

    def _resolve_candidate(self, query: _ApplicationQuery) -> _ApplicationCandidate | None:
        """Resolve one application query into a concrete candidate."""

        groups = self._candidate_groups()
        exact = self._match_exact(query, groups)
        if exact is not None:
            return exact

        structured = self._match_structured(query, groups)
        if structured is not None:
            return structured

        metadata = self._match_metadata(query, groups)
        if metadata is not None:
            return metadata

        return self._match_fuzzy(query, groups)

    def _candidate_groups(self) -> tuple[tuple[str, tuple[_ApplicationCandidate, ...]], ...]:
        """Return all source groups in the required priority order."""

        return (
            ("app_paths", self._app_paths_candidates()),
            ("execution_aliases", self._execution_alias_candidates()),
            ("store_apps", self._store_app_candidates()),
            ("start_menu", self._start_menu_candidates()),
            ("desktop", self._desktop_candidates()),
            ("registry", self._registry_candidates()),
            ("path", self._path_candidates()),
            ("program_files", self._program_files_candidates()),
            ("program_files_x86", self._program_files_x86_candidates()),
        )

    def _launch_candidate(self, candidate: _ApplicationCandidate, descriptor: str) -> None:
        """Launch one resolved candidate using the correct Windows shell strategy."""

        if candidate.launch_kind == "appsfolder":
            subprocess.Popen(["explorer.exe", candidate.launch_target])
            return
        if candidate.launch_kind == "shortcut":
            if hasattr(os, "startfile"):
                os.startfile(candidate.launch_target)  # type: ignore[attr-defined]
            else:  # pragma: no cover - Windows-specific fallback
                subprocess.Popen(candidate.launch_target)
            return
        self._launch_path_command(descriptor, path=candidate.path)

    def _launch_path_command(self, descriptor: str, *, path: Path | None, args: Sequence[str] = ()) -> None:
        """Launch one executable descriptor with Windows console isolation when required."""

        command = [descriptor, *[str(argument) for argument in args]]
        popen_kwargs = self._popen_kwargs_for_path(path)
        subprocess.Popen(command, **popen_kwargs)

    def _popen_kwargs_for_path(self, path: Path | None) -> dict[str, Any]:
        """Return ``Popen`` keyword arguments for one concrete path launch."""

        if self.os_type != "Windows" or path is None or not self._is_console_process_path(path):
            return {}

        creationflags = (
            getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        if creationflags == 0:
            return {}
        return {"creationflags": creationflags}

    def _is_console_process_path(self, path: Path) -> bool:
        """Return whether a path should launch in its own console window."""

        suffix = path.suffix.lower()
        if suffix in {".bat", ".cmd", ".com"}:
            return True
        if suffix != ".exe":
            return False
        return self._read_pe_subsystem(path) == 3

    def _read_pe_subsystem(self, path: Path) -> int | None:
        """Read the PE subsystem value for one executable when available."""

        try:
            with path.open("rb") as handle:
                header = handle.read(64)
                if len(header) < 64 or header[:2] != b"MZ":
                    return None

                pe_offset = int.from_bytes(header[60:64], "little")
                handle.seek(pe_offset)
                if handle.read(4) != b"PE\x00\x00":
                    return None

                handle.seek(20, os.SEEK_CUR)
                optional_header = handle.read(70)
                if len(optional_header) < 70:
                    return None

                magic = int.from_bytes(optional_header[0:2], "little")
                if magic not in {0x10B, 0x20B}:
                    return None

                return int.from_bytes(optional_header[68:70], "little")
        except OSError:
            return None

    def _match_exact(
        self,
        query: _ApplicationQuery,
        groups: tuple[tuple[str, tuple[_ApplicationCandidate, ...]], ...],
    ) -> _ApplicationCandidate | None:
        """Return the first exact label match across the source priority order."""

        for _source_name, candidates in groups:
            for candidate in candidates:
                if self._is_system_candidate(candidate) and candidate.source not in {"path", "execution_aliases"}:
                    continue
                if any(label == query.normalized for label in self._exact_labels(candidate)):
                    return candidate
        return None

    def _match_structured(
        self,
        query: _ApplicationQuery,
        groups: tuple[tuple[str, tuple[_ApplicationCandidate, ...]], ...],
    ) -> _ApplicationCandidate | None:
        """Return the highest-confidence structured match by source priority."""

        thresholds = {
            "app_paths": 0.84,
            "execution_aliases": 0.94,
            "store_apps": 0.84,
            "start_menu": 0.84,
            "desktop": 0.84,
            "registry": 0.82,
            "path": 0.98,
            "program_files": 0.82,
            "program_files_x86": 0.82,
        }

        for source_name, candidates in groups:
            best: tuple[float, _ApplicationCandidate] | None = None
            for candidate in candidates:
                score = self._structured_score(query, candidate)
                if score < thresholds[source_name]:
                    continue
                if best is None or score > best[0]:
                    best = (score, candidate)
            if best is not None:
                return best[1]
        return None

    def _match_metadata(
        self,
        query: _ApplicationQuery,
        groups: tuple[tuple[str, tuple[_ApplicationCandidate, ...]], ...],
    ) -> _ApplicationCandidate | None:
        """Return a match based on ProductName or FileDescription metadata."""

        metadata_sources = {"registry", "path", "program_files", "program_files_x86"}
        for source_name, candidates in groups:
            if source_name not in metadata_sources:
                continue

            best: tuple[float, _ApplicationCandidate] | None = None
            for candidate in candidates:
                if not self._metadata_prefilter(query, candidate):
                    continue
                labels = self._metadata_labels(candidate)
                if not labels:
                    continue
                score = self._best_label_score(query, labels)
                if score < 0.84:
                    continue
                if best is None or score > best[0]:
                    best = (score, candidate)
            if best is not None:
                return best[1]
        return None

    def _match_fuzzy(
        self,
        query: _ApplicationQuery,
        groups: tuple[tuple[str, tuple[_ApplicationCandidate, ...]], ...],
    ) -> _ApplicationCandidate | None:
        """Return a final guarded fuzzy match across all sources."""

        if len(query.normalized) < 4:
            return None

        source_weight = {
            "app_paths": 1.0,
            "execution_aliases": 0.99,
            "store_apps": 0.98,
            "start_menu": 0.97,
            "desktop": 0.96,
            "registry": 0.95,
            "path": 0.93,
            "program_files": 0.92,
            "program_files_x86": 0.91,
        }

        best: tuple[float, _ApplicationCandidate] | None = None
        for source_name, candidates in groups:
            for candidate in candidates:
                score = self._fuzzy_score(query, candidate) * source_weight[source_name]
                threshold = 0.93 if len(query.tokens) <= 1 else 0.9
                if score < threshold:
                    continue
                if best is None or score > best[0]:
                    best = (score, candidate)
        return best[1] if best is not None else None

    def _app_paths_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached App Paths candidates."""

        return self._cached_candidates("app_paths", self._build_app_paths_candidates)

    def _execution_alias_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Windows App Execution Alias candidates."""

        return self._cached_candidates("execution_aliases", self._build_execution_alias_candidates)

    def _store_app_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Microsoft Store app candidates."""

        return self._cached_candidates("store_apps", self._build_store_app_candidates)

    def _start_menu_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Start Menu shortcut candidates."""

        return self._cached_candidates("start_menu", self._build_start_menu_candidates)

    def _desktop_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Desktop shortcut candidates."""

        return self._cached_candidates("desktop", self._build_desktop_candidates)

    def _registry_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached registry uninstall candidates."""

        return self._cached_candidates("registry", self._build_registry_candidates)

    def _path_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached PATH candidates."""

        return self._cached_candidates("path", self._build_path_candidates)

    def _program_files_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Program Files candidates."""

        return self._cached_candidates("program_files", self._build_program_files_candidates)

    def _program_files_x86_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Return cached Program Files (x86) candidates."""

        return self._cached_candidates("program_files_x86", self._build_program_files_x86_candidates)

    def _build_app_paths_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from the App Paths registry."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._app_paths_reader():
            registry_name = str(entry.get("Name", "") or "").strip()
            executable_path = self._clean_registry_path(str(entry.get("Path", "") or ""))
            if executable_path is None or not self._is_launchable_path(executable_path):
                continue
            candidate = self._candidate_from_path(
                executable_path,
                source="app_paths",
                display_labels=(
                    str(entry.get("FriendlyAppName", "") or "").strip(),
                    self._stem_value(registry_name),
                ),
                root=executable_path.parent,
            )
            if candidate is not None:
                candidates.append(candidate)
        return self._dedupe_candidates(candidates)

    def _build_execution_alias_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Windows App Execution Aliases."""

        candidates: list[_ApplicationCandidate] = []
        entries = tuple(self._windows_aliases_reader())
        if entries:
            for entry in entries:
                candidate = self._alias_candidate_from_entry(entry)
                if candidate is not None:
                    candidates.append(candidate)
            return self._dedupe_candidates(candidates)

        root = self.windows_apps_root
        if root is None or not root.exists() or not root.is_dir():
            return ()

        try:
            for child in root.iterdir():
                if child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                    continue
                candidate = self._candidate_from_path(
                    child,
                    source="execution_aliases",
                    display_labels=(child.stem,),
                    root=root,
                    allow_missing=True,
                )
                if candidate is not None:
                    candidates.append(candidate)
        except OSError:
            return ()

        return self._dedupe_candidates(candidates)

    def _build_store_app_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Microsoft Store apps exposed through AppsFolder."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._windows_apps_reader():
            candidate = self._store_app_candidate_from_entry(entry)
            if candidate is not None:
                candidates.append(candidate)
        return self._dedupe_candidates(candidates)

    def _build_start_menu_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Start Menu shortcuts."""

        candidates: list[_ApplicationCandidate] = []
        for root in self.start_menu_roots:
            candidates.extend(self._scan_shortcuts(root, source="start_menu"))
        return self._dedupe_candidates(candidates)

    def _build_desktop_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Desktop shortcuts."""

        candidates: list[_ApplicationCandidate] = []
        for root in self.desktop_roots:
            candidates.extend(self._scan_shortcuts(root, source="desktop"))
        return self._dedupe_candidates(candidates)

    def _build_registry_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from installed-program registry entries."""

        candidates: list[_ApplicationCandidate] = []
        for entry in self._registry_reader():
            display_name = str(entry.get("DisplayName", "") or "").strip()
            display_icon = self._clean_registry_path(str(entry.get("DisplayIcon", "") or ""))
            install_root = self._coerce_optional_path(str(entry.get("InstallLocation", "") or ""))

            if display_icon is not None and self._is_launchable_path(display_icon):
                candidate = self._candidate_from_path(
                    display_icon,
                    source="registry",
                    display_labels=(display_name,),
                    root=display_icon.parent,
                )
                if candidate is not None:
                    candidates.append(candidate)

            if install_root is not None and install_root.exists() and install_root.is_dir():
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
            if self._is_protected_directory(directory.name):
                continue
            try:
                for child in directory.iterdir():
                    if child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                        continue
                    candidate = self._candidate_from_path(
                        child,
                        source="path",
                        root=directory,
                        allow_missing=True,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
            except OSError:
                continue
        return self._dedupe_candidates(candidates)

    def _build_program_files_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Program Files."""

        roots = self.program_files_roots[:1]
        return self._dedupe_candidates(self._scan_program_files_roots(roots, source="program_files"))

    def _build_program_files_x86_candidates(self) -> tuple[_ApplicationCandidate, ...]:
        """Build candidates from Program Files (x86)."""

        roots = self.program_files_roots[1:2]
        return self._dedupe_candidates(self._scan_program_files_roots(roots, source="program_files_x86"))

    def _scan_program_files_roots(
        self,
        roots: Sequence[Path],
        *,
        source: str,
    ) -> list[_ApplicationCandidate]:
        """Scan Program Files-style roots for candidate launchers."""

        candidates: list[_ApplicationCandidate] = []
        for root in roots:
            candidates.extend(self._scan_directory_launchers(root, source=source, max_depth=4))
        return candidates

    def _scan_shortcuts(self, root: Path, *, source: str) -> list[_ApplicationCandidate]:
        """Scan one shortcut root for launchable shortcuts."""

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
                candidate = self._shortcut_candidate(
                    shortcut,
                    source=source,
                    root=root,
                    target=target,
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
        """Scan one directory tree and collect plausible launchers."""

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
                    if child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                        continue
                    candidate = self._candidate_from_path(
                        child,
                        source=source,
                        display_labels=(display_label,),
                        root=root,
                        allow_missing=True,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
            except OSError:
                continue
        return candidates

    def _candidate_from_path(
        self,
        path: str | Path,
        *,
        source: str,
        display_labels: Iterable[str] = (),
        root: Path | None = None,
        allow_missing: bool = False,
    ) -> _ApplicationCandidate | None:
        """Create a file-backed candidate from a filesystem path."""

        candidate_path = self._coerce_optional_path(path)
        if candidate_path is None:
            return None

        if not allow_missing and not self._is_launchable_path(candidate_path):
            return None

        candidate = _ApplicationCandidate(
            source=source,
            launch_kind="path",
            launch_target=str(candidate_path),
            path=candidate_path,
            display_labels=self._dedupe_strings(display_labels),
            folder_labels=self._folder_labels_from_path(candidate_path, root=root),
            filename_labels=self._dedupe_strings((candidate_path.stem, candidate_path.name)),
        )
        return None if self._should_ignore_candidate(candidate) else candidate

    def _shortcut_candidate(
        self,
        shortcut: Path,
        *,
        source: str,
        root: Path | None = None,
        target: Path | None = None,
    ) -> _ApplicationCandidate | None:
        """Create a shortcut-backed candidate while preserving its target metadata."""

        target_path = target if target is not None and self._is_launchable_path(target) else None
        shortcut_labels = self._folder_labels_from_path(shortcut, root=root)
        target_labels = self._folder_labels_from_path(target_path, root=target_path.parent) if target_path is not None else ()

        candidate = _ApplicationCandidate(
            source=source,
            launch_kind="shortcut",
            launch_target=str(shortcut),
            path=target_path,
            display_labels=(shortcut.stem,),
            folder_labels=self._dedupe_strings((*shortcut_labels, *target_labels)),
            filename_labels=(shortcut.stem, shortcut.name),
        )
        return None if self._should_ignore_candidate(candidate) else candidate

    def _alias_candidate_from_entry(self, entry: Mapping[str, str]) -> _ApplicationCandidate | None:
        """Create an execution-alias candidate from an injected entry."""

        name = str(entry.get("Name", "") or "").strip()
        raw_path = str(entry.get("Path", "") or "").strip()
        if not name and not raw_path:
            return None

        candidate_path = self._coerce_optional_path(raw_path or name)
        if candidate_path is not None and candidate_path.suffix.lower() in _LAUNCHABLE_SUFFIXES:
            candidate = self._candidate_from_path(
                candidate_path,
                source="execution_aliases",
                display_labels=(self._stem_value(name),),
                root=self.windows_apps_root,
                allow_missing=True,
            )
            if candidate is not None:
                return candidate

        alias_name = self._stem_value(name or raw_path)
        if not alias_name:
            return None
        candidate = _ApplicationCandidate(
            source="execution_aliases",
            launch_kind="path",
            launch_target=alias_name,
            path=Path(alias_name),
            display_labels=(alias_name,),
            folder_labels=(),
            filename_labels=(alias_name, f"{alias_name}.exe"),
        )
        return None if self._should_ignore_candidate(candidate) else candidate

    def _store_app_candidate_from_entry(self, entry: Mapping[str, str]) -> _ApplicationCandidate | None:
        """Create a Store-app candidate from one AppsFolder entry."""

        display_name = str(entry.get("Name", "") or "").strip()
        app_id = str(entry.get("AppUserModelID", "") or "").strip()
        raw_path = str(entry.get("Path", "") or "").strip()
        app_identifier = app_id or raw_path

        # ``shell:AppsFolder`` enumerates both packaged Store apps and traditional
        # desktop bridges. Only packaged apps belong in the Store-app priority tier.
        is_packaged_app = "!" in app_identifier
        if not display_name or not app_identifier or not is_packaged_app:
            return None

        candidate = _ApplicationCandidate(
            source="store_apps",
            launch_kind="appsfolder",
            launch_target=f"shell:AppsFolder\\{app_identifier}",
            path=None,
            display_labels=(display_name,),
            folder_labels=(),
            filename_labels=(),
        )
        return None if self._should_ignore_candidate(candidate) else candidate

    def _candidate_descriptor(self, candidate: _ApplicationCandidate) -> str:
        """Return the string launch descriptor for a candidate."""

        if candidate.launch_kind == "shortcut" and candidate.path is not None:
            return str(candidate.path)
        return candidate.launch_target

    def _descriptors(self, candidates: Iterable[_ApplicationCandidate]) -> tuple[str, ...]:
        """Return deduplicated descriptors for one candidate collection."""

        seen: set[str] = set()
        results: list[str] = []
        for candidate in candidates:
            descriptor = self._candidate_descriptor(candidate)
            if not descriptor or descriptor.lower() in seen:
                continue
            seen.add(descriptor.lower())
            results.append(descriptor)
        return tuple(results)

    def _exact_labels(self, candidate: _ApplicationCandidate) -> tuple[str, ...]:
        """Return exact-match labels for one candidate."""

        labels: list[str] = []
        labels.extend(candidate.filename_labels)

        if candidate.source in {"app_paths", "store_apps", "start_menu", "desktop", "registry"}:
            labels.extend(candidate.display_labels)
        if candidate.source in {"app_paths", "program_files", "program_files_x86"}:
            labels.extend(candidate.folder_labels)

        normalized = []
        seen: set[str] = set()
        for label in labels:
            normalized_label = self._normalize_name(label)
            if not normalized_label or normalized_label in seen:
                continue
            seen.add(normalized_label)
            normalized.append(normalized_label)
        return tuple(normalized)

    def _structured_score(self, query: _ApplicationQuery, candidate: _ApplicationCandidate) -> float:
        """Score one candidate using source-aware structured matching."""

        if self._is_system_candidate(candidate) and candidate.source not in {"path", "execution_aliases"}:
            return 0.0

        display_score = self._best_label_score(query, candidate.display_labels)
        folder_score = self._best_label_score(query, candidate.folder_labels)
        filename_score = self._best_label_score(query, candidate.filename_labels)

        if candidate.source == "app_paths":
            return max(filename_score, display_score, folder_score)
        if candidate.source == "execution_aliases":
            return max(filename_score, display_score)
        if candidate.source == "store_apps":
            return max(display_score, filename_score)
        if candidate.source in {"start_menu", "desktop"}:
            return max(display_score, folder_score, filename_score * 0.98)
        if candidate.source == "registry":
            return display_score * 0.55 + folder_score * 0.25 + filename_score * 0.2
        if candidate.source == "path":
            return filename_score
        if candidate.source in {"program_files", "program_files_x86"}:
            return folder_score * 0.45 + display_score * 0.3 + filename_score * 0.25
        return max(display_score, folder_score, filename_score)

    def _best_label_score(self, query: _ApplicationQuery, labels: Iterable[str]) -> float:
        """Return the best structured score across one label collection."""

        best = 0.0
        for label in labels:
            best = max(best, self._structured_label_score(query, label))
        return best

    def _structured_label_score(self, query: _ApplicationQuery, label: str) -> float:
        """Return a conservative structured score for one label."""

        normalized_label = self._normalize_name(label)
        if not normalized_label:
            return 0.0

        if normalized_label == query.normalized:
            return 1.0

        label_tokens = self._tokenize(label)
        if query.tokens and label_tokens:
            if query.tokens == label_tokens:
                return 0.98
            coverage = self._token_sequence_coverage(query.tokens, label_tokens)
            if coverage > 0.0:
                return coverage

        if len(query.normalized) >= 4:
            if normalized_label.startswith(query.normalized):
                return 0.92
            if query.normalized.startswith(normalized_label):
                return 0.9 if len(normalized_label) >= 4 else 0.0
            if query.normalized in normalized_label:
                return 0.88
            if normalized_label in query.normalized:
                return 0.84

        overlap = len(set(query.tokens) & set(label_tokens))
        if overlap >= 2:
            return 0.8
        return 0.0

    def _token_sequence_coverage(self, query_tokens: tuple[str, ...], label_tokens: tuple[str, ...]) -> float:
        """Return a structured token-coverage score for one query/label pair."""

        if not query_tokens or not label_tokens:
            return 0.0

        query_index = 0
        label_index = 0
        matched_units = 0

        while query_index < len(query_tokens) and label_index < len(label_tokens):
            query_token = query_tokens[query_index]
            label_token = label_tokens[label_index]

            if label_token == query_token or label_token.startswith(query_token):
                matched_units += 1
                query_index += 1
                label_index += 1
                continue

            if len(query_token) >= 2:
                acronym = ""
                matched = False
                for end_index in range(label_index, min(len(label_tokens), label_index + 4)):
                    acronym += label_tokens[end_index][0]
                    if acronym == query_token and end_index > label_index:
                        matched_units += end_index - label_index + 1
                        query_index += 1
                        label_index = end_index + 1
                        matched = True
                        break
                if matched:
                    continue

            label_index += 1

        if query_index != len(query_tokens):
            return 0.0

        coverage = matched_units / max(len(label_tokens), len(query_tokens))
        if coverage >= 1.0:
            return 0.95
        if coverage >= 0.75:
            return 0.9
        if coverage >= 0.5:
            return 0.84
        return 0.0

    def _metadata_prefilter(self, query: _ApplicationQuery, candidate: _ApplicationCandidate) -> bool:
        """Return whether metadata lookup is worth attempting for one candidate."""

        if candidate.path is None or candidate.path.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
            return False

        for label in (*candidate.filename_labels, *candidate.folder_labels, *candidate.display_labels):
            normalized_label = self._normalize_name(label)
            if not normalized_label:
                continue
            if query.normalized.startswith(normalized_label) or normalized_label.startswith(query.normalized):
                return True
            if len(query.normalized) >= 4 and normalized_label in query.normalized:
                return True
            if self._structured_label_score(query, label) >= 0.72:
                return True
        return False

    def _metadata_labels(self, candidate: _ApplicationCandidate) -> tuple[str, ...]:
        """Return cached ProductName/FileDescription labels for one candidate."""

        if candidate.path is None:
            return ()

        cache_key = str(candidate.path).lower()
        cached = self._metadata_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            payload = self._metadata_reader(candidate.path)
        except Exception:
            payload = None

        labels: list[str] = []
        if isinstance(payload, Mapping):
            labels.extend(str(value or "").strip() for value in payload.values())
        elif payload is not None:
            labels.extend(str(value or "").strip() for value in payload)

        deduped = self._dedupe_strings(labels)
        self._metadata_cache[cache_key] = deduped
        return deduped

    def _fuzzy_score(self, query: _ApplicationQuery, candidate: _ApplicationCandidate) -> float:
        """Return a guarded fuzzy score for a candidate."""

        if self._is_system_candidate(candidate):
            return 0.0

        labels = (*candidate.display_labels, *candidate.folder_labels, *candidate.filename_labels)
        best = 0.0
        for label in labels:
            normalized_label = self._normalize_name(label)
            if not normalized_label or len(normalized_label) < 4:
                continue
            ratio = SequenceMatcher(None, query.normalized, normalized_label).ratio()
            if query.normalized in normalized_label or normalized_label in query.normalized:
                ratio = max(ratio, 0.9)
            best = max(best, ratio)
        return best

    def _should_ignore_candidate(self, candidate: _ApplicationCandidate) -> bool:
        """Return whether one candidate looks like non-application noise."""

        labels = " ".join((*candidate.display_labels, *candidate.filename_labels)).lower()
        return any(fragment in labels for fragment in _NOISE_LABEL_FRAGMENTS)

    def _is_system_candidate(self, candidate: _ApplicationCandidate) -> bool:
        """Return whether one candidate points into Windows system directories."""

        if candidate.path is None:
            return False
        return self._is_system_path(candidate.path)

    def _is_system_path(self, path: Path) -> bool:
        """Return whether a path points into Windows system executable directories."""

        return any(part.lower() in _SYSTEM_DIRECTORY_NAMES for part in path.parts)

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

    def _resolve_shortcut_target(self, shortcut_path: Path) -> Path | None:
        """Resolve a Windows shortcut target path when possible."""

        if self.os_type != "Windows":
            return None

        quoted_path = self._powershell_quote(str(shortcut_path))
        script = (
            f"$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut({quoted_path}); "
            "if ($shortcut.TargetPath) { Write-Output $shortcut.TargetPath }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except Exception:  # pragma: no cover - depends on host PowerShell availability
            return None

        target = result.stdout.strip()
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

    def _read_windows_alias_entries(self) -> tuple[Mapping[str, str], ...]:
        """Read Windows App Execution Aliases from the WindowsApps directory."""

        root = self.windows_apps_root
        if self.os_type != "Windows" or root is None or not root.exists() or not root.is_dir():
            return ()

        entries: list[dict[str, str]] = []
        try:
            for child in root.iterdir():
                if child.suffix.lower() not in _LAUNCHABLE_SUFFIXES:
                    continue
                entries.append({"Name": child.name, "Path": str(child)})
        except OSError:
            return ()
        return tuple(entries)

    def _read_store_app_entries(self) -> tuple[Mapping[str, str], ...]:
        """Read Microsoft Store app entries from shell:AppsFolder."""

        if self.os_type != "Windows":
            return ()

        script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$folder = $shell.Namespace('shell:AppsFolder'); "
            "$items = foreach ($item in $folder.Items()) { "
            "  $path = ''; "
            "  try { $path = $item.Path } catch { $path = '' }; "
            "  $appId = ''; "
            "  try { $appId = $item.ExtendedProperty('System.AppUserModel.ID') } catch { $appId = '' }; "
            "  [PSCustomObject]@{ Name = $item.Name; Path = $path; AppUserModelID = $appId } "
            "}; "
            "$items | ConvertTo-Json -Compress"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
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
            app_id = str(item.get("AppUserModelID", "") or "").strip()
            if not name and not path and not app_id:
                continue
            entries.append({"Name": name, "Path": path, "AppUserModelID": app_id})
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

    def _read_file_metadata(self, path: Path) -> Mapping[str, str] | None:
        """Read ProductName/FileDescription metadata for one executable."""

        if self.os_type != "Windows":
            return None

        quoted_path = self._powershell_quote(str(path))
        script = (
            f"$info = (Get-Item -LiteralPath {quoted_path}).VersionInfo; "
            "[PSCustomObject]@{ "
            "ProductName = $info.ProductName; "
            "FileDescription = $info.FileDescription; "
            "OriginalFilename = $info.OriginalFilename "
            "} | ConvertTo-Json -Compress"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except Exception:  # pragma: no cover - depends on host PowerShell availability
            return None

        payload = result.stdout.strip()
        if not payload:
            return None

        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None

    @staticmethod
    def _build_query(value: str) -> _ApplicationQuery:
        """Build a normalized application query."""

        return _ApplicationQuery(
            raw=value,
            normalized=ApplicationResolver._normalize_name(value),
            tokens=ApplicationResolver._tokenize(value),
        )

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
    def _dedupe_candidates(candidates: Iterable[_ApplicationCandidate]) -> tuple[_ApplicationCandidate, ...]:
        """Return candidates deduplicated by source and launch target."""

        seen: dict[tuple[str, str], _ApplicationCandidate] = {}
        for candidate in candidates:
            key = (candidate.source, candidate.launch_target.lower())
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
    def _stem_value(value: str) -> str:
        """Return a filename stem when the value looks like one."""

        text = str(value or "").strip()
        if not text:
            return ""
        return Path(text).stem

    @staticmethod
    def _looks_like_filesystem_path(value: str) -> bool:
        """Return whether a string looks like a concrete filesystem path."""

        text = str(value or "").strip()
        return bool(text) and (":" in text or text.startswith("\\"))

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
    def _powershell_quote(value: str) -> str:
        """Return a single-quoted PowerShell string literal."""

        return "'" + str(value).replace("'", "''") + "'"

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

    @staticmethod
    def _is_protected_directory(name: str) -> bool:
        """Return whether a directory should be skipped during scans."""

        return name.strip().lower() in _PROTECTED_DIRECTORY_NAMES

    @staticmethod
    def _filter_directory_names(directories: list[str]) -> list[str]:
        """Return the subdirectories worth traversing."""

        return [
            name
            for name in directories
            if name and not name.startswith(".") and not ApplicationResolver._is_protected_directory(name)
        ]

    @staticmethod
    def _folder_labels_from_path(path: Path, *, root: Path | None = None) -> tuple[str, ...]:
        """Build searchable folder labels for one path."""

        labels = [path.parent.name]
        if root is not None:
            try:
                relative_parts = path.parent.relative_to(root).parts
            except ValueError:
                relative_parts = ()
            labels.extend(part for part in relative_parts if part and part != ".")
            if len(relative_parts) >= 2:
                labels.append(relative_parts[-2])
                labels.append(relative_parts[-1])
        return ApplicationResolver._dedupe_strings(labels)


__all__ = ["ApplicationResolver"]
