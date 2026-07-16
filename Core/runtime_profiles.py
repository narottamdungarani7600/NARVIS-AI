"""Immutable deterministic runtime operating-profile metadata.

Profiles reference retained runtime metadata only.  They never apply
configuration, resolve services, invoke providers or AI models, perform I/O,
use networking, alter lifecycle state, or enter Trusted Execution.
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


RUNTIME_PROFILE_REGISTRY_VERSION = "1.5.7"
RUNTIME_PROFILE_SCHEMA_VERSION = "1.0"
RUNTIME_PROFILE_COMPATIBILITY_VERSION = "1.5"

_PROFILE_ID_PREFIX = "runtime-profile-"
_REGISTRY_ID_PREFIX = "runtime-profile-registry-"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_NUMERIC_VERSION_PATTERN = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][A-Za-z0-9._-]+)?$"
)
_LOGICAL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class RuntimeProfileValidationStatus(str, Enum):
    """Validation states for profile registries and snapshots."""

    VALID = "valid"
    INVALID = "invalid"


class RuntimeProfileCompatibilityStatus(str, Enum):
    """Compatibility states for an operating profile."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class RuntimeProfileReadiness(str, Enum):
    """Metadata-only operating-profile readiness states."""

    READY = "ready"
    PARTIAL = "partial"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"


class RuntimeProfileReferenceKind(str, Enum):
    """Typed reference targets retained by a runtime profile."""

    CONFIGURATION = "configuration"
    METADATA = "metadata"
    CAPABILITY = "capability"
    FEATURE = "feature"


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


def _optional_text(
    value: object,
    name: str,
    *,
    maximum: int = 512,
) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=maximum)


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
    raise TypeError(f"unsupported profile export value: {type(value).__name__}")


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
    raise TypeError(f"unsupported profile export value: {type(value).__name__}")


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _content_identifier(value: object, prefix: str, name: str) -> str:
    identifier = _text(value, name, maximum=160)
    if not identifier.startswith(prefix):
        raise ValueError(f"{name} must use the required prefix")
    digest = identifier.removeprefix(prefix)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{name} must contain a SHA-256 digest")
    return identifier


