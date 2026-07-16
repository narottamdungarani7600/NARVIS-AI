"""Immutable deterministic runtime version and metadata catalogue.

The catalogue describes retained architecture metadata only.  It never reads
the repository, resolves services, invokes providers or AI models, probes the
host, uses networking, or enters Trusted Execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any

from .runtime_config import (
    RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION,
    RUNTIME_CONFIGURATION_SCHEMA_VERSION,
    RUNTIME_CONFIGURATION_VERSION,
)


RUNTIME_METADATA_CATALOG_VERSION = "1.5.5"
RUNTIME_METADATA_SCHEMA_VERSION = "1.0"
NARVIS_ARCHITECTURE_VERSION = "1.5"
NARVIS_REPOSITORY_VERSION = "develop-v1.1"
NARVIS_COMPATIBILITY_VERSION = "1.4"

RUNTIME_FEATURE_REGISTRY_VERSION = "1.5.1"
RUNTIME_DEPENDENCY_GRAPH_VERSION = "1.5.2"
RUNTIME_STATE_VERSION = "1.5.3"
RUNTIME_OBSERVABILITY_VERSION = "1.5.4"
RUNTIME_DIAGNOSTICS_VERSION = "1.4.1"
RUNTIME_SERVICE_REGISTRY_VERSION = "1.4.2"
RUNTIME_CAPABILITY_MANIFEST_VERSION = "1.4.3"

_SNAPSHOT_ID_PREFIX = "runtime-metadata-"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_NUMERIC_VERSION_PATTERN = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class RuntimeMetadataValidationStatus(str, Enum):
    """Semantic validation results for one metadata catalogue."""

    VALID = "valid"
    INVALID = "invalid"


class RuntimeMetadataCompatibilityStatus(str, Enum):
    """Compatibility verification results for version metadata."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


def _text(value: object, name: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise ValueError(
            f"{name} must be normalized non-empty text of at most {maximum} characters"
        )
    return value


def _version(value: object, name: str) -> str:
    version = _text(value, name, maximum=64)
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(
            f"{name} must contain only alphanumeric version characters, '.', '-', '+', or '_'"
        )
    return version


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of identifiers")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    for value in result:
        _text(value, name, maximum=128)
    if result != tuple(sorted(set(result))):
        raise ValueError(f"{name} must use unique deterministic ordering")
    return result


def _numeric_version(value: str) -> tuple[int, int, int] | None:
    match = _NUMERIC_VERSION_PATTERN.match(value)
    if match is None:
        return None
    return tuple(int(item or 0) for item in match.groups())  # type: ignore[return-value]


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(value[key])
            for key in sorted(value, key=str)
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise TypeError(f"unsupported metadata export value: {type(value).__name__}")


def _immutable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return MappingProxyType(
            {item.name: _immutable(getattr(value, item.name)) for item in fields(value)}
        )
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _immutable(value[key])
                for key in sorted(value, key=str)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_immutable(item) for item in value)
    raise TypeError(f"unsupported metadata export value: {type(value).__name__}")


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(slots=True, frozen=True)
class RuntimeMetadataVersions:
    """Complete immutable version catalogue for the composed runtime."""

    runtime_version: str
    architecture_version: str
    schema_version: str
    repository_version: str
    compatibility_version: str
    feature_registry_version: str
    capability_manifest_version: str
    dependency_graph_version: str
    runtime_state_version: str
    observability_version: str
    diagnostics_version: str
    service_registry_version: str = RUNTIME_SERVICE_REGISTRY_VERSION
    metadata_catalog_version: str = RUNTIME_METADATA_CATALOG_VERSION
    runtime_configuration_version: str = RUNTIME_CONFIGURATION_VERSION
    configuration_schema_version: str = RUNTIME_CONFIGURATION_SCHEMA_VERSION
    configuration_compatibility_version: str = (
        RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION
    )

    def __post_init__(self) -> None:
        for item in fields(self):
            object.__setattr__(
                self,
                item.name,
                _version(getattr(self, item.name), item.name),
            )

    def as_mapping(self) -> Mapping[str, str]:
        """Return all versions in immutable deterministic field-name order."""

        return MappingProxyType(
            {
                item.name: getattr(self, item.name)
                for item in sorted(fields(self), key=lambda value: value.name)
            }
        )


