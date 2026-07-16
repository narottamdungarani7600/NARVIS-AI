"""Immutable deterministic runtime policy metadata.

Policies in this module describe passive runtime expectations only. They do
not authorize actions, evaluate requests, resolve services, execute providers
or AI models, perform I/O, use networking, or enter Trusted Execution.
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


RUNTIME_POLICY_REGISTRY_VERSION = "1.5.8"
RUNTIME_POLICY_SCHEMA_VERSION = "1.0"
RUNTIME_POLICY_COMPATIBILITY_VERSION = "1.5"

_POLICY_ID_PREFIX = "runtime-policy-"
_REGISTRY_ID_PREFIX = "runtime-policy-registry-"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_NUMERIC_VERSION_PATTERN = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][A-Za-z0-9._-]+)?$"
)
_LOGICAL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class RuntimePolicyValidationStatus(str, Enum):
    """Validation states for policy descriptors and registries."""

    VALID = "valid"
    INVALID = "invalid"


class RuntimePolicyCompatibilityStatus(str, Enum):
    """Compatibility states for one policy and runtime version."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class RuntimePolicyReadiness(str, Enum):
    """Metadata-only policy readiness states."""

    READY = "ready"
    PARTIAL = "partial"
    NOT_READY = "not_ready"
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


def _priority(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("priority must be a non-negative integer")
    return value


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of identifiers")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    for value in result:
        identifier = _text(value, name, maximum=128)
        if _LOGICAL_ID_PATTERN.fullmatch(identifier) is None:
            raise ValueError(f"{name} must contain normalized identifiers")
    if result != tuple(sorted(set(result))):
        raise ValueError(f"{name} must use unique deterministic ordering")
    return result


def _ordered_identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of identifiers")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of identifiers") from error
    for value in result:
        _text(value, name, maximum=128)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _issues(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of issue strings")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be an iterable of issue strings") from error
    for value in result:
        _text(value, name, maximum=2000)
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
        return {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(value[key])
            for key in sorted(value, key=str)
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise TypeError(f"unsupported policy export value: {type(value).__name__}")


def _immutable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return MappingProxyType(
            {
                item.name: _immutable(getattr(value, item.name))
                for item in fields(value)
            }
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
    raise TypeError(f"unsupported policy export value: {type(value).__name__}")


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
class RuntimePolicyDescriptor:
    """Immutable logical runtime policy descriptor."""

    id: str
    name: str
    version: str
    description: str
    category: str
    scope: str
    priority: int
    minimum_runtime_version: str
    maximum_runtime_version: str
    depends_on: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        policy_id = _text(self.id, "policy id", maximum=128)
        if _LOGICAL_ID_PATTERN.fullmatch(policy_id) is None:
            raise ValueError("policy id must use normalized dotted identifiers")
        _text(self.name, "policy name", maximum=128)
        _version(self.version, "policy version")
        _text(self.description, "policy description", maximum=2000)
        for name in ("category", "scope"):
            value = _text(getattr(self, name), name, maximum=128)
            if _LOGICAL_ID_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must use a normalized identifier")
        _priority(self.priority)
        _version(self.minimum_runtime_version, "minimum_runtime_version")
        _version(self.maximum_runtime_version, "maximum_runtime_version")
        object.__setattr__(
            self,
            "depends_on",
            _identifiers(self.depends_on, "depends_on"),
        )
        object.__setattr__(
            self,
            "optional_dependencies",
            _identifiers(
                self.optional_dependencies,
                "optional_dependencies",
            ),
        )


@dataclass(slots=True, frozen=True)
class RuntimePolicyCompatibilityMetadata:
    """Immutable runtime-version compatibility metadata for one policy."""

    policy_id: str
    status: RuntimePolicyCompatibilityStatus
    runtime_version: str
    minimum_runtime_version: str
    maximum_runtime_version: str
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id", maximum=128)
        if not isinstance(self.status, RuntimePolicyCompatibilityStatus):
            raise TypeError("status must be a RuntimePolicyCompatibilityStatus")
        for name in (
            "runtime_version",
            "minimum_runtime_version",
            "maximum_runtime_version",
        ):
            object.__setattr__(self, name, _version(getattr(self, name), name))
        object.__setattr__(self, "issues", _issues(self.issues, "issues"))
        _text(self.summary, "summary", maximum=2000)

    @property
    def compatible(self) -> bool:
        return self.status is RuntimePolicyCompatibilityStatus.COMPATIBLE


@dataclass(slots=True, frozen=True)
class RuntimePolicyDependencyMetadata:
    """Immutable required, optional, reverse, and missing dependency metadata."""

    policy_id: str
    required_dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    required_by: tuple[str, ...]
    missing_required_dependencies: tuple[str, ...]
    missing_optional_dependencies: tuple[str, ...]
    circular: bool
    summary: str

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id", maximum=128)
        for name in (
            "required_dependencies",
            "optional_dependencies",
            "required_by",
            "missing_required_dependencies",
            "missing_optional_dependencies",
        ):
            object.__setattr__(
                self,
                name,
                _identifiers(getattr(self, name), name),
            )
        if not isinstance(self.circular, bool):
            raise TypeError("circular must be a bool")
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimePolicyValidationMetadata:
    """Immutable semantic validation metadata for one policy."""

    policy_id: str
    status: RuntimePolicyValidationStatus
    checked_fields: tuple[str, ...]
    issues: tuple[str, ...]
    summary: str
    calculated_from_metadata: bool = True
    active_enforcement: bool = False

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id", maximum=128)
        if not isinstance(self.status, RuntimePolicyValidationStatus):
            raise TypeError("status must be a RuntimePolicyValidationStatus")
        object.__setattr__(
            self,
            "checked_fields",
            _identifiers(self.checked_fields, "checked_fields"),
        )
        object.__setattr__(self, "issues", _issues(self.issues, "issues"))
        _text(self.summary, "summary", maximum=2000)
        if self.calculated_from_metadata is not True:
            raise ValueError("policy validation must be metadata-derived")
        if self.active_enforcement is not False:
            raise ValueError("policy validation cannot enforce runtime behavior")

    @property
    def valid(self) -> bool:
        return self.status is RuntimePolicyValidationStatus.VALID


@dataclass(slots=True, frozen=True)
class RuntimePolicyReadinessMetadata:
    """Immutable dependency-aware, metadata-only policy readiness."""

    policy_id: str
    state: RuntimePolicyReadiness
    required_dependency_count: int
    available_required_dependency_count: int
    issues: tuple[str, ...]
    summary: str
    calculated_from_metadata: bool = True
    active_evaluation: bool = False

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id", maximum=128)
        if not isinstance(self.state, RuntimePolicyReadiness):
            raise TypeError("state must be a RuntimePolicyReadiness")
        for name in (
            "required_dependency_count",
            "available_required_dependency_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            self.available_required_dependency_count
            > self.required_dependency_count
        ):
            raise ValueError("available dependencies cannot exceed required dependencies")
        object.__setattr__(self, "issues", _issues(self.issues, "issues"))
        _text(self.summary, "summary", maximum=2000)
        if self.calculated_from_metadata is not True:
            raise ValueError("policy readiness must be metadata-derived")
        if self.active_evaluation is not False:
            raise ValueError("policy readiness cannot actively evaluate behavior")

    @property
    def ready(self) -> bool:
        return self.state is RuntimePolicyReadiness.READY


@dataclass(slots=True, frozen=True)
class RuntimePolicySource:
    """Same-timestamp passive metadata input for one policy registry capture."""

    runtime_version: str
    runtime_readiness: RuntimePolicyReadiness
    readiness_issues: tuple[str, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        _version(self.runtime_version, "runtime_version")
        if not isinstance(self.runtime_readiness, RuntimePolicyReadiness):
            raise TypeError("runtime_readiness must be a RuntimePolicyReadiness")
        object.__setattr__(
            self,
            "readiness_issues",
            _issues(self.readiness_issues, "readiness_issues"),
        )
        _time(self.captured_at, "captured_at")


@dataclass(slots=True, frozen=True)
class RuntimePolicySnapshotComparison:
    """Deterministic comparison between two policy snapshots."""

    left_policy_id: str
    right_policy_id: str
    same_snapshot: bool
    same_content: bool
    same_descriptor: bool
    timestamp_changed: bool
    changed_sections: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        _content_identifier(self.left_policy_id, _POLICY_ID_PREFIX, "left_policy_id")
        _content_identifier(
            self.right_policy_id,
            _POLICY_ID_PREFIX,
            "right_policy_id",
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
class RuntimePolicySnapshot:
    """Content-addressed immutable resolved policy metadata."""

    policy_id: str
    content_hash: str
    descriptor: RuntimePolicyDescriptor
    compatibility: RuntimePolicyCompatibilityMetadata
    readiness: RuntimePolicyReadinessMetadata
    dependencies: RuntimePolicyDependencyMetadata
    validation: RuntimePolicyValidationMetadata
    captured_at: datetime
    deterministic: bool = True
    read_only: bool = True
    active_enforcement: bool = False

    def __post_init__(self) -> None:
        _content_identifier(self.policy_id, _POLICY_ID_PREFIX, "policy_id")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a SHA-256 digest")
        if self.policy_id != f"{_POLICY_ID_PREFIX}{self.content_hash}":
            raise ValueError("policy_id must be content-addressed")
        expected_types = (
            ("descriptor", self.descriptor, RuntimePolicyDescriptor),
            (
                "compatibility",
                self.compatibility,
                RuntimePolicyCompatibilityMetadata,
            ),
            ("readiness", self.readiness, RuntimePolicyReadinessMetadata),
            (
                "dependencies",
                self.dependencies,
                RuntimePolicyDependencyMetadata,
            ),
            ("validation", self.validation, RuntimePolicyValidationMetadata),
        )
        for name, value, expected_type in expected_types:
            if not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
        logical_id = self.descriptor.id
        if any(
            value != logical_id
            for value in (
                self.compatibility.policy_id,
                self.readiness.policy_id,
                self.dependencies.policy_id,
                self.validation.policy_id,
            )
        ):
            raise ValueError("policy metadata must match the descriptor id")
        _time(self.captured_at, "captured_at")
        if self.content_hash != _digest(self._content_payload()):
            raise ValueError("policy content hash does not match snapshot content")
        if self.deterministic is not True or self.read_only is not True:
            raise ValueError("policy snapshots must be deterministic and read-only")
        if self.active_enforcement is not False:
            raise ValueError("policy snapshots cannot enforce runtime behavior")

    @property
    def id(self) -> str:
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
    def scope(self) -> str:
        return self.descriptor.scope

    @property
    def priority(self) -> int:
        return self.descriptor.priority

    def _content_payload(self) -> Mapping[str, object]:
        return {
            "descriptor": self.descriptor,
            "compatibility": self.compatibility,
            "readiness": self.readiness,
            "dependencies": self.dependencies,
            "validation": self.validation,
        }

    def export(self) -> Mapping[str, object]:
        return _immutable(self)

    def serialize(self) -> str:
        return json.dumps(
            _canonical(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    to_json = serialize

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.serialize())

    @classmethod
    def deserialize(cls, payload: str) -> RuntimePolicySnapshot:
        if not isinstance(payload, str):
            raise TypeError("payload must be a string")
        try:
            data = json.loads(payload)
            return _policy_snapshot_from_data(data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("payload is not a valid runtime policy snapshot") from error

    from_json = deserialize

    def compare(
        self,
        other: RuntimePolicySnapshot,
    ) -> RuntimePolicySnapshotComparison:
        if not isinstance(other, RuntimePolicySnapshot):
            raise TypeError("other must be a RuntimePolicySnapshot")
        sections = (
            "compatibility",
            "dependencies",
            "descriptor",
            "readiness",
            "validation",
        )
        changed = tuple(
            name for name in sections if getattr(self, name) != getattr(other, name)
        )
        return RuntimePolicySnapshotComparison(
            left_policy_id=self.policy_id,
            right_policy_id=other.policy_id,
            same_snapshot=self == other,
            same_content=self.content_hash == other.content_hash,
            same_descriptor=self.descriptor == other.descriptor,
            timestamp_changed=self.captured_at != other.captured_at,
            changed_sections=changed,
            summary=(
                f"Runtime policies are "
                f"{'identical' if self == other else 'different'}; "
                f"{len(changed)} sections changed."
            ),
        )


@dataclass(slots=True, frozen=True)
class RuntimePolicyRegistryValidationReport:
    """Aggregate deterministic policy-registry validation report."""

    status: RuntimePolicyValidationStatus
    policy_count: int
    policy_ids: tuple[str, ...]
    issues: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimePolicyValidationStatus):
            raise TypeError("status must be a RuntimePolicyValidationStatus")
        if (
            isinstance(self.policy_count, bool)
            or not isinstance(self.policy_count, int)
            or self.policy_count < 0
        ):
            raise ValueError("policy_count must be a non-negative integer")
        policy_ids = _ordered_identifiers(self.policy_ids, "policy_ids")
        if len(policy_ids) != self.policy_count:
            raise ValueError("policy_count must match policy_ids")
        object.__setattr__(self, "policy_ids", policy_ids)
        object.__setattr__(self, "issues", _issues(self.issues, "issues"))
        _text(self.summary, "summary", maximum=2000)

    @property
    def valid(self) -> bool:
        return self.status is RuntimePolicyValidationStatus.VALID


@dataclass(slots=True, frozen=True)
class RuntimePolicyRegistrySummary:
    """Aggregate immutable policy registry metadata."""

    policy_count: int
    category_count: int
    categories: tuple[str, ...]
    ready_policy_count: int
    partial_policy_count: int
    not_ready_policy_count: int
    unknown_policy_count: int
    compatible_policy_count: int
    invalid_policy_count: int
    summary: str

    def __post_init__(self) -> None:
        for name in (
            "policy_count",
            "category_count",
            "ready_policy_count",
            "partial_policy_count",
            "not_ready_policy_count",
            "unknown_policy_count",
            "compatible_policy_count",
            "invalid_policy_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        categories = _identifiers(self.categories, "categories")
        if len(categories) != self.category_count:
            raise ValueError("category_count must match categories")
        if (
            self.ready_policy_count
            + self.partial_policy_count
            + self.not_ready_policy_count
            + self.unknown_policy_count
            != self.policy_count
        ):
            raise ValueError("readiness counts must match policy_count")
        if self.compatible_policy_count > self.policy_count:
            raise ValueError("compatible_policy_count cannot exceed policy_count")
        if self.invalid_policy_count > self.policy_count:
            raise ValueError("invalid_policy_count cannot exceed policy_count")
        object.__setattr__(self, "categories", categories)
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimePolicyRegistryComparison:
    """Deterministic comparison of two policy registry snapshots."""

    left_registry_id: str
    right_registry_id: str
    same_snapshot: bool
    same_content: bool
    timestamp_changed: bool
    added_policy_ids: tuple[str, ...]
    removed_policy_ids: tuple[str, ...]
    changed_policy_ids: tuple[str, ...]
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
            "added_policy_ids",
            "removed_policy_ids",
            "changed_policy_ids",
        ):
            object.__setattr__(
                self,
                name,
                _identifiers(getattr(self, name), name),
            )
        _text(self.summary, "summary", maximum=2000)


@dataclass(slots=True, frozen=True)
class RuntimePolicyRegistrySnapshot:
    """Complete immutable deterministically ordered policy snapshot."""

    registry_id: str
    content_hash: str
    registry_version: str
    schema_version: str
    policies: tuple[RuntimePolicySnapshot, ...]
    validation_report: RuntimePolicyRegistryValidationReport
    policy_summary: RuntimePolicyRegistrySummary
    captured_at: datetime
    deterministic: bool = True
    read_only: bool = True
    active_enforcement: bool = False

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
        policies = tuple(self.policies)
        if not all(isinstance(item, RuntimePolicySnapshot) for item in policies):
            raise TypeError("policies must contain RuntimePolicySnapshot values")
        expected_order = tuple(
            sorted(policies, key=lambda item: (item.priority, item.id))
        )
        if policies != expected_order:
            raise ValueError("policies must use priority and id ordering")
        logical_ids = tuple(item.id for item in policies)
        if len(set(logical_ids)) != len(logical_ids):
            raise ValueError("policies cannot contain duplicate logical ids")
        _time(self.captured_at, "captured_at")
        if any(item.captured_at != self.captured_at for item in policies):
            raise ValueError("policy and registry timestamps must match")
        if not isinstance(
            self.validation_report,
            RuntimePolicyRegistryValidationReport,
        ):
            raise TypeError(
                "validation_report must be a RuntimePolicyRegistryValidationReport"
            )
        if not isinstance(self.policy_summary, RuntimePolicyRegistrySummary):
            raise TypeError("policy_summary must be a RuntimePolicyRegistrySummary")
        if self.validation_report.policy_ids != logical_ids:
            raise ValueError("validation report must describe snapshot policies")
        if self.policy_summary.policy_count != len(policies):
            raise ValueError("policy summary must describe every policy")
        expected_hash = _digest(
            {
                "registry_version": self.registry_version,
                "schema_version": self.schema_version,
                "policies": tuple(item.policy_id for item in policies),
            }
        )
        if self.content_hash != expected_hash:
            raise ValueError("registry content hash does not match policies")
        if self.deterministic is not True or self.read_only is not True:
            raise ValueError("policy registries must be deterministic and read-only")
        if self.active_enforcement is not False:
            raise ValueError("policy registries cannot enforce runtime behavior")
        object.__setattr__(self, "policies", policies)

    @property
    def summary(self) -> RuntimePolicyRegistrySummary:
        return self.policy_summary

    def get(self, policy_id: str) -> RuntimePolicySnapshot | None:
        _text(policy_id, "policy id", maximum=128)
        return next((item for item in self.policies if item.id == policy_id), None)

    def export(self) -> Mapping[str, object]:
        return _immutable(self)

    def serialize(self) -> str:
        return json.dumps(
            _canonical(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    to_json = serialize

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.serialize())

    @classmethod
    def deserialize(cls, payload: str) -> RuntimePolicyRegistrySnapshot:
        if not isinstance(payload, str):
            raise TypeError("payload must be a string")
        try:
            data = json.loads(payload)
            policies = tuple(
                _policy_snapshot_from_data(item) for item in data["policies"]
            )
            validation = data["validation_report"]
            summary = data["policy_summary"]
            return cls(
                registry_id=data["registry_id"],
                content_hash=data["content_hash"],
                registry_version=data["registry_version"],
                schema_version=data["schema_version"],
                policies=policies,
                validation_report=RuntimePolicyRegistryValidationReport(
                    status=RuntimePolicyValidationStatus(validation["status"]),
                    policy_count=validation["policy_count"],
                    policy_ids=tuple(validation["policy_ids"]),
                    issues=tuple(validation["issues"]),
                    summary=validation["summary"],
                ),
                policy_summary=RuntimePolicyRegistrySummary(
                    policy_count=summary["policy_count"],
                    category_count=summary["category_count"],
                    categories=tuple(summary["categories"]),
                    ready_policy_count=summary["ready_policy_count"],
                    partial_policy_count=summary["partial_policy_count"],
                    not_ready_policy_count=summary["not_ready_policy_count"],
                    unknown_policy_count=summary["unknown_policy_count"],
                    compatible_policy_count=summary["compatible_policy_count"],
                    invalid_policy_count=summary["invalid_policy_count"],
                    summary=summary["summary"],
                ),
                captured_at=datetime.fromisoformat(data["captured_at"]),
                deterministic=data["deterministic"],
                read_only=data["read_only"],
                active_enforcement=data["active_enforcement"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("payload is not a valid policy registry snapshot") from error

    from_json = deserialize

    def compare(
        self,
        other: RuntimePolicyRegistrySnapshot,
    ) -> RuntimePolicyRegistryComparison:
        return RuntimePolicyRegistry.compare(self, other)


def _policy_snapshot_from_data(data: Mapping[str, object]) -> RuntimePolicySnapshot:
    descriptor = data["descriptor"]
    compatibility = data["compatibility"]
    readiness = data["readiness"]
    dependencies = data["dependencies"]
    validation = data["validation"]
    return RuntimePolicySnapshot(
        policy_id=data["policy_id"],
        content_hash=data["content_hash"],
        descriptor=RuntimePolicyDescriptor(
            id=descriptor["id"],
            name=descriptor["name"],
            version=descriptor["version"],
            description=descriptor["description"],
            category=descriptor["category"],
            scope=descriptor["scope"],
            priority=descriptor["priority"],
            minimum_runtime_version=descriptor["minimum_runtime_version"],
            maximum_runtime_version=descriptor["maximum_runtime_version"],
            depends_on=tuple(descriptor["depends_on"]),
            optional_dependencies=tuple(descriptor["optional_dependencies"]),
        ),
        compatibility=RuntimePolicyCompatibilityMetadata(
            policy_id=compatibility["policy_id"],
            status=RuntimePolicyCompatibilityStatus(compatibility["status"]),
            runtime_version=compatibility["runtime_version"],
            minimum_runtime_version=compatibility["minimum_runtime_version"],
            maximum_runtime_version=compatibility["maximum_runtime_version"],
            issues=tuple(compatibility["issues"]),
            summary=compatibility["summary"],
        ),
        readiness=RuntimePolicyReadinessMetadata(
            policy_id=readiness["policy_id"],
            state=RuntimePolicyReadiness(readiness["state"]),
            required_dependency_count=readiness["required_dependency_count"],
            available_required_dependency_count=readiness[
                "available_required_dependency_count"
            ],
            issues=tuple(readiness["issues"]),
            summary=readiness["summary"],
            calculated_from_metadata=readiness["calculated_from_metadata"],
            active_evaluation=readiness["active_evaluation"],
        ),
        dependencies=RuntimePolicyDependencyMetadata(
            policy_id=dependencies["policy_id"],
            required_dependencies=tuple(dependencies["required_dependencies"]),
            optional_dependencies=tuple(dependencies["optional_dependencies"]),
            required_by=tuple(dependencies["required_by"]),
            missing_required_dependencies=tuple(
                dependencies["missing_required_dependencies"]
            ),
            missing_optional_dependencies=tuple(
                dependencies["missing_optional_dependencies"]
            ),
            circular=dependencies["circular"],
            summary=dependencies["summary"],
        ),
        validation=RuntimePolicyValidationMetadata(
            policy_id=validation["policy_id"],
            status=RuntimePolicyValidationStatus(validation["status"]),
            checked_fields=tuple(validation["checked_fields"]),
            issues=tuple(validation["issues"]),
            summary=validation["summary"],
            calculated_from_metadata=validation["calculated_from_metadata"],
            active_enforcement=validation["active_enforcement"],
        ),
        captured_at=datetime.fromisoformat(data["captured_at"]),
        deterministic=data["deterministic"],
        read_only=data["read_only"],
        active_enforcement=data["active_enforcement"],
    )


def default_runtime_policy_descriptors() -> tuple[RuntimePolicyDescriptor, ...]:
    """Return built-in passive Version 1.5 runtime policies."""

    return (
        RuntimePolicyDescriptor(
            id="runtime.metadata_integrity",
            name="Runtime Metadata Integrity Policy",
            version="1.0",
            description="Describes deterministic immutable metadata expectations.",
            category="runtime_metadata",
            scope="runtime.metadata",
            priority=100,
            minimum_runtime_version="1.4",
            maximum_runtime_version="1.5",
        ),
        RuntimePolicyDescriptor(
            id="runtime.observability_readiness",
            name="Runtime Observability Readiness Policy",
            version="1.0",
            description="Describes passive observability readiness expectations.",
            category="runtime_observability",
            scope="runtime.observability",
            priority=200,
            minimum_runtime_version="1.4",
            maximum_runtime_version="1.5",
            depends_on=("runtime.metadata_integrity",),
        ),
    )


@dataclass(slots=True, frozen=True)
class RuntimePolicyRegistry:
    """Immutable registry of passive runtime policy descriptors."""

    descriptors: tuple[RuntimePolicyDescriptor, ...] = (
        default_runtime_policy_descriptors()
    )
    registry_version: str = RUNTIME_POLICY_REGISTRY_VERSION
    schema_version: str = RUNTIME_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.registry_version, "registry_version")
        _version(self.schema_version, "schema_version")
        descriptors = tuple(self.descriptors)
        if not all(isinstance(item, RuntimePolicyDescriptor) for item in descriptors):
            raise TypeError("descriptors must contain RuntimePolicyDescriptor values")
        ids = tuple(item.id for item in descriptors)
        if len(set(ids)) != len(ids):
            raise ValueError("policy descriptor ids must be unique")
        object.__setattr__(
            self,
            "descriptors",
            tuple(sorted(descriptors, key=lambda item: (item.priority, item.id))),
        )

    def get(self, policy_id: str) -> RuntimePolicyDescriptor | None:
        _text(policy_id, "policy id", maximum=128)
        return next((item for item in self.descriptors if item.id == policy_id), None)

    def register(self, descriptor: RuntimePolicyDescriptor) -> RuntimePolicyRegistry:
        if not isinstance(descriptor, RuntimePolicyDescriptor):
            raise TypeError("descriptor must be a RuntimePolicyDescriptor")
        if self.get(descriptor.id) is not None:
            raise ValueError(f"policy id is already registered: {descriptor.id}")
        return RuntimePolicyRegistry(
            descriptors=(*self.descriptors, descriptor),
            registry_version=self.registry_version,
            schema_version=self.schema_version,
        )

    def _circular_policy_ids(self) -> tuple[str, ...]:
        descriptors = {item.id: item for item in self.descriptors}
        circular: set[str] = set()
        completed: set[str] = set()
        stack: list[str] = []

        def visit(policy_id: str) -> None:
            if policy_id in completed:
                return
            if policy_id in stack:
                circular.update(stack[stack.index(policy_id) :])
                return
            stack.append(policy_id)
            descriptor = descriptors[policy_id]
            for dependency_id in descriptor.depends_on:
                if dependency_id in descriptors:
                    visit(dependency_id)
            stack.pop()
            completed.add(policy_id)

        for policy_id in sorted(descriptors):
            visit(policy_id)
        return tuple(sorted(circular))

    def _validation_metadata(
        self,
        descriptor: RuntimePolicyDescriptor,
        circular_policy_ids: tuple[str, ...],
    ) -> RuntimePolicyValidationMetadata:
        registered = {item.id for item in self.descriptors}
        issues: set[str] = set()
        minimum = _numeric_version(descriptor.minimum_runtime_version)
        maximum = _numeric_version(descriptor.maximum_runtime_version)
        if minimum is None or maximum is None:
            issues.add("compatibility range must use numeric versions")
        elif minimum > maximum:
            issues.add("minimum runtime version cannot exceed maximum")
        if descriptor.id in descriptor.depends_on:
            issues.add("policy cannot require itself")
        if descriptor.id in descriptor.optional_dependencies:
            issues.add("policy cannot optionally depend on itself")
        if set(descriptor.depends_on) & set(descriptor.optional_dependencies):
            issues.add("required and optional dependencies cannot overlap")
        for dependency_id in set(descriptor.depends_on) - registered:
            issues.add(f"required policy dependency is missing: {dependency_id}")
        if descriptor.id in circular_policy_ids:
            issues.add("required policy dependency cycle detected")
        status = (
            RuntimePolicyValidationStatus.INVALID
            if issues
            else RuntimePolicyValidationStatus.VALID
        )
        checked = tuple(
            sorted(
                (
                    "category",
                    "compatibility_range",
                    "dependencies",
                    "description",
                    "id",
                    "name",
                    "priority",
                    "scope",
                    "version",
                )
            )
        )
        return RuntimePolicyValidationMetadata(
            policy_id=descriptor.id,
            status=status,
            checked_fields=checked,
            issues=tuple(sorted(issues)),
            summary=(
                f"Policy {descriptor.id} validation is {status.value}: "
                f"{len(issues)} issues."
            ),
        )

    def validate(self) -> RuntimePolicyRegistryValidationReport:
        circular = self._circular_policy_ids()
        results = tuple(
            self._validation_metadata(item, circular) for item in self.descriptors
        )
        issues = tuple(
            sorted(
                f"{result.policy_id}: {issue}"
                for result in results
                for issue in result.issues
            )
        )
        if not self.descriptors:
            issues = (*issues, "runtime policy registry must contain a policy")
            issues = tuple(sorted(issues))
        status = (
            RuntimePolicyValidationStatus.INVALID
            if issues
            else RuntimePolicyValidationStatus.VALID
        )
        ids = tuple(item.id for item in self.descriptors)
        return RuntimePolicyRegistryValidationReport(
            status=status,
            policy_count=len(ids),
            policy_ids=ids,
            issues=issues,
            summary=(
                f"Runtime policy validation is {status.value}: "
                f"{len(ids)} policies and {len(issues)} issues."
            ),
        )

    @staticmethod
    def verify_compatibility(
        descriptor: RuntimePolicyDescriptor,
        runtime_version: str,
    ) -> RuntimePolicyCompatibilityMetadata:
        if not isinstance(descriptor, RuntimePolicyDescriptor):
            raise TypeError("descriptor must be a RuntimePolicyDescriptor")
        runtime_text = _version(runtime_version, "runtime_version")
        runtime = _numeric_version(runtime_text)
        minimum = _numeric_version(descriptor.minimum_runtime_version)
        maximum = _numeric_version(descriptor.maximum_runtime_version)
        issues: set[str] = set()
        if runtime is None or minimum is None or maximum is None:
            status = RuntimePolicyCompatibilityStatus.UNKNOWN
            issues.add("policy compatibility requires numeric version syntax")
        else:
            if minimum > maximum:
                issues.add("policy minimum runtime version exceeds maximum")
            if runtime < minimum:
                issues.add("runtime version is older than the policy minimum")
            if runtime > maximum:
                issues.add("runtime version is newer than the policy maximum")
            status = (
                RuntimePolicyCompatibilityStatus.INCOMPATIBLE
                if issues
                else RuntimePolicyCompatibilityStatus.COMPATIBLE
            )
        return RuntimePolicyCompatibilityMetadata(
            policy_id=descriptor.id,
            status=status,
            runtime_version=runtime_text,
            minimum_runtime_version=descriptor.minimum_runtime_version,
            maximum_runtime_version=descriptor.maximum_runtime_version,
            issues=tuple(sorted(issues)),
            summary=(
                f"Policy {descriptor.id} compatibility is {status.value} "
                f"for runtime {runtime_text}."
            ),
        )

    def _dependency_metadata(
        self,
        descriptor: RuntimePolicyDescriptor,
        circular_policy_ids: tuple[str, ...],
    ) -> RuntimePolicyDependencyMetadata:
        registered = {item.id for item in self.descriptors}
        required_by = tuple(
            sorted(
                item.id
                for item in self.descriptors
                if descriptor.id in item.depends_on
            )
        )
        missing_required = tuple(
            sorted(set(descriptor.depends_on) - registered)
        )
        missing_optional = tuple(
            sorted(set(descriptor.optional_dependencies) - registered)
        )
        circular = descriptor.id in circular_policy_ids
        return RuntimePolicyDependencyMetadata(
            policy_id=descriptor.id,
            required_dependencies=descriptor.depends_on,
            optional_dependencies=descriptor.optional_dependencies,
            required_by=required_by,
            missing_required_dependencies=missing_required,
            missing_optional_dependencies=missing_optional,
            circular=circular,
            summary=(
                f"Policy {descriptor.id} declares {len(descriptor.depends_on)} "
                f"required and {len(descriptor.optional_dependencies)} optional "
                f"dependencies; {len(missing_required)} required are missing."
            ),
        )

    @staticmethod
    def _readiness_metadata(
        descriptor: RuntimePolicyDescriptor,
        source: RuntimePolicySource,
        compatibility: RuntimePolicyCompatibilityMetadata,
        dependencies: RuntimePolicyDependencyMetadata,
        validation: RuntimePolicyValidationMetadata,
    ) -> RuntimePolicyReadinessMetadata:
        issues = set(source.readiness_issues)
        issues.update(compatibility.issues)
        issues.update(validation.issues)
        issues.update(
            f"required policy dependency is missing: {item}"
            for item in dependencies.missing_required_dependencies
        )
        issues.update(
            f"optional policy dependency is missing: {item}"
            for item in dependencies.missing_optional_dependencies
        )
        if (
            not validation.valid
            or compatibility.status
            is RuntimePolicyCompatibilityStatus.INCOMPATIBLE
            or dependencies.missing_required_dependencies
            or dependencies.circular
            or source.runtime_readiness is RuntimePolicyReadiness.NOT_READY
        ):
            state = RuntimePolicyReadiness.NOT_READY
        elif (
            compatibility.status is RuntimePolicyCompatibilityStatus.UNKNOWN
            or source.runtime_readiness is RuntimePolicyReadiness.UNKNOWN
        ):
            state = RuntimePolicyReadiness.UNKNOWN
        elif (
            dependencies.missing_optional_dependencies
            or source.runtime_readiness is RuntimePolicyReadiness.PARTIAL
        ):
            state = RuntimePolicyReadiness.PARTIAL
        else:
            state = RuntimePolicyReadiness.READY
        required_count = len(descriptor.depends_on)
        available_count = required_count - len(
            dependencies.missing_required_dependencies
        )
        return RuntimePolicyReadinessMetadata(
            policy_id=descriptor.id,
            state=state,
            required_dependency_count=required_count,
            available_required_dependency_count=available_count,
            issues=tuple(sorted(issues)),
            summary=(
                f"Policy {descriptor.id} readiness is {state.value}: "
                f"{available_count} of {required_count} required dependencies available."
            ),
        )

    def snapshot(self, source: RuntimePolicySource) -> RuntimePolicyRegistrySnapshot:
        if not isinstance(source, RuntimePolicySource):
            raise TypeError("source must be a RuntimePolicySource")
        circular = self._circular_policy_ids()
        policies: list[RuntimePolicySnapshot] = []
        for descriptor in self.descriptors:
            compatibility = self.verify_compatibility(
                descriptor,
                source.runtime_version,
            )
            dependencies = self._dependency_metadata(descriptor, circular)
            validation = self._validation_metadata(descriptor, circular)
            readiness = self._readiness_metadata(
                descriptor,
                source,
                compatibility,
                dependencies,
                validation,
            )
            content_payload = {
                "descriptor": descriptor,
                "compatibility": compatibility,
                "readiness": readiness,
                "dependencies": dependencies,
                "validation": validation,
            }
            content_hash = _digest(content_payload)
            policies.append(
                RuntimePolicySnapshot(
                    policy_id=f"{_POLICY_ID_PREFIX}{content_hash}",
                    content_hash=content_hash,
                    descriptor=descriptor,
                    compatibility=compatibility,
                    readiness=readiness,
                    dependencies=dependencies,
                    validation=validation,
                    captured_at=source.captured_at,
                )
            )
        policy_values = tuple(policies)
        validation_report = self.validate()
        categories = tuple(sorted({item.category for item in policy_values}))
        readiness_counts = {
            state: sum(item.readiness.state is state for item in policy_values)
            for state in RuntimePolicyReadiness
        }
        compatible_count = sum(
            item.compatibility.status
            is RuntimePolicyCompatibilityStatus.COMPATIBLE
            for item in policy_values
        )
        invalid_count = sum(not item.validation.valid for item in policy_values)
        summary = RuntimePolicyRegistrySummary(
            policy_count=len(policy_values),
            category_count=len(categories),
            categories=categories,
            ready_policy_count=readiness_counts[RuntimePolicyReadiness.READY],
            partial_policy_count=readiness_counts[RuntimePolicyReadiness.PARTIAL],
            not_ready_policy_count=(
                readiness_counts[RuntimePolicyReadiness.NOT_READY]
            ),
            unknown_policy_count=readiness_counts[RuntimePolicyReadiness.UNKNOWN],
            compatible_policy_count=compatible_count,
            invalid_policy_count=invalid_count,
            summary=(
                f"Runtime policy registry contains {len(policy_values)} policies; "
                f"{readiness_counts[RuntimePolicyReadiness.READY]} are ready."
            ),
        )
        content_hash = _digest(
            {
                "registry_version": self.registry_version,
                "schema_version": self.schema_version,
                "policies": tuple(item.policy_id for item in policy_values),
            }
        )
        return RuntimePolicyRegistrySnapshot(
            registry_id=f"{_REGISTRY_ID_PREFIX}{content_hash}",
            content_hash=content_hash,
            registry_version=self.registry_version,
            schema_version=self.schema_version,
            policies=policy_values,
            validation_report=validation_report,
            policy_summary=summary,
            captured_at=source.captured_at,
        )

    def export(self, source: RuntimePolicySource) -> Mapping[str, object]:
        return self.snapshot(source).export()

    @staticmethod
    def compare(
        left: RuntimePolicyRegistrySnapshot,
        right: RuntimePolicyRegistrySnapshot,
    ) -> RuntimePolicyRegistryComparison:
        if not isinstance(left, RuntimePolicyRegistrySnapshot) or not isinstance(
            right,
            RuntimePolicyRegistrySnapshot,
        ):
            raise TypeError(
                "left and right must be RuntimePolicyRegistrySnapshot values"
            )
        left_policies = {item.id: item for item in left.policies}
        right_policies = {item.id: item for item in right.policies}
        left_ids = set(left_policies)
        right_ids = set(right_policies)
        changed = tuple(
            sorted(
                policy_id
                for policy_id in left_ids & right_ids
                if left_policies[policy_id].content_hash
                != right_policies[policy_id].content_hash
            )
        )
        return RuntimePolicyRegistryComparison(
            left_registry_id=left.registry_id,
            right_registry_id=right.registry_id,
            same_snapshot=left == right,
            same_content=left.content_hash == right.content_hash,
            timestamp_changed=left.captured_at != right.captured_at,
            added_policy_ids=tuple(sorted(right_ids - left_ids)),
            removed_policy_ids=tuple(sorted(left_ids - right_ids)),
            changed_policy_ids=changed,
            summary=(
                f"Runtime policy registries are "
                f"{'identical' if left == right else 'different'}; "
                f"{len(changed)} policies changed."
            ),
        )


def build_runtime_policy_registry() -> RuntimePolicyRegistry:
    """Build the default passive Runtime Policy Registry."""

    return RuntimePolicyRegistry()


__all__ = [
    "RUNTIME_POLICY_COMPATIBILITY_VERSION",
    "RUNTIME_POLICY_REGISTRY_VERSION",
    "RUNTIME_POLICY_SCHEMA_VERSION",
    "RuntimePolicyCompatibilityMetadata",
    "RuntimePolicyCompatibilityStatus",
    "RuntimePolicyDependencyMetadata",
    "RuntimePolicyDescriptor",
    "RuntimePolicyReadiness",
    "RuntimePolicyReadinessMetadata",
    "RuntimePolicyRegistry",
    "RuntimePolicyRegistryComparison",
    "RuntimePolicyRegistrySnapshot",
    "RuntimePolicyRegistrySummary",
    "RuntimePolicyRegistryValidationReport",
    "RuntimePolicySnapshot",
    "RuntimePolicySnapshotComparison",
    "RuntimePolicySource",
    "RuntimePolicyValidationMetadata",
    "RuntimePolicyValidationStatus",
    "build_runtime_policy_registry",
    "default_runtime_policy_descriptors",
]