@dataclass(slots=True, frozen=True)
class RuntimeProfileReference:
    """Immutable reference to one retained runtime metadata surface."""

    kind: RuntimeProfileReferenceKind
    reference_id: str | None
    version: str | None
    content_hash: str | None
    available: bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RuntimeProfileReferenceKind):
            raise TypeError("kind must be a RuntimeProfileReferenceKind")
        if not isinstance(self.available, bool):
            raise TypeError("available must be a bool")
        reference_id = _optional_text(
            self.reference_id,
            "reference_id",
            maximum=160,
        )
        version = (
            _version(self.version, "reference version")
            if self.version is not None
            else None
        )
        content_hash = _optional_text(
            self.content_hash,
            "content_hash",
            maximum=64,
        )
        if content_hash is not None and (
            len(content_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in content_hash
            )
        ):
            raise ValueError("reference content_hash must be a SHA-256 digest")
        if self.available and (
            reference_id is None or version is None or content_hash is None
        ):
            raise ValueError("available profile references require id, version, and hash")
        if not self.available and any(
            value is not None for value in (reference_id, content_hash)
        ):
            raise ValueError("unavailable profile references cannot claim retained content")
        object.__setattr__(self, "reference_id", reference_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_hash", content_hash)

    @classmethod
    def unavailable(
        cls,
        kind: RuntimeProfileReferenceKind,
        *,
        version: str | None = None,
    ) -> RuntimeProfileReference:
        """Return an explicit unavailable metadata reference."""

        return cls(
            kind=kind,
            reference_id=None,
            version=version,
            content_hash=None,
            available=False,
        )


def build_runtime_profile_reference(
    kind: RuntimeProfileReferenceKind,
    *,
    version: str,
    content: object,
    reference_id: str | None = None,
    content_hash: str | None = None,
) -> RuntimeProfileReference:
    """Build a deterministic reference without invoking the referenced object."""

    if not isinstance(kind, RuntimeProfileReferenceKind):
        raise TypeError("kind must be a RuntimeProfileReferenceKind")
    digest = content_hash or _digest(content)
    return RuntimeProfileReference(
        kind=kind,
        reference_id=reference_id or f"{kind.value}-{digest}",
        version=version,
        content_hash=digest,
        available=True,
    )


@dataclass(slots=True, frozen=True)
class RuntimeProfileDescriptor:
    """Immutable logical runtime operating-profile description."""

    id: str
    name: str
    version: str
    category: str
    description: str
    minimum_runtime_version: str
    maximum_runtime_version: str

    def __post_init__(self) -> None:
        profile_id = _text(self.id, "profile id", maximum=128)
        if _LOGICAL_ID_PATTERN.fullmatch(profile_id) is None:
            raise ValueError("profile id must use normalized dotted identifiers")
        _text(self.name, "profile name", maximum=128)
        _version(self.version, "profile version")
        _text(self.category, "profile category", maximum=128)
        _text(self.description, "profile description", maximum=2000)
        _version(self.minimum_runtime_version, "minimum_runtime_version")
        _version(self.maximum_runtime_version, "maximum_runtime_version")


@dataclass(slots=True, frozen=True)
class RuntimeProfileCompatibilityMetadata:
    """Immutable compatibility result for one profile and runtime version."""

    status: RuntimeProfileCompatibilityStatus
    descriptor_id: str
    profile_version: str
    runtime_version: str
    minimum_runtime_version: str
    maximum_runtime_version: str
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeProfileCompatibilityStatus):
            raise TypeError("status must be a RuntimeProfileCompatibilityStatus")
        _text(self.descriptor_id, "descriptor_id", maximum=128)
        for name in (
            "profile_version",
            "runtime_version",
            "minimum_runtime_version",
            "maximum_runtime_version",
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
        """Return whether the profile supports the runtime version."""

        return self.status is RuntimeProfileCompatibilityStatus.COMPATIBLE


@dataclass(slots=True, frozen=True)
class RuntimeProfileReadinessMetadata:
    """Immutable metadata-only readiness for one operating profile."""

    state: RuntimeProfileReadiness
    descriptor_id: str
    available_reference_count: int
    required_reference_count: int
    issues: tuple[str, ...]
    summary: str
    calculated_from_metadata: bool = True
    active_probes: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuntimeProfileReadiness):
            raise TypeError("state must be a RuntimeProfileReadiness")
        _text(self.descriptor_id, "descriptor_id", maximum=128)
        for name in ("available_reference_count", "required_reference_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.available_reference_count > self.required_reference_count:
            raise ValueError("available references cannot exceed required references")
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "readiness issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        _text(self.summary, "summary", maximum=2000)
        if self.calculated_from_metadata is not True:
            raise ValueError("profile readiness must be metadata-derived")
        if self.active_probes is not False:
            raise ValueError("profile readiness cannot use active probes")
        object.__setattr__(self, "issues", issues)

    @property
    def ready(self) -> bool:
        """Return whether the profile is fully ready."""

        return self.state is RuntimeProfileReadiness.READY


@dataclass(slots=True, frozen=True)
class RuntimeProfileSource:
    """One same-timestamp immutable reference set used for profile capture."""

    runtime_version: str
    readiness: RuntimeProfileReadiness
    readiness_issues: tuple[str, ...]
    configuration_reference: RuntimeProfileReference
    metadata_reference: RuntimeProfileReference
    capability_reference: RuntimeProfileReference
    feature_reference: RuntimeProfileReference
    captured_at: datetime

    def __post_init__(self) -> None:
        _version(self.runtime_version, "runtime_version")
        if not isinstance(self.readiness, RuntimeProfileReadiness):
            raise TypeError("readiness must be a RuntimeProfileReadiness")
        issues = tuple(self.readiness_issues)
        for issue in issues:
            _text(issue, "readiness issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("readiness_issues must use unique deterministic ordering")
        expected = (
            (
                self.configuration_reference,
                RuntimeProfileReferenceKind.CONFIGURATION,
            ),
            (self.metadata_reference, RuntimeProfileReferenceKind.METADATA),
            (self.capability_reference, RuntimeProfileReferenceKind.CAPABILITY),
            (self.feature_reference, RuntimeProfileReferenceKind.FEATURE),
        )
        for reference, kind in expected:
            if not isinstance(reference, RuntimeProfileReference):
                raise TypeError("profile references must be RuntimeProfileReference values")
            if reference.kind is not kind:
                raise ValueError(f"{kind.value} reference kind must match its field")
        _time(self.captured_at, "captured_at")
        object.__setattr__(self, "readiness_issues", issues)

    @property
    def references(self) -> tuple[RuntimeProfileReference, ...]:
        """Return references in deterministic kind ordering."""

        return tuple(
            sorted(
                (
                    self.configuration_reference,
                    self.metadata_reference,
                    self.capability_reference,
                    self.feature_reference,
                ),
                key=lambda item: item.kind.value,
            )
        )


@dataclass(slots=True, frozen=True)
class RuntimeProfileValidationReport:
    """Deterministic validation report for a profile registry capture."""

    status: RuntimeProfileValidationStatus
    profile_count: int
    profile_ids: tuple[str, ...]
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeProfileValidationStatus):
            raise TypeError("status must be a RuntimeProfileValidationStatus")
        if (
            isinstance(self.profile_count, bool)
            or not isinstance(self.profile_count, int)
            or self.profile_count < 0
        ):
            raise ValueError("profile_count must be a non-negative integer")
        profile_ids = _identifiers(self.profile_ids, "profile_ids")
        if self.profile_count != len(profile_ids):
            raise ValueError("profile_count must match profile_ids")
        issues = tuple(self.issues)
        for issue in issues:
            _text(issue, "profile validation issue", maximum=2000)
        if issues != tuple(sorted(set(issues))):
            raise ValueError("issues must use unique deterministic ordering")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "profile_ids", profile_ids)
        object.__setattr__(self, "issues", issues)

    @property
    def valid(self) -> bool:
        """Return whether the profile registry is valid."""

        return self.status is RuntimeProfileValidationStatus.VALID