def default_runtime_metadata_versions(
    *,
    runtime_version: str = NARVIS_ARCHITECTURE_VERSION,
    repository_version: str = NARVIS_REPOSITORY_VERSION,
) -> RuntimeMetadataVersions:
    """Return the built-in Version 1.5 metadata version set."""

    return RuntimeMetadataVersions(
        runtime_version=runtime_version,
        architecture_version=NARVIS_ARCHITECTURE_VERSION,
        schema_version=RUNTIME_METADATA_SCHEMA_VERSION,
        repository_version=repository_version,
        compatibility_version=NARVIS_COMPATIBILITY_VERSION,
        feature_registry_version=RUNTIME_FEATURE_REGISTRY_VERSION,
        capability_manifest_version=RUNTIME_CAPABILITY_MANIFEST_VERSION,
        dependency_graph_version=RUNTIME_DEPENDENCY_GRAPH_VERSION,
        runtime_state_version=RUNTIME_STATE_VERSION,
        observability_version=RUNTIME_OBSERVABILITY_VERSION,
        diagnostics_version=RUNTIME_DIAGNOSTICS_VERSION,
        service_registry_version=RUNTIME_SERVICE_REGISTRY_VERSION,
        metadata_catalog_version=RUNTIME_METADATA_CATALOG_VERSION,
        runtime_configuration_version=RUNTIME_CONFIGURATION_VERSION,
        configuration_schema_version=RUNTIME_CONFIGURATION_SCHEMA_VERSION,
        configuration_compatibility_version=(
            RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION
        ),
    )


@dataclass(slots=True, frozen=True)
class RuntimeMetadataEntry:
    """One deterministically ordered named version entry."""

    component: str
    version: str
    category: str

    def __post_init__(self) -> None:
        _text(self.component, "component", maximum=128)
        _version(self.version, "version")
        _text(self.category, "category", maximum=128)


@dataclass(slots=True, frozen=True)
class RuntimeMetadataValidationReport:
    """Deterministic semantic validation of runtime version metadata."""

    status: RuntimeMetadataValidationStatus
    checked_fields: tuple[str, ...]
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeMetadataValidationStatus):
            raise TypeError("status must be a RuntimeMetadataValidationStatus")
        object.__setattr__(
            self,
            "checked_fields",
            _identifiers(self.checked_fields, "checked_fields"),
        )
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "validation issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "issues", issues)

    @property
    def valid(self) -> bool:
        """Return whether all metadata validation checks passed."""

        return self.status is RuntimeMetadataValidationStatus.VALID


@dataclass(slots=True, frozen=True)
class RuntimeMetadataCompatibilityReport:
    """Deterministic compatibility verification for a requested version."""

    status: RuntimeMetadataCompatibilityStatus
    runtime_version: str
    compatibility_version: str
    required_version: str
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeMetadataCompatibilityStatus):
            raise TypeError("status must be a RuntimeMetadataCompatibilityStatus")
        for name in (
            "runtime_version",
            "compatibility_version",
            "required_version",
        ):
            object.__setattr__(self, name, _version(getattr(self, name), name))
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "compatibility issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "issues", issues)

    @property
    def compatible(self) -> bool:
        """Return whether the requested version is supported."""

        return self.status is RuntimeMetadataCompatibilityStatus.COMPATIBLE


