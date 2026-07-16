"""Immutable deterministic runtime configuration metadata.

The registry describes configuration values without applying them.  It never
resolves services, changes application settings, invokes providers or AI
models, performs I/O, uses networking, or enters Trusted Execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
import re
from types import MappingProxyType
from typing import Any

from .runtime_profiles import RUNTIME_PROFILE_REGISTRY_VERSION


RUNTIME_CONFIGURATION_VERSION = "1.5.6"
RUNTIME_CONFIGURATION_SCHEMA_VERSION = "1.0"
RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION = "1.0"

_CONFIGURATION_ID_PREFIX = "runtime-config-"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_NUMERIC_VERSION_PATTERN = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][A-Za-z0-9._-]+)?$"
)
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class RuntimeConfigurationValidationStatus(str, Enum):
    """Validation states for immutable runtime configuration metadata."""

    VALID = "valid"
    INVALID = "invalid"


class RuntimeConfigurationCompatibilityStatus(str, Enum):
    """Schema compatibility states for configuration consumers."""

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


def _numeric_version(value: str) -> tuple[int, int, int] | None:
    match = _NUMERIC_VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    return tuple(int(item or 0) for item in match.groups())  # type: ignore[return-value]


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


def _freeze_value(value: Any, name: str = "configuration value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{name} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key in sorted(value, key=str):
            _text(key, f"{name} key", maximum=128)
            frozen[key] = _freeze_value(value[key], name)
        return MappingProxyType(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item, name) for item in value)
    raise TypeError(
        f"{name} must contain only JSON-safe scalar, mapping, or sequence values"
    )


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
    raise TypeError(f"unsupported configuration export value: {type(value).__name__}")


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
    raise TypeError(f"unsupported configuration export value: {type(value).__name__}")


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationVersions:
    """Immutable configuration and schema version metadata."""

    configuration_version: str = RUNTIME_CONFIGURATION_VERSION
    schema_version: str = RUNTIME_CONFIGURATION_SCHEMA_VERSION
    compatibility_version: str = RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION

    def __post_init__(self) -> None:
        for item in fields(self):
            object.__setattr__(
                self,
                item.name,
                _version(getattr(self, item.name), item.name),
            )

    def as_mapping(self) -> Mapping[str, str]:
        """Return versions in immutable deterministic field-name order."""

        return MappingProxyType(
            {
                item.name: getattr(self, item.name)
                for item in sorted(fields(self), key=lambda value: value.name)
            }
        )


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationEntry:
    """One immutable named configuration value and its declared default."""

    key: str
    value: Any
    default_value: Any
    category: str
    description: str

    def __post_init__(self) -> None:
        key = _text(self.key, "configuration key", maximum=128)
        if _KEY_PATTERN.fullmatch(key) is None:
            raise ValueError("configuration key must use normalized dotted identifiers")
        _text(self.category, "category", maximum=128)
        _text(self.description, "description", maximum=1000)
        object.__setattr__(self, "value", _freeze_value(self.value))
        object.__setattr__(
            self,
            "default_value",
            _freeze_value(self.default_value, "default configuration value"),
        )

    @property
    def overridden(self) -> bool:
        """Return whether the current value differs from its default."""

        return _canonical(self.value) != _canonical(self.default_value)


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationValidationReport:
    """Deterministic validation of configuration versions and entries."""

    status: RuntimeConfigurationValidationStatus
    checked_entry_count: int
    checked_version_fields: tuple[str, ...]
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeConfigurationValidationStatus):
            raise TypeError("status must be a RuntimeConfigurationValidationStatus")
        if (
            isinstance(self.checked_entry_count, bool)
            or not isinstance(self.checked_entry_count, int)
            or self.checked_entry_count < 0
        ):
            raise ValueError("checked_entry_count must be a non-negative integer")
        object.__setattr__(
            self,
            "checked_version_fields",
            _identifiers(self.checked_version_fields, "checked_version_fields"),
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
        """Return whether configuration validation succeeded."""

        return self.status is RuntimeConfigurationValidationStatus.VALID


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationCompatibilityReport:
    """Deterministic compatibility validation for a requested schema."""

    status: RuntimeConfigurationCompatibilityStatus
    configuration_version: str
    schema_version: str
    compatibility_version: str
    required_version: str
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeConfigurationCompatibilityStatus):
            raise TypeError(
                "status must be a RuntimeConfigurationCompatibilityStatus"
            )
        for name in (
            "configuration_version",
            "schema_version",
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
        """Return whether the requested configuration schema is supported."""

        return self.status is RuntimeConfigurationCompatibilityStatus.COMPATIBLE


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationSummary:
    """Compact immutable configuration snapshot summary metadata."""

    configuration_id: str
    configuration_version: str
    schema_version: str
    total_entry_count: int
    default_entry_count: int
    overridden_entry_count: int
    category_count: int
    categories: tuple[str, ...]
    validation_status: RuntimeConfigurationValidationStatus
    compatibility_status: RuntimeConfigurationCompatibilityStatus
    summary: str

    def __post_init__(self) -> None:
        _configuration_id(self.configuration_id)
        _version(self.configuration_version, "configuration_version")
        _version(self.schema_version, "schema_version")
        for name in (
            "total_entry_count",
            "default_entry_count",
            "overridden_entry_count",
            "category_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.default_entry_count + self.overridden_entry_count != self.total_entry_count:
            raise ValueError("default and overridden entry counts must match total")
        categories = _identifiers(self.categories, "categories")
        if self.category_count != len(categories):
            raise ValueError("category_count must match categories")
        if not isinstance(
            self.validation_status,
            RuntimeConfigurationValidationStatus,
        ):
            raise TypeError(
                "validation_status must be a RuntimeConfigurationValidationStatus"
            )
        if not isinstance(
            self.compatibility_status,
            RuntimeConfigurationCompatibilityStatus,
        ):
            raise TypeError(
                "compatibility_status must be a RuntimeConfigurationCompatibilityStatus"
            )
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "categories", categories)


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationComparison:
    """Deterministic comparison between two configuration snapshots."""

    left_configuration_id: str
    right_configuration_id: str
    same_snapshot: bool
    same_content: bool
    same_versions: bool
    timestamp_changed: bool
    changed_keys: tuple[str, ...]
    added_keys: tuple[str, ...]
    removed_keys: tuple[str, ...]
    compatibility_changed: bool
    validation_changed: bool
    summary: str

    def __post_init__(self) -> None:
        _configuration_id(self.left_configuration_id)
        _configuration_id(self.right_configuration_id)
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
        for name in ("changed_keys", "added_keys", "removed_keys"):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        _text(self.summary, "summary", maximum=2000)


def _configuration_id(value: object) -> str:
    identifier = _text(value, "configuration_id", maximum=128)
    if not identifier.startswith(_CONFIGURATION_ID_PREFIX):
        raise ValueError("configuration_id must use the runtime configuration prefix")
    digest = identifier.removeprefix(_CONFIGURATION_ID_PREFIX)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("configuration_id must contain a SHA-256 digest")
    return identifier


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationSnapshot:
    """Content-addressed immutable runtime configuration snapshot."""

    configuration_id: str
    content_hash: str
    versions: RuntimeConfigurationVersions
    entries: tuple[RuntimeConfigurationEntry, ...]
    validation_report: RuntimeConfigurationValidationReport
    compatibility_report: RuntimeConfigurationCompatibilityReport
    configuration_summary: RuntimeConfigurationSummary
    captured_at: datetime | None = None
    deterministic: bool = True
    read_only: bool = True
    calculated_from_metadata: bool = True
    active_application: bool = False

    def __post_init__(self) -> None:
        _configuration_id(self.configuration_id)
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a SHA-256 digest")
        if self.configuration_id != f"{_CONFIGURATION_ID_PREFIX}{self.content_hash}":
            raise ValueError("configuration_id must be content-addressed")
        if not isinstance(self.versions, RuntimeConfigurationVersions):
            raise TypeError("versions must be RuntimeConfigurationVersions")
        entries = tuple(self.entries)
        if not all(isinstance(item, RuntimeConfigurationEntry) for item in entries):
            raise TypeError("entries must contain RuntimeConfigurationEntry values")
        keys = tuple(item.key for item in entries)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("entries must use unique key ordering")
        if not isinstance(
            self.validation_report,
            RuntimeConfigurationValidationReport,
        ):
            raise TypeError(
                "validation_report must be a RuntimeConfigurationValidationReport"
            )
        if not isinstance(
            self.compatibility_report,
            RuntimeConfigurationCompatibilityReport,
        ):
            raise TypeError(
                "compatibility_report must be a RuntimeConfigurationCompatibilityReport"
            )
        if not isinstance(self.configuration_summary, RuntimeConfigurationSummary):
            raise TypeError(
                "configuration_summary must be a RuntimeConfigurationSummary"
            )
        if self.configuration_summary.configuration_id != self.configuration_id:
            raise ValueError("configuration summary must match configuration_id")
        if self.captured_at is not None:
            _time(self.captured_at, "captured_at")
        if self.deterministic is not True:
            raise ValueError("runtime configuration snapshots must be deterministic")
        if self.read_only is not True:
            raise ValueError("runtime configuration snapshots must be read-only")
        if self.calculated_from_metadata is not True:
            raise ValueError("runtime configuration must be metadata-derived")
        if self.active_application is not False:
            raise ValueError("runtime configuration snapshots cannot apply settings")
        object.__setattr__(self, "entries", entries)

    @property
    def configuration_version(self) -> str:
        return self.versions.configuration_version

    @property
    def schema_version(self) -> str:
        return self.versions.schema_version

    @property
    def compatibility_version(self) -> str:
        return self.versions.compatibility_version

    @property
    def summary(self) -> RuntimeConfigurationSummary:
        return self.configuration_summary

    def get(self, key: str) -> RuntimeConfigurationEntry | None:
        """Return one named immutable configuration entry."""

        _text(key, "configuration key", maximum=128)
        return next((item for item in self.entries if item.key == key), None)

    def values(self) -> Mapping[str, object]:
        """Return current values as a deeply immutable ordered mapping."""

        return MappingProxyType(
            {item.key: _immutable(item.value) for item in self.entries}
        )

    def defaults(self) -> Mapping[str, object]:
        """Return default values as a deeply immutable ordered mapping."""

        return MappingProxyType(
            {item.key: _immutable(item.default_value) for item in self.entries}
        )

    def export(self) -> Mapping[str, object]:
        """Return a deeply immutable deterministic snapshot export."""

        return _immutable(self)

    def serialize(self) -> str:
        """Return deterministic compact JSON serialization."""

        return json.dumps(
            _canonical(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    to_json = serialize

    def to_dict(self) -> dict[str, object]:
        """Return a detached mutable JSON-safe copy."""

        return json.loads(self.serialize())

    @classmethod
    def deserialize(cls, payload: str) -> RuntimeConfigurationSnapshot:
        """Rebuild and integrity-check a serialized configuration snapshot."""

        if not isinstance(payload, str):
            raise TypeError("payload must be a string")
        try:
            data = json.loads(payload)
            versions = RuntimeConfigurationVersions(**data["versions"])
            entries = tuple(
                RuntimeConfigurationEntry(**entry) for entry in data["entries"]
            )
            captured_value = data.get("captured_at")
            captured_at = (
                datetime.fromisoformat(captured_value)
                if captured_value is not None
                else None
            )
            required_version = data["compatibility_report"]["required_version"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(
                "payload is not a valid runtime configuration snapshot"
            ) from error
        snapshot = RuntimeConfigurationRegistry(
            entries=entries,
            versions=versions,
        ).snapshot(
            captured_at=captured_at,
            required_schema_version=required_version,
        )
        if (
            snapshot.configuration_id != data.get("configuration_id")
            or snapshot.content_hash != data.get("content_hash")
        ):
            raise ValueError("serialized configuration integrity check failed")
        return snapshot

    from_json = deserialize

    def compare(
        self,
        other: RuntimeConfigurationSnapshot,
    ) -> RuntimeConfigurationComparison:
        """Compare this snapshot with another retained snapshot."""

        return RuntimeConfigurationRegistry.compare(self, other)


def default_runtime_configuration_entries() -> tuple[RuntimeConfigurationEntry, ...]:
    """Return deterministic non-sensitive runtime configuration defaults."""

    definitions = (
        (
            "metadata.deterministic_ordering",
            True,
            "metadata",
            "Require deterministic key and entry ordering for metadata exports.",
        ),
        (
            "metadata.read_only_exports",
            True,
            "metadata",
            "Expose configuration through recursively immutable exports.",
        ),
        (
            "runtime.app_name",
            "NARVIS",
            "runtime",
            "Human-readable runtime application name.",
        ),
        (
            "runtime.data_directory",
            "data",
            "runtime",
            "Configured runtime data directory metadata.",
        ),
        (
            "runtime.debug",
            True,
            "runtime",
            "Configured diagnostic verbosity metadata.",
        ),
        (
            "runtime.environment",
            "development",
            "runtime",
            "Configured runtime environment name.",
        ),
        (
            "runtime.log_directory",
            "logs",
            "runtime",
            "Configured runtime log directory metadata.",
        ),
        (
            "runtime.profile_registry_version",
            RUNTIME_PROFILE_REGISTRY_VERSION,
            "runtime",
            "Configured immutable Runtime Profile Registry version metadata.",
        ),
        (
            "runtime.version",
            "1.5",
            "runtime",
            "Configured NARVIS runtime version metadata.",
        ),
    )
    return tuple(
        RuntimeConfigurationEntry(
            key=key,
            value=value,
            default_value=value,
            category=category,
            description=description,
        )
        for key, value, category, description in definitions
    )


@dataclass(slots=True, frozen=True)
class RuntimeConfigurationRegistry:
    """Immutable registry of deterministic runtime configuration metadata."""

    entries: tuple[RuntimeConfigurationEntry, ...] = (
        default_runtime_configuration_entries()
    )
    versions: RuntimeConfigurationVersions = RuntimeConfigurationVersions()

    def __post_init__(self) -> None:
        if not isinstance(self.versions, RuntimeConfigurationVersions):
            raise TypeError("versions must be RuntimeConfigurationVersions")
        entries = tuple(self.entries)
        if not all(isinstance(item, RuntimeConfigurationEntry) for item in entries):
            raise TypeError("entries must contain RuntimeConfigurationEntry values")
        keys = tuple(item.key for item in entries)
        if len(set(keys)) != len(keys):
            raise ValueError("configuration keys must be unique")
        object.__setattr__(self, "entries", tuple(sorted(entries, key=lambda item: item.key)))

    def get(self, key: str) -> RuntimeConfigurationEntry | None:
        """Return one registered configuration entry."""

        _text(key, "configuration key", maximum=128)
        return next((item for item in self.entries if item.key == key), None)

    def register(
        self,
        entry: RuntimeConfigurationEntry,
    ) -> RuntimeConfigurationRegistry:
        """Return a new registry containing one additional unique entry."""

        if not isinstance(entry, RuntimeConfigurationEntry):
            raise TypeError("entry must be a RuntimeConfigurationEntry")
        if self.get(entry.key) is not None:
            raise ValueError(f"configuration key is already registered: {entry.key}")
        return RuntimeConfigurationRegistry(
            entries=(*self.entries, entry),
            versions=self.versions,
        )

    def with_values(
        self,
        values: Mapping[str, object],
    ) -> RuntimeConfigurationRegistry:
        """Return a new registry with declared values replaced immutably."""

        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        unknown = tuple(sorted(set(values) - {item.key for item in self.entries}))
        if unknown:
            raise KeyError(f"unknown runtime configuration keys: {', '.join(unknown)}")
        replacements = {
            key: _freeze_value(values[key]) for key in sorted(values)
        }
        return RuntimeConfigurationRegistry(
            entries=tuple(
                replace(item, value=replacements[item.key])
                if item.key in replacements
                else item
                for item in self.entries
            ),
            versions=self.versions,
        )

    def validate(self) -> RuntimeConfigurationValidationReport:
        """Return deterministic semantic validation metadata."""

        issues: set[str] = set()
        configuration = _numeric_version(self.versions.configuration_version)
        schema = _numeric_version(self.versions.schema_version)
        compatibility = _numeric_version(self.versions.compatibility_version)
        if configuration is None:
            issues.add("configuration version must use numeric version syntax")
        if schema is None:
            issues.add("configuration schema version must use numeric version syntax")
        if compatibility is None:
            issues.add("compatibility version must use numeric version syntax")
        if (
            schema is not None
            and compatibility is not None
            and compatibility > schema
        ):
            issues.add("compatibility version cannot exceed schema version")
        if not self.entries:
            issues.add("runtime configuration must contain at least one entry")
        status = (
            RuntimeConfigurationValidationStatus.INVALID
            if issues
            else RuntimeConfigurationValidationStatus.VALID
        )
        return RuntimeConfigurationValidationReport(
            status=status,
            checked_entry_count=len(self.entries),
            checked_version_fields=tuple(sorted(self.versions.as_mapping())),
            issues=tuple(sorted(issues)),
            summary=(
                f"Runtime configuration validation is {status.value}: "
                f"{len(self.entries)} entries and {len(issues)} issues."
            ),
        )

    def verify_compatibility(
        self,
        required_schema_version: str | None = None,
    ) -> RuntimeConfigurationCompatibilityReport:
        """Verify a requested schema against the declared compatible range."""

        required = _version(
            required_schema_version or self.versions.compatibility_version,
            "required_schema_version",
        )
        schema = _numeric_version(self.versions.schema_version)
        baseline = _numeric_version(self.versions.compatibility_version)
        requested = _numeric_version(required)
        issues: set[str] = set()
        if schema is None or baseline is None or requested is None:
            status = RuntimeConfigurationCompatibilityStatus.UNKNOWN
            issues.add("schema compatibility requires numeric version syntax")
        else:
            if requested < baseline:
                issues.add("required schema is older than the compatibility baseline")
            if requested > schema:
                issues.add("required schema is newer than the configuration schema")
            if requested[0] != schema[0]:
                issues.add("required and configuration schema major versions must match")
            status = (
                RuntimeConfigurationCompatibilityStatus.INCOMPATIBLE
                if issues
                else RuntimeConfigurationCompatibilityStatus.COMPATIBLE
            )
        return RuntimeConfigurationCompatibilityReport(
            status=status,
            configuration_version=self.versions.configuration_version,
            schema_version=self.versions.schema_version,
            compatibility_version=self.versions.compatibility_version,
            required_version=required,
            issues=tuple(sorted(issues)),
            summary=(
                f"Runtime configuration compatibility is {status.value} for "
                f"required schema {required}; supported baseline is "
                f"{self.versions.compatibility_version}."
            ),
        )

    def snapshot(
        self,
        *,
        captured_at: datetime | None = None,
        required_schema_version: str | None = None,
    ) -> RuntimeConfigurationSnapshot:
        """Return one deterministic content-addressed configuration snapshot."""

        if captured_at is not None:
            _time(captured_at, "captured_at")
        validation = self.validate()
        compatibility = self.verify_compatibility(required_schema_version)
        content_hash = _digest(
            {
                "versions": self.versions,
                "entries": self.entries,
            }
        )
        configuration_id = f"{_CONFIGURATION_ID_PREFIX}{content_hash}"
        categories = tuple(sorted({item.category for item in self.entries}))
        overridden = sum(item.overridden for item in self.entries)
        summary = RuntimeConfigurationSummary(
            configuration_id=configuration_id,
            configuration_version=self.versions.configuration_version,
            schema_version=self.versions.schema_version,
            total_entry_count=len(self.entries),
            default_entry_count=len(self.entries) - overridden,
            overridden_entry_count=overridden,
            category_count=len(categories),
            categories=categories,
            validation_status=validation.status,
            compatibility_status=compatibility.status,
            summary=(
                f"Runtime configuration contains {len(self.entries)} entries "
                f"across {len(categories)} categories with {overridden} overrides."
            ),
        )
        return RuntimeConfigurationSnapshot(
            configuration_id=configuration_id,
            content_hash=content_hash,
            versions=self.versions,
            entries=self.entries,
            validation_report=validation,
            compatibility_report=compatibility,
            configuration_summary=summary,
            captured_at=captured_at,
        )

    def export(
        self,
        *,
        captured_at: datetime | None = None,
        required_schema_version: str | None = None,
    ) -> Mapping[str, object]:
        """Build and deeply freeze one deterministic configuration export."""

        return self.snapshot(
            captured_at=captured_at,
            required_schema_version=required_schema_version,
        ).export()

    @staticmethod
    def compare(
        left: RuntimeConfigurationSnapshot,
        right: RuntimeConfigurationSnapshot,
    ) -> RuntimeConfigurationComparison:
        """Return a deterministic comparison of two configuration snapshots."""

        if not isinstance(left, RuntimeConfigurationSnapshot) or not isinstance(
            right,
            RuntimeConfigurationSnapshot,
        ):
            raise TypeError(
                "left and right must be RuntimeConfigurationSnapshot values"
            )
        left_values = {item.key: _canonical(item) for item in left.entries}
        right_values = {item.key: _canonical(item) for item in right.entries}
        left_keys = set(left_values)
        right_keys = set(right_values)
        common = left_keys & right_keys
        changed = tuple(
            sorted(key for key in common if left_values[key] != right_values[key])
        )
        same_snapshot = left == right
        same_content = left.content_hash == right.content_hash
        return RuntimeConfigurationComparison(
            left_configuration_id=left.configuration_id,
            right_configuration_id=right.configuration_id,
            same_snapshot=same_snapshot,
            same_content=same_content,
            same_versions=left.versions == right.versions,
            timestamp_changed=left.captured_at != right.captured_at,
            changed_keys=changed,
            added_keys=tuple(sorted(right_keys - left_keys)),
            removed_keys=tuple(sorted(left_keys - right_keys)),
            compatibility_changed=(
                left.compatibility_report != right.compatibility_report
            ),
            validation_changed=left.validation_report != right.validation_report,
            summary=(
                f"Runtime configurations are "
                f"{'identical' if same_snapshot else 'different'}; "
                f"{len(changed)} values changed, "
                f"{len(right_keys - left_keys)} added, and "
                f"{len(left_keys - right_keys)} removed."
            ),
        )


def build_runtime_configuration_registry(
    *,
    current_values: Mapping[str, object] | None = None,
) -> RuntimeConfigurationRegistry:
    """Build the default passive registry with optional retained values."""

    registry = RuntimeConfigurationRegistry(
        entries=default_runtime_configuration_entries(),
    )
    return registry.with_values(current_values) if current_values else registry


__all__ = [
    "RUNTIME_CONFIGURATION_COMPATIBILITY_VERSION",
    "RUNTIME_CONFIGURATION_SCHEMA_VERSION",
    "RUNTIME_CONFIGURATION_VERSION",
    "RUNTIME_PROFILE_REGISTRY_VERSION",
    "RuntimeConfigurationCompatibilityReport",
    "RuntimeConfigurationCompatibilityStatus",
    "RuntimeConfigurationComparison",
    "RuntimeConfigurationEntry",
    "RuntimeConfigurationRegistry",
    "RuntimeConfigurationSnapshot",
    "RuntimeConfigurationSummary",
    "RuntimeConfigurationValidationReport",
    "RuntimeConfigurationValidationStatus",
    "RuntimeConfigurationVersions",
    "build_runtime_configuration_registry",
    "default_runtime_configuration_entries",
]