@dataclass(slots=True, frozen=True)
class RuntimeProfileSnapshotComparison:
    """Deterministic comparison between two immutable profile snapshots."""

    left_profile_id: str
    right_profile_id: str
    same_snapshot: bool
    same_content: bool
    same_descriptor: bool
    timestamp_changed: bool
    changed_sections: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        _content_identifier(self.left_profile_id, _PROFILE_ID_PREFIX, "left_profile_id")
        _content_identifier(
            self.right_profile_id,
            _PROFILE_ID_PREFIX,
            "right_profile_id",
        )
        for name in (
            "same_snapshot",
            "same_content",
            "same_descriptor",
            "timestamp_changed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        object.__setattr__(
            self,
            "changed_sections",
            _identifiers(self.changed_sections, "changed_sections"),
        )
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeProfileSnapshot:
    """Content-addressed immutable snapshot of one resolved profile."""

    profile_id: str
    content_hash: str
    descriptor: RuntimeProfileDescriptor
    compatibility: RuntimeProfileCompatibilityMetadata
    readiness: RuntimeProfileReadinessMetadata
    configuration_reference: RuntimeProfileReference
    metadata_reference: RuntimeProfileReference
    capability_reference: RuntimeProfileReference
    feature_reference: RuntimeProfileReference
    captured_at: datetime
    deterministic: bool = True
    read_only: bool = True
    active_application: bool = False

    def __post_init__(self) -> None:
        _content_identifier(self.profile_id, _PROFILE_ID_PREFIX, "profile_id")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a SHA-256 digest")
        if self.profile_id != f"{_PROFILE_ID_PREFIX}{self.content_hash}":
            raise ValueError("profile_id must be content-addressed")
        if not isinstance(self.descriptor, RuntimeProfileDescriptor):
            raise TypeError("descriptor must be a RuntimeProfileDescriptor")
        if not isinstance(
            self.compatibility,
            RuntimeProfileCompatibilityMetadata,
        ):
            raise TypeError(
                "compatibility must be RuntimeProfileCompatibilityMetadata"
            )
        if not isinstance(self.readiness, RuntimeProfileReadinessMetadata):
            raise TypeError("readiness must be RuntimeProfileReadinessMetadata")
        if (
            self.compatibility.descriptor_id != self.descriptor.id
            or self.readiness.descriptor_id != self.descriptor.id
        ):
            raise ValueError("profile reports must match the descriptor")
        expected_references = (
            (self.configuration_reference, RuntimeProfileReferenceKind.CONFIGURATION),
            (self.metadata_reference, RuntimeProfileReferenceKind.METADATA),
            (self.capability_reference, RuntimeProfileReferenceKind.CAPABILITY),
            (self.feature_reference, RuntimeProfileReferenceKind.FEATURE),
        )
        for reference, kind in expected_references:
            if not isinstance(reference, RuntimeProfileReference):
                raise TypeError("profile references must be RuntimeProfileReference values")
            if reference.kind is not kind:
                raise ValueError("profile reference kind must match its field")
        _time(self.captured_at, "captured_at")
        expected_hash = _digest(self._content_payload())
        if self.content_hash != expected_hash:
            raise ValueError("profile content hash does not match snapshot content")
        if self.deterministic is not True:
            raise ValueError("runtime profiles must be deterministic")
        if self.read_only is not True:
            raise ValueError("runtime profiles must be read-only")
        if self.active_application is not False:
            raise ValueError("runtime profiles cannot apply operating state")

    @property
    def id(self) -> str:
        """Return the stable logical profile descriptor id."""

        return self.descriptor.id

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def version(self) -> str:
        return self.descriptor.version

    @property
    def category(self) -> str:
        return self.descriptor.category

    @property
    def description(self) -> str:
        return self.descriptor.description

    def _content_payload(self) -> Mapping[str, object]:
        return {
            "descriptor": self.descriptor,
            "compatibility": self.compatibility,
            "readiness": self.readiness,
            "configuration_reference": self.configuration_reference,
            "metadata_reference": self.metadata_reference,
            "capability_reference": self.capability_reference,
            "feature_reference": self.feature_reference,
        }

    def export(self) -> Mapping[str, object]:
        """Return a deeply immutable deterministic profile export."""

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
        """Return a detached mutable JSON-safe profile copy."""

        return json.loads(self.serialize())

    @classmethod
    def deserialize(cls, payload: str) -> RuntimeProfileSnapshot:
        """Rebuild and integrity-check one serialized profile snapshot."""

        if not isinstance(payload, str):
            raise TypeError("payload must be a string")
        try:
            data = json.loads(payload)
            snapshot = _profile_snapshot_from_data(data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("payload is not a valid runtime profile snapshot") from error
        return snapshot

    from_json = deserialize

    def compare(
        self,
        other: RuntimeProfileSnapshot,
    ) -> RuntimeProfileSnapshotComparison:
        """Compare this profile snapshot with another snapshot."""

        if not isinstance(other, RuntimeProfileSnapshot):
            raise TypeError("other must be a RuntimeProfileSnapshot")
        sections = (
            "capability_reference",
            "compatibility",
            "configuration_reference",
            "descriptor",
            "feature_reference",
            "metadata_reference",
            "readiness",
        )
        changed = tuple(
            name
            for name in sections
            if getattr(self, name) != getattr(other, name)
        )
        same_snapshot = self == other
        same_content = self.content_hash == other.content_hash
        return RuntimeProfileSnapshotComparison(
            left_profile_id=self.profile_id,
            right_profile_id=other.profile_id,
            same_snapshot=same_snapshot,
            same_content=same_content,
            same_descriptor=self.descriptor == other.descriptor,
            timestamp_changed=self.captured_at != other.captured_at,
            changed_sections=changed,
            summary=(
                f"Runtime profiles are "
                f"{'identical' if same_snapshot else 'different'}; "
                f"{len(changed)} sections changed."
            ),
        )


@dataclass(slots=True, frozen=True)
class RuntimeProfileRegistrySummary:
    """Aggregate immutable profile registry summary metadata."""

    profile_count: int
    category_count: int
    categories: tuple[str, ...]
    ready_profile_count: int
    partial_profile_count: int
    not_ready_profile_count: int
    unknown_profile_count: int
    compatible_profile_count: int
    incompatible_profile_count: int
    summary: str

    def __post_init__(self) -> None:
        for name in (
            "profile_count",
            "category_count",
            "ready_profile_count",
            "partial_profile_count",
            "not_ready_profile_count",
            "unknown_profile_count",
            "compatible_profile_count",
            "incompatible_profile_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        categories = _identifiers(self.categories, "categories")
        if self.category_count != len(categories):
            raise ValueError("category_count must match categories")
        if (
            self.ready_profile_count
            + self.partial_profile_count
            + self.not_ready_profile_count
            + self.unknown_profile_count
            != self.profile_count
        ):
            raise ValueError("readiness counts must match profile_count")
        if self.compatible_profile_count + self.incompatible_profile_count > self.profile_count:
            raise ValueError("compatibility counts cannot exceed profile_count")
        _text(self.summary, "summary", maximum=2000)
        object.__setattr__(self, "categories", categories)


@dataclass(slots=True, frozen=True)
class RuntimeProfileRegistryComparison:
    """Deterministic comparison between profile registry snapshots."""

    left_registry_id: str
    right_registry_id: str
    same_snapshot: bool
    same_content: bool
    timestamp_changed: bool
    added_profile_ids: tuple[str, ...]
    removed_profile_ids: tuple[str, ...]
    changed_profile_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        _content_identifier(
            self.left_registry_id,
            _REGISTRY_ID_PREFIX,
            "left_registry_id",
        )
        _content_identifier(
            self.right_registry_id,
            _REGISTRY_ID_PREFIX,
            "right_registry_id",
        )
        for name in ("same_snapshot", "same_content", "timestamp_changed"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        for name in (
            "added_profile_ids",
            "removed_profile_ids",
            "changed_profile_ids",
        ):
            object.__setattr__(self, name, _identifiers(getattr(self, name), name))
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimeProfileRegistrySnapshot:
    """Complete immutable snapshot of deterministically ordered profiles."""

    registry_id: str
    content_hash: str
    registry_version: str
    schema_version: str
    profiles: tuple[RuntimeProfileSnapshot, ...]
    validation_report: RuntimeProfileValidationReport
    profile_summary: RuntimeProfileRegistrySummary
    captured_at: datetime
    deterministic: bool = True
    read_only: bool = True
    active_application: bool = False

    def __post_init__(self) -> None:
        _content_identifier(self.registry_id, _REGISTRY_ID_PREFIX, "registry_id")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a SHA-256 digest")
        if self.registry_id != f"{_REGISTRY_ID_PREFIX}{self.content_hash}":
            raise ValueError("registry_id must be content-addressed")
        _version(self.registry_version, "registry_version")
        _version(self.schema_version, "schema_version")
        profiles = tuple(self.profiles)
        if not all(isinstance(item, RuntimeProfileSnapshot) for item in profiles):
            raise TypeError("profiles must contain RuntimeProfileSnapshot values")
        logical_ids = tuple(item.id for item in profiles)
        if logical_ids != tuple(sorted(set(logical_ids))):
            raise ValueError("profiles must use unique logical-id ordering")
        if any(item.captured_at != self.captured_at for item in profiles):
            raise ValueError("profile and registry timestamps must match")
        if not isinstance(self.validation_report, RuntimeProfileValidationReport):
            raise TypeError("validation_report must be RuntimeProfileValidationReport")
        if not isinstance(self.profile_summary, RuntimeProfileRegistrySummary):
            raise TypeError("profile_summary must be RuntimeProfileRegistrySummary")
        if self.validation_report.profile_ids != logical_ids:
            raise ValueError("validation report must describe snapshot profiles")
        if self.profile_summary.profile_count != len(profiles):
            raise ValueError("profile summary must describe every profile")
        _time(self.captured_at, "captured_at")
        expected_hash = _digest(
            {
                "registry_version": self.registry_version,
                "schema_version": self.schema_version,
                "profiles": tuple(item.profile_id for item in profiles),
            }
        )
        if self.content_hash != expected_hash:
            raise ValueError("registry content hash does not match profiles")
        if self.deterministic is not True:
            raise ValueError("profile registries must be deterministic")
        if self.read_only is not True:
            raise ValueError("profile registries must be read-only")
        if self.active_application is not False:
            raise ValueError("profile registries cannot apply operating state")
        object.__setattr__(self, "profiles", profiles)

    @property
    def summary(self) -> RuntimeProfileRegistrySummary:
        return self.profile_summary

    def get(self, profile_id: str) -> RuntimeProfileSnapshot | None:
        """Return one profile by its stable logical descriptor id."""

        _text(profile_id, "profile id", maximum=128)
        return next((item for item in self.profiles if item.id == profile_id), None)

    def export(self) -> Mapping[str, object]:
        """Return a deeply immutable deterministic registry export."""

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
        """Return a detached mutable JSON-safe registry copy."""

        return json.loads(self.serialize())

    @classmethod
    def deserialize(cls, payload: str) -> RuntimeProfileRegistrySnapshot:
        """Rebuild and integrity-check a serialized registry snapshot."""

        if not isinstance(payload, str):
            raise TypeError("payload must be a string")
        try:
            data = json.loads(payload)
            profiles = tuple(
                _profile_snapshot_from_data(item) for item in data["profiles"]
            )
            validation_data = data["validation_report"]
            summary_data = data["profile_summary"]
            snapshot = cls(
                registry_id=data["registry_id"],
                content_hash=data["content_hash"],
                registry_version=data["registry_version"],
                schema_version=data["schema_version"],
                profiles=profiles,
                validation_report=RuntimeProfileValidationReport(
                    status=RuntimeProfileValidationStatus(
                        validation_data["status"]
                    ),
                    profile_count=validation_data["profile_count"],
                    profile_ids=tuple(validation_data["profile_ids"]),
                    issues=tuple(validation_data["issues"]),
                    summary=validation_data["summary"],
                ),
                profile_summary=RuntimeProfileRegistrySummary(
                    profile_count=summary_data["profile_count"],
                    category_count=summary_data["category_count"],
                    categories=tuple(summary_data["categories"]),
                    ready_profile_count=summary_data["ready_profile_count"],
                    partial_profile_count=summary_data["partial_profile_count"],
                    not_ready_profile_count=summary_data["not_ready_profile_count"],
                    unknown_profile_count=summary_data["unknown_profile_count"],
                    compatible_profile_count=summary_data[
                        "compatible_profile_count"
                    ],
                    incompatible_profile_count=summary_data[
                        "incompatible_profile_count"
                    ],
                    summary=summary_data["summary"],
                ),
                captured_at=datetime.fromisoformat(data["captured_at"]),
                deterministic=data["deterministic"],
                read_only=data["read_only"],
                active_application=data["active_application"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("payload is not a valid profile registry snapshot") from error
        return snapshot

    from_json = deserialize

    def compare(
        self,
        other: RuntimeProfileRegistrySnapshot,
    ) -> RuntimeProfileRegistryComparison:
        """Compare this registry snapshot with another snapshot."""

        return RuntimeProfileRegistry.compare(self, other)


def _reference_from_data(data: Mapping[str, object]) -> RuntimeProfileReference:
    return RuntimeProfileReference(
        kind=RuntimeProfileReferenceKind(data["kind"]),
        reference_id=data.get("reference_id"),
        version=data.get("version"),
        content_hash=data.get("content_hash"),
        available=data["available"],
    )


def _profile_snapshot_from_data(data: Mapping[str, object]) -> RuntimeProfileSnapshot:
    descriptor_data = data["descriptor"]
    compatibility_data = data["compatibility"]
    readiness_data = data["readiness"]
    return RuntimeProfileSnapshot(
        profile_id=data["profile_id"],
        content_hash=data["content_hash"],
        descriptor=RuntimeProfileDescriptor(**descriptor_data),
        compatibility=RuntimeProfileCompatibilityMetadata(
            status=RuntimeProfileCompatibilityStatus(compatibility_data["status"]),
            descriptor_id=compatibility_data["descriptor_id"],
            profile_version=compatibility_data["profile_version"],
            runtime_version=compatibility_data["runtime_version"],
            minimum_runtime_version=compatibility_data["minimum_runtime_version"],
            maximum_runtime_version=compatibility_data["maximum_runtime_version"],
            issues=tuple(compatibility_data["issues"]),
            summary=compatibility_data["summary"],
        ),
        readiness=RuntimeProfileReadinessMetadata(
            state=RuntimeProfileReadiness(readiness_data["state"]),
            descriptor_id=readiness_data["descriptor_id"],
            available_reference_count=readiness_data[
                "available_reference_count"
            ],
            required_reference_count=readiness_data[
                "required_reference_count"
            ],
            issues=tuple(readiness_data["issues"]),
            summary=readiness_data["summary"],
            calculated_from_metadata=readiness_data["calculated_from_metadata"],
            active_probes=readiness_data["active_probes"],
        ),
        configuration_reference=_reference_from_data(
            data["configuration_reference"]
        ),
        metadata_reference=_reference_from_data(data["metadata_reference"]),
        capability_reference=_reference_from_data(data["capability_reference"]),
        feature_reference=_reference_from_data(data["feature_reference"]),
        captured_at=datetime.fromisoformat(data["captured_at"]),
        deterministic=data["deterministic"],
        read_only=data["read_only"],
        active_application=data["active_application"],
    )


def default_runtime_profile_descriptors() -> tuple[RuntimeProfileDescriptor, ...]:
    """Return built-in passive Version 1.5 operating profiles."""

    return (
        RuntimeProfileDescriptor(
            id="runtime.default",
            name="Default Runtime Profile",
            version="1.0",
            category="runtime",
            description="Describes the composed default NARVIS runtime metadata.",
            minimum_runtime_version="1.4",
            maximum_runtime_version="1.5",
        ),
        RuntimeProfileDescriptor(
            id="runtime.observability",
            name="Runtime Observability Profile",
            version="1.0",
            category="observability",
            description="Describes passive runtime inspection metadata surfaces.",
            minimum_runtime_version="1.4",
            maximum_runtime_version="1.5",
        ),
    )


@dataclass(slots=True, frozen=True)
class RuntimeProfileRegistry:
    """Immutable registry of logical runtime operating-profile descriptors."""

    descriptors: tuple[RuntimeProfileDescriptor, ...] = (
        default_runtime_profile_descriptors()
    )
    registry_version: str = RUNTIME_PROFILE_REGISTRY_VERSION
    schema_version: str = RUNTIME_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.registry_version, "registry_version")
        _version(self.schema_version, "schema_version")
        descriptors = tuple(self.descriptors)
        if not all(isinstance(item, RuntimeProfileDescriptor) for item in descriptors):
            raise TypeError("descriptors must contain RuntimeProfileDescriptor values")
        ids = tuple(item.id for item in descriptors)
        if len(set(ids)) != len(ids):
            raise ValueError("profile descriptor ids must be unique")
        object.__setattr__(
            self,
            "descriptors",
            tuple(sorted(descriptors, key=lambda item: item.id)),
        )

    def get(self, profile_id: str) -> RuntimeProfileDescriptor | None:
        """Return one logical profile descriptor."""

        _text(profile_id, "profile id", maximum=128)
        return next((item for item in self.descriptors if item.id == profile_id), None)

    def register(self, descriptor: RuntimeProfileDescriptor) -> RuntimeProfileRegistry:
        """Return a new registry containing one additional descriptor."""

        if not isinstance(descriptor, RuntimeProfileDescriptor):
            raise TypeError("descriptor must be a RuntimeProfileDescriptor")
        if self.get(descriptor.id) is not None:
            raise ValueError(f"profile id is already registered: {descriptor.id}")
        return RuntimeProfileRegistry(
            descriptors=(*self.descriptors, descriptor),
            registry_version=self.registry_version,
            schema_version=self.schema_version,
        )

    def validate(
        self,
        source: RuntimeProfileSource | None = None,
    ) -> RuntimeProfileValidationReport:
        """Return deterministic profile and optional reference validation."""

        if source is not None and not isinstance(source, RuntimeProfileSource):
            raise TypeError("source must be a RuntimeProfileSource")
        issues: set[str] = set()
        if not self.descriptors:
            issues.add("runtime profile registry must contain at least one profile")
        for descriptor in self.descriptors:
            minimum = _numeric_version(descriptor.minimum_runtime_version)
            maximum = _numeric_version(descriptor.maximum_runtime_version)
            if minimum is None or maximum is None:
                issues.add(
                    f"{descriptor.id}: compatibility range must use numeric versions"
                )
            elif minimum > maximum:
                issues.add(
                    f"{descriptor.id}: minimum runtime version cannot exceed maximum"
                )
        if source is not None:
            for reference in source.references:
                if not reference.available:
                    issues.add(f"{reference.kind.value} reference is unavailable")
        status = (
            RuntimeProfileValidationStatus.INVALID
            if issues
            else RuntimeProfileValidationStatus.VALID
        )
        ids = tuple(item.id for item in self.descriptors)
        return RuntimeProfileValidationReport(
            status=status,
            profile_count=len(ids),
            profile_ids=ids,
            issues=tuple(sorted(issues)),
            summary=(
                f"Runtime profile validation is {status.value}: "
                f"{len(ids)} profiles and {len(issues)} issues."
            ),
        )

    @staticmethod
    def verify_compatibility(
        descriptor: RuntimeProfileDescriptor,
        runtime_version: str,
    ) -> RuntimeProfileCompatibilityMetadata:
        """Verify one profile compatibility range against a runtime version."""

        if not isinstance(descriptor, RuntimeProfileDescriptor):
            raise TypeError("descriptor must be a RuntimeProfileDescriptor")
        runtime_text = _version(runtime_version, "runtime_version")
        runtime = _numeric_version(runtime_text)
        minimum = _numeric_version(descriptor.minimum_runtime_version)
        maximum = _numeric_version(descriptor.maximum_runtime_version)
        issues: set[str] = set()
        if runtime is None or minimum is None or maximum is None:
            status = RuntimeProfileCompatibilityStatus.UNKNOWN
            issues.add("profile compatibility requires numeric version syntax")
        else:
            if minimum > maximum:
                issues.add("profile minimum runtime version exceeds maximum")
            if runtime < minimum:
                issues.add("runtime version is older than the profile minimum")
            if runtime > maximum:
                issues.add("runtime version is newer than the profile maximum")
            status = (
                RuntimeProfileCompatibilityStatus.INCOMPATIBLE
                if issues
                else RuntimeProfileCompatibilityStatus.COMPATIBLE
            )
        return RuntimeProfileCompatibilityMetadata(
            status=status,
            descriptor_id=descriptor.id,
            profile_version=descriptor.version,
            runtime_version=runtime_text,
            minimum_runtime_version=descriptor.minimum_runtime_version,
            maximum_runtime_version=descriptor.maximum_runtime_version,
            issues=tuple(sorted(issues)),
            summary=(
                f"Profile {descriptor.id} compatibility is {status.value} "
                f"for runtime {runtime_text}."
            ),
        )

    @staticmethod
    def _readiness(
        descriptor: RuntimeProfileDescriptor,
        source: RuntimeProfileSource,
        compatibility: RuntimeProfileCompatibilityMetadata,
    ) -> RuntimeProfileReadinessMetadata:
        issues = set(source.readiness_issues)
        missing = tuple(
            reference.kind.value
            for reference in source.references
            if not reference.available
        )
        issues.update(f"{kind} reference is unavailable" for kind in missing)
        issues.update(compatibility.issues)
        if compatibility.status is RuntimeProfileCompatibilityStatus.INCOMPATIBLE:
            state = RuntimeProfileReadiness.NOT_READY
        elif compatibility.status is RuntimeProfileCompatibilityStatus.UNKNOWN:
            state = RuntimeProfileReadiness.UNKNOWN
        elif source.readiness is RuntimeProfileReadiness.NOT_READY:
            state = RuntimeProfileReadiness.NOT_READY
        elif source.readiness is RuntimeProfileReadiness.UNKNOWN:
            state = RuntimeProfileReadiness.UNKNOWN
        elif missing:
            state = RuntimeProfileReadiness.PARTIAL
        else:
            state = source.readiness
        available = sum(reference.available for reference in source.references)
        return RuntimeProfileReadinessMetadata(
            state=state,
            descriptor_id=descriptor.id,
            available_reference_count=available,
            required_reference_count=len(source.references),
            issues=tuple(sorted(issues)),
            summary=(
                f"Profile {descriptor.id} readiness is {state.value}: "
                f"{available} of {len(source.references)} references available."
            ),
        )

    def snapshot(self, source: RuntimeProfileSource) -> RuntimeProfileRegistrySnapshot:
        """Resolve all descriptors into immutable content-addressed profiles."""

        if not isinstance(source, RuntimeProfileSource):
            raise TypeError("source must be a RuntimeProfileSource")
        profiles: list[RuntimeProfileSnapshot] = []
        for descriptor in self.descriptors:
            compatibility = self.verify_compatibility(
                descriptor,
                source.runtime_version,
            )
            readiness = self._readiness(descriptor, source, compatibility)
            content_payload = {
                "descriptor": descriptor,
                "compatibility": compatibility,
                "readiness": readiness,
                "configuration_reference": source.configuration_reference,
                "metadata_reference": source.metadata_reference,
                "capability_reference": source.capability_reference,
                "feature_reference": source.feature_reference,
            }
            content_hash = _digest(content_payload)
            profiles.append(
                RuntimeProfileSnapshot(
                    profile_id=f"{_PROFILE_ID_PREFIX}{content_hash}",
                    content_hash=content_hash,
                    descriptor=descriptor,
                    compatibility=compatibility,
                    readiness=readiness,
                    configuration_reference=source.configuration_reference,
                    metadata_reference=source.metadata_reference,
                    capability_reference=source.capability_reference,
                    feature_reference=source.feature_reference,
                    captured_at=source.captured_at,
                )
            )
        profile_values = tuple(profiles)
        validation = self.validate(source)
        categories = tuple(sorted({item.category for item in profile_values}))
        readiness_counts = {
            state: sum(item.readiness.state is state for item in profile_values)
            for state in RuntimeProfileReadiness
        }
        compatible = sum(
            item.compatibility.status
            is RuntimeProfileCompatibilityStatus.COMPATIBLE
            for item in profile_values
        )
        incompatible = sum(
            item.compatibility.status
            is RuntimeProfileCompatibilityStatus.INCOMPATIBLE
            for item in profile_values
        )
        summary = RuntimeProfileRegistrySummary(
            profile_count=len(profile_values),
            category_count=len(categories),
            categories=categories,
            ready_profile_count=readiness_counts[RuntimeProfileReadiness.READY],
            partial_profile_count=readiness_counts[RuntimeProfileReadiness.PARTIAL],
            not_ready_profile_count=(
                readiness_counts[RuntimeProfileReadiness.NOT_READY]
            ),
            unknown_profile_count=(
                readiness_counts[RuntimeProfileReadiness.UNKNOWN]
            ),
            compatible_profile_count=compatible,
            incompatible_profile_count=incompatible,
            summary=(
                f"Runtime profile registry contains {len(profile_values)} profiles; "
                f"{readiness_counts[RuntimeProfileReadiness.READY]} are ready."
            ),
        )
        content_hash = _digest(
            {
                "registry_version": self.registry_version,
                "schema_version": self.schema_version,
                "profiles": tuple(item.profile_id for item in profile_values),
            }
        )
        return RuntimeProfileRegistrySnapshot(
            registry_id=f"{_REGISTRY_ID_PREFIX}{content_hash}",
            content_hash=content_hash,
            registry_version=self.registry_version,
            schema_version=self.schema_version,
            profiles=profile_values,
            validation_report=validation,
            profile_summary=summary,
            captured_at=source.captured_at,
        )

    def export(self, source: RuntimeProfileSource) -> Mapping[str, object]:
        """Resolve and deeply freeze a deterministic registry export."""

        return self.snapshot(source).export()

    @staticmethod
    def compare(
        left: RuntimeProfileRegistrySnapshot,
        right: RuntimeProfileRegistrySnapshot,
    ) -> RuntimeProfileRegistryComparison:
        """Return a deterministic comparison of two registry snapshots."""

        if not isinstance(left, RuntimeProfileRegistrySnapshot) or not isinstance(
            right,
            RuntimeProfileRegistrySnapshot,
        ):
            raise TypeError(
                "left and right must be RuntimeProfileRegistrySnapshot values"
            )
        left_profiles = {item.id: item for item in left.profiles}
        right_profiles = {item.id: item for item in right.profiles}
        left_ids = set(left_profiles)
        right_ids = set(right_profiles)
        changed = tuple(
            sorted(
                profile_id
                for profile_id in left_ids & right_ids
                if left_profiles[profile_id].content_hash
                != right_profiles[profile_id].content_hash
            )
        )
        same_snapshot = left == right
        same_content = left.content_hash == right.content_hash
        return RuntimeProfileRegistryComparison(
            left_registry_id=left.registry_id,
            right_registry_id=right.registry_id,
            same_snapshot=same_snapshot,
            same_content=same_content,
            timestamp_changed=left.captured_at != right.captured_at,
            added_profile_ids=tuple(sorted(right_ids - left_ids)),
            removed_profile_ids=tuple(sorted(left_ids - right_ids)),
            changed_profile_ids=changed,
            summary=(
                f"Runtime profile registries are "
                f"{'identical' if same_snapshot else 'different'}; "
                f"{len(changed)} profiles changed."
            ),
        )


def build_runtime_profile_registry() -> RuntimeProfileRegistry:
    """Build the default passive Runtime Profile Registry."""

    return RuntimeProfileRegistry()


__all__ = [
    "RUNTIME_PROFILE_COMPATIBILITY_VERSION",
    "RUNTIME_PROFILE_REGISTRY_VERSION",
    "RUNTIME_PROFILE_SCHEMA_VERSION",
    "RuntimeProfileCompatibilityMetadata",
    "RuntimeProfileCompatibilityStatus",
    "RuntimeProfileDescriptor",
    "RuntimeProfileReadiness",
    "RuntimeProfileReadinessMetadata",
    "RuntimeProfileReference",
    "RuntimeProfileReferenceKind",
    "RuntimeProfileRegistry",
    "RuntimeProfileRegistryComparison",
    "RuntimeProfileRegistrySnapshot",
    "RuntimeProfileRegistrySummary",
    "RuntimeProfileSnapshot",
    "RuntimeProfileSnapshotComparison",
    "RuntimeProfileSource",
    "RuntimeProfileValidationReport",
    "RuntimeProfileValidationStatus",
    "build_runtime_profile_reference",
    "build_runtime_profile_registry",
    "default_runtime_profile_descriptors",
]