@dataclass(slots=True, frozen=True)
class RuntimeMetadataComparison:
    """Deterministic comparison between two metadata snapshots."""

    left_snapshot_id: str
    right_snapshot_id: str
    same_snapshot: bool
    same_content: bool
    same_versions: bool
    timestamp_changed: bool
    changed_components: tuple[str, ...]
    compatibility_changed: bool
    validation_changed: bool
    summary: str

    def __post_init__(self) -> None:
        for name in ("left_snapshot_id", "right_snapshot_id"):
            _text(getattr(self, name), name, maximum=128)
        for name in (
            "same_snapshot",
            "same_content",
            "same_versions",
            "timestamp_changed",
            "compatibility_changed",
            "validation_changed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        object.__setattr__(
            self,
            "changed_components",
            _identifiers(self.changed_components, "changed_components"),
        )
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeMetadataSnapshot:
    """Versioned, content-addressed immutable runtime metadata snapshot."""

    snapshot_id: str
    content_hash: str
    versions: RuntimeMetadataVersions
    entries: tuple[RuntimeMetadataEntry, ...]
    validation_report: RuntimeMetadataValidationReport
    compatibility_report: RuntimeMetadataCompatibilityReport
    captured_at: datetime | None = None
    deterministic: bool = True
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        _text(self.snapshot_id, "snapshot_id", maximum=128)
        if not self.snapshot_id.startswith(_SNAPSHOT_ID_PREFIX):
            raise ValueError("snapshot_id must use the runtime metadata prefix")
        identifier_hash = self.snapshot_id.removeprefix(_SNAPSHOT_ID_PREFIX)
        for name, value in (
            ("snapshot id hash", identifier_hash),
            ("content_hash", self.content_hash),
        ):
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ValueError(f"{name} must be a SHA-256 digest")
        if not isinstance(self.versions, RuntimeMetadataVersions):
            raise TypeError("versions must be RuntimeMetadataVersions")
        entries = tuple(self.entries)
        if not all(isinstance(item, RuntimeMetadataEntry) for item in entries):
            raise TypeError("entries must contain RuntimeMetadataEntry values")
        components = tuple(item.component for item in entries)
        if components != tuple(sorted(set(components))):
            raise ValueError("entries must use unique component ordering")
        if not isinstance(
            self.validation_report,
            RuntimeMetadataValidationReport,
        ):
            raise TypeError(
                "validation_report must be a RuntimeMetadataValidationReport"
            )
        if not isinstance(
            self.compatibility_report,
            RuntimeMetadataCompatibilityReport,
        ):
            raise TypeError(
                "compatibility_report must be a RuntimeMetadataCompatibilityReport"
            )
        if self.captured_at is not None:
            _time(self.captured_at, "captured_at")
        if self.deterministic is not True:
            raise ValueError("runtime metadata snapshots must be deterministic")
        if self.calculated_from_metadata is not True:
            raise ValueError("runtime metadata must be calculated from metadata")
        if self.active_probes is not False:
            raise ValueError("runtime metadata cannot use active probes")
        object.__setattr__(self, "entries", entries)

    @property
    def runtime_version(self) -> str:
        return self.versions.runtime_version

    @property
    def architecture_version(self) -> str:
        return self.versions.architecture_version

    @property
    def schema_version(self) -> str:
        return self.versions.schema_version

    @property
    def repository_version(self) -> str:
        return self.versions.repository_version

    @property
    def compatibility_version(self) -> str:
        return self.versions.compatibility_version

    @property
    def feature_registry_version(self) -> str:
        return self.versions.feature_registry_version

    @property
    def capability_manifest_version(self) -> str:
        return self.versions.capability_manifest_version

    @property
    def dependency_graph_version(self) -> str:
        return self.versions.dependency_graph_version

    @property
    def runtime_state_version(self) -> str:
        return self.versions.runtime_state_version

    @property
    def observability_version(self) -> str:
        return self.versions.observability_version

    @property
    def diagnostics_version(self) -> str:
        return self.versions.diagnostics_version

    @property
    def runtime_configuration_version(self) -> str:
        return self.versions.runtime_configuration_version

    @property
    def configuration_schema_version(self) -> str:
        return self.versions.configuration_schema_version

    @property
    def configuration_compatibility_version(self) -> str:
        return self.versions.configuration_compatibility_version

    def get(self, component: str) -> RuntimeMetadataEntry | None:
        """Return one named version entry."""

        _text(component, "component", maximum=128)
        return next((item for item in self.entries if item.component == component), None)

    def export(self) -> Mapping[str, object]:
        """Return a deeply immutable deterministic mapping export."""

        return _immutable(self)

    def serialize(self) -> str:
        """Return deterministic compact JSON without mutating the snapshot."""

        return json.dumps(
            _canonical(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def to_json(self) -> str:
        """Compatibility spelling for :meth:`serialize`."""

        return self.serialize()

    def to_dict(self) -> dict[str, object]:
        """Return a detached mutable JSON-safe copy of the snapshot export."""

        return json.loads(self.serialize())

    @classmethod
    def deserialize(cls, payload: str) -> RuntimeMetadataSnapshot:
        """Rebuild and validate a snapshot from its deterministic JSON export."""

        if not isinstance(payload, str):
            raise TypeError("payload must be a string")
        try:
            data = json.loads(payload)
            versions = RuntimeMetadataVersions(**data["versions"])
            captured_value = data.get("captured_at")
            captured_at = (
                datetime.fromisoformat(captured_value)
                if captured_value is not None
                else None
            )
            required_version = data["compatibility_report"]["required_version"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("payload is not a valid runtime metadata snapshot") from error
        snapshot = RuntimeMetadataCatalog(versions).snapshot(
            captured_at=captured_at,
            required_compatibility_version=required_version,
        )
        if (
            snapshot.snapshot_id != data.get("snapshot_id")
            or snapshot.content_hash != data.get("content_hash")
        ):
            raise ValueError("serialized runtime metadata integrity check failed")
        return snapshot

    from_json = deserialize

    def compare(self, other: RuntimeMetadataSnapshot) -> RuntimeMetadataComparison:
        """Compare this snapshot with another snapshot deterministically."""

        return RuntimeMetadataCatalog.compare(self, other)


@dataclass(slots=True, frozen=True)
class RuntimeMetadataCatalog:
    """Build, validate, export, and compare immutable runtime metadata."""

    versions: RuntimeMetadataVersions = RuntimeMetadataVersions(
        runtime_version=NARVIS_ARCHITECTURE_VERSION,
        architecture_version=NARVIS_ARCHITECTURE_VERSION,
        schema_version=RUNTIME_METADATA_SCHEMA_VERSION,
        repository_version=NARVIS_REPOSITORY_VERSION,
        compatibility_version=NARVIS_COMPATIBILITY_VERSION,
        feature_registry_version=RUNTIME_FEATURE_REGISTRY_VERSION,
        capability_manifest_version=RUNTIME_CAPABILITY_MANIFEST_VERSION,
        dependency_graph_version=RUNTIME_DEPENDENCY_GRAPH_VERSION,
        runtime_state_version=RUNTIME_STATE_VERSION,
        observability_version=RUNTIME_OBSERVABILITY_VERSION,
        diagnostics_version=RUNTIME_DIAGNOSTICS_VERSION,
        runtime_configuration_version=RUNTIME_CONFIGURATION_VERSION,
        configuration_schema_version=RUNTIME_CONFIGURATION_SCHEMA_VERSION,
        configuration_compatibility_version=(
            RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION
        ),
    )

    def __post_init__(self) -> None:
        if not isinstance(self.versions, RuntimeMetadataVersions):
            raise TypeError("versions must be RuntimeMetadataVersions")

    def snapshot(
        self,
        *,
        captured_at: datetime | None = None,
        required_compatibility_version: str | None = None,
    ) -> RuntimeMetadataSnapshot:
        """Return one deterministic immutable metadata snapshot."""

        if captured_at is not None:
            _time(captured_at, "captured_at")
        entries = self._entries(self.versions)
        validation = self.validate()
        compatibility = self.verify_compatibility(
            required_compatibility_version
        )
        content_payload = {
            "versions": self.versions,
            "entries": entries,
            "validation_report": validation,
            "compatibility_report": compatibility,
        }
        content_hash = _digest(content_payload)
        snapshot_hash = _digest(
            {
                "content_hash": content_hash,
                "captured_at": captured_at,
            }
        )
        return RuntimeMetadataSnapshot(
            snapshot_id=f"{_SNAPSHOT_ID_PREFIX}{snapshot_hash}",
            content_hash=content_hash,
            versions=self.versions,
            entries=entries,
            validation_report=validation,
            compatibility_report=compatibility,
            captured_at=captured_at,
        )

    def export(
        self,
        *,
        captured_at: datetime | None = None,
        required_compatibility_version: str | None = None,
    ) -> Mapping[str, object]:
        """Build and deeply freeze one deterministic metadata export."""

        return self.snapshot(
            captured_at=captured_at,
            required_compatibility_version=required_compatibility_version,
        ).export()

    def validate(self) -> RuntimeMetadataValidationReport:
        """Return deterministic semantic validation for the catalog versions."""

        issues: set[str] = set()
        runtime = _numeric_version(self.versions.runtime_version)
        architecture = _numeric_version(self.versions.architecture_version)
        compatibility = _numeric_version(self.versions.compatibility_version)
        schema = _numeric_version(self.versions.schema_version)
        if runtime is None:
            issues.add("runtime version must have a numeric prefix")
        if architecture is None:
            issues.add("architecture version must have a numeric prefix")
        if schema is None:
            issues.add("schema version must have a numeric prefix")
        if compatibility is None:
            issues.add("compatibility version must have a numeric prefix")
        if runtime is not None and architecture is not None:
            if runtime[0] != architecture[0]:
                issues.add("runtime and architecture major versions must match")
            if architecture > runtime:
                issues.add("architecture version cannot exceed runtime version")
        if runtime is not None and compatibility is not None and compatibility > runtime:
            issues.add("compatibility version cannot exceed runtime version")
        checked = tuple(sorted(self.versions.as_mapping()))
        status = (
            RuntimeMetadataValidationStatus.INVALID
            if issues
            else RuntimeMetadataValidationStatus.VALID
        )
        return RuntimeMetadataValidationReport(
            status=status,
            checked_fields=checked,
            issues=tuple(sorted(issues)),
            summary=(
                f"Runtime metadata validation is {status.value}: "
                f"{len(checked)} version fields checked and {len(issues)} issues found."
            ),
        )

    def verify_compatibility(
        self,
        required_version: str | None = None,
    ) -> RuntimeMetadataCompatibilityReport:
        """Verify a requested version against the declared compatibility range."""

        required = _version(
            required_version or self.versions.compatibility_version,
            "required_version",
        )
        runtime = _numeric_version(self.versions.runtime_version)
        baseline = _numeric_version(self.versions.compatibility_version)
        requested = _numeric_version(required)
        issues: set[str] = set()
        if runtime is None or baseline is None or requested is None:
            status = RuntimeMetadataCompatibilityStatus.UNKNOWN
            issues.add("compatibility comparison requires numeric version prefixes")
        else:
            if requested < baseline:
                issues.add("required version is older than the compatibility baseline")
            if requested > runtime:
                issues.add("required version is newer than the runtime version")
            if requested[0] != runtime[0]:
                issues.add("required and runtime major versions must match")
            status = (
                RuntimeMetadataCompatibilityStatus.INCOMPATIBLE
                if issues
                else RuntimeMetadataCompatibilityStatus.COMPATIBLE
            )
        return RuntimeMetadataCompatibilityReport(
            status=status,
            runtime_version=self.versions.runtime_version,
            compatibility_version=self.versions.compatibility_version,
            required_version=required,
            issues=tuple(sorted(issues)),
            summary=(
                f"Runtime metadata compatibility is {status.value} for required "
                f"version {required}; supported baseline is "
                f"{self.versions.compatibility_version}."
            ),
        )

    @staticmethod
    def compare(
        left: RuntimeMetadataSnapshot,
        right: RuntimeMetadataSnapshot,
    ) -> RuntimeMetadataComparison:
        """Return a deterministic comparison of two metadata snapshots."""

        if not isinstance(left, RuntimeMetadataSnapshot) or not isinstance(
            right,
            RuntimeMetadataSnapshot,
        ):
            raise TypeError("left and right must be RuntimeMetadataSnapshot values")
        left_entries = {item.component: item.version for item in left.entries}
        right_entries = {item.component: item.version for item in right.entries}
        components = tuple(sorted(set(left_entries) | set(right_entries)))
        changed = tuple(
            component
            for component in components
            if left_entries.get(component) != right_entries.get(component)
        )
        same_snapshot = left.snapshot_id == right.snapshot_id
        same_content = left.content_hash == right.content_hash
        summary = (
            f"Runtime metadata snapshots are "
            f"{'identical' if same_snapshot else 'different'}; "
            f"{len(changed)} component versions changed."
        )
        return RuntimeMetadataComparison(
            left_snapshot_id=left.snapshot_id,
            right_snapshot_id=right.snapshot_id,
            same_snapshot=same_snapshot,
            same_content=same_content,
            same_versions=left.versions == right.versions,
            timestamp_changed=left.captured_at != right.captured_at,
            changed_components=changed,
            compatibility_changed=(
                left.compatibility_report != right.compatibility_report
            ),
            validation_changed=left.validation_report != right.validation_report,
            summary=summary,
        )

    @staticmethod
    def _entries(
        versions: RuntimeMetadataVersions,
    ) -> tuple[RuntimeMetadataEntry, ...]:
        categories = {
            "architecture_version": "architecture",
            "capability_manifest_version": "runtime_component",
            "configuration_compatibility_version": "compatibility",
            "configuration_schema_version": "schema",
            "compatibility_version": "compatibility",
            "dependency_graph_version": "runtime_component",
            "diagnostics_version": "runtime_component",
            "feature_registry_version": "runtime_component",
            "metadata_catalog_version": "runtime_component",
            "observability_version": "runtime_component",
            "repository_version": "repository",
            "runtime_state_version": "runtime_component",
            "runtime_configuration_version": "runtime_component",
            "runtime_version": "runtime",
            "schema_version": "schema",
            "service_registry_version": "runtime_component",
        }
        return tuple(
            sorted(
                (
                    RuntimeMetadataEntry(
                        component=name.removesuffix("_version"),
                        version=value,
                        category=categories[name],
                    )
                    for name, value in versions.as_mapping().items()
                ),
                key=lambda item: item.component,
            )
        )


def build_runtime_metadata_catalog(
    *,
    runtime_version: str = NARVIS_ARCHITECTURE_VERSION,
    repository_version: str = NARVIS_REPOSITORY_VERSION,
) -> RuntimeMetadataCatalog:
    """Build the default passive Runtime Metadata Catalog."""

    return RuntimeMetadataCatalog(
        default_runtime_metadata_versions(
            runtime_version=runtime_version,
            repository_version=repository_version,
        )
    )


__all__ = [
    "NARVIS_ARCHITECTURE_VERSION",
    "NARVIS_COMPATIBILITY_VERSION",
    "NARVIS_REPOSITORY_VERSION",
    "RUNTIME_CAPABILITY_MANIFEST_VERSION",
    "RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION",
    "RUNTIME_CONFIGURATION_SCHEMA_VERSION",
    "RUNTIME_CONFIGURATION_VERSION",
    "RUNTIME_DEPENDENCY_GRAPH_VERSION",
    "RUNTIME_DIAGNOSTICS_VERSION",
    "RUNTIME_FEATURE_REGISTRY_VERSION",
    "RUNTIME_METADATA_CATALOG_VERSION",
    "RUNTIME_METADATA_SCHEMA_VERSION",
    "RUNTIME_OBSERVABILITY_VERSION",
    "RUNTIME_SERVICE_REGISTRY_VERSION",
    "RUNTIME_STATE_VERSION",
    "RuntimeMetadataCatalog",
    "RuntimeMetadataComparison",
    "RuntimeMetadataCompatibilityReport",
    "RuntimeMetadataCompatibilityStatus",
    "RuntimeMetadataEntry",
    "RuntimeMetadataSnapshot",
    "RuntimeMetadataValidationReport",
    "RuntimeMetadataValidationStatus",
    "RuntimeMetadataVersions",
    "build_runtime_metadata_catalog",
    "default_runtime_metadata_versions",
]
