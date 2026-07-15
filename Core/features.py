"""Immutable runtime feature descriptors and deterministic catalogue exports.

The registry stores descriptive metadata only. Runtime-aware snapshots consume
the existing immutable service registry and capability manifest; they never
resolve services, invoke providers, probe the host, perform I/O, or execute a
feature.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from threading import RLock
from types import MappingProxyType

from .capabilities import RuntimeCapabilityManifest
from .service_registry import RuntimeServiceRegistrySnapshot


class RuntimeFeatureMaturity(str, Enum):
    """Product maturity classifications for runtime features."""

    EXPERIMENTAL = "experimental"
    BETA = "beta"
    PREVIEW = "preview"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class RuntimeFeatureAvailability(str, Enum):
    """Declared or metadata-derived runtime feature availability."""

    AVAILABLE = "available"
    CONDITIONAL = "conditional"
    UNAVAILABLE = "unavailable"


class RuntimeFeatureSafetyLevel(str, Enum):
    """Safety classifications advertised without granting execution authority."""

    METADATA_ONLY = "metadata_only"
    SAFE = "safe"
    GUARDED = "guarded"
    RESTRICTED = "restricted"


class RuntimeFeatureCommercialVisibility(str, Enum):
    """Commercial catalogue visibility classifications."""

    PUBLIC = "public"
    COMMERCIAL = "commercial"
    LICENSED = "licensed"
    INTERNAL = "internal"
    HIDDEN = "hidden"


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
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return tuple(sorted(result))


def _enum_value(value: object, enum_type: type[Enum], name: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{name} must be one of: {choices}") from error


@dataclass(slots=True, frozen=True)
class RuntimeFeatureDescriptor:
    """One immutable feature definition suitable for runtime catalogues."""

    id: str
    display_name: str
    description: str
    category: str
    maturity: RuntimeFeatureMaturity
    availability: RuntimeFeatureAvailability
    required_services: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    safety_level: RuntimeFeatureSafetyLevel
    commercial_visibility: RuntimeFeatureCommercialVisibility
    experimental: bool

    def __post_init__(self) -> None:
        _text(self.id, "id", maximum=128)
        _text(self.display_name, "display_name", maximum=128)
        _text(self.description, "description", maximum=2000)
        _text(self.category, "category", maximum=128)
        object.__setattr__(
            self,
            "maturity",
            _enum_value(self.maturity, RuntimeFeatureMaturity, "maturity"),
        )
        object.__setattr__(
            self,
            "availability",
            _enum_value(
                self.availability,
                RuntimeFeatureAvailability,
                "availability",
            ),
        )
        object.__setattr__(
            self,
            "safety_level",
            _enum_value(
                self.safety_level,
                RuntimeFeatureSafetyLevel,
                "safety_level",
            ),
        )
        object.__setattr__(
            self,
            "commercial_visibility",
            _enum_value(
                self.commercial_visibility,
                RuntimeFeatureCommercialVisibility,
                "commercial_visibility",
            ),
        )
        object.__setattr__(
            self,
            "required_services",
            _identifiers(self.required_services, "required_services"),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _identifiers(self.required_capabilities, "required_capabilities"),
        )
        if not isinstance(self.experimental, bool):
            raise TypeError("experimental must be a bool")


@dataclass(slots=True, frozen=True)
class RuntimeFeaturePublicSummary:
    """Immutable public-safe feature catalogue record."""

    id: str
    display_name: str
    description: str
    category: str
    maturity: RuntimeFeatureMaturity
    availability: RuntimeFeatureAvailability
    required_capabilities: tuple[str, ...]
    safety_level: RuntimeFeatureSafetyLevel
    commercial_visibility: RuntimeFeatureCommercialVisibility
    experimental: bool

    @classmethod
    def from_descriptor(
        cls,
        descriptor: RuntimeFeatureDescriptor,
    ) -> RuntimeFeaturePublicSummary:
        """Create a public record without exposing internal service topology."""

        if not isinstance(descriptor, RuntimeFeatureDescriptor):
            raise TypeError("descriptor must be a RuntimeFeatureDescriptor")
        return cls(
            id=descriptor.id,
            display_name=descriptor.display_name,
            description=descriptor.description,
            category=descriptor.category,
            maturity=descriptor.maturity,
            availability=descriptor.availability,
            required_capabilities=descriptor.required_capabilities,
            safety_level=descriptor.safety_level,
            commercial_visibility=descriptor.commercial_visibility,
            experimental=descriptor.experimental,
        )

    def __post_init__(self) -> None:
        _text(self.id, "id", maximum=128)
        _text(self.display_name, "display_name", maximum=128)
        _text(self.description, "description", maximum=2000)
        _text(self.category, "category", maximum=128)
        if not isinstance(self.maturity, RuntimeFeatureMaturity):
            raise TypeError("maturity must be a RuntimeFeatureMaturity")
        if not isinstance(self.availability, RuntimeFeatureAvailability):
            raise TypeError("availability must be a RuntimeFeatureAvailability")
        if not isinstance(self.safety_level, RuntimeFeatureSafetyLevel):
            raise TypeError("safety_level must be a RuntimeFeatureSafetyLevel")
        if not isinstance(
            self.commercial_visibility,
            RuntimeFeatureCommercialVisibility,
        ):
            raise TypeError(
                "commercial_visibility must be a RuntimeFeatureCommercialVisibility"
            )
        object.__setattr__(
            self,
            "required_capabilities",
            _identifiers(self.required_capabilities, "required_capabilities"),
        )
        if not isinstance(self.experimental, bool):
            raise TypeError("experimental must be a bool")


@dataclass(slots=True, frozen=True)
class RuntimeFeatureRegistrySnapshot:
    """Deeply immutable, deterministically ordered feature catalogue snapshot."""

    features: tuple[RuntimeFeatureDescriptor, ...]
    features_by_category: Mapping[str, tuple[RuntimeFeatureDescriptor, ...]]
    public_summaries: tuple[RuntimeFeaturePublicSummary, ...]
    diagnostics_timestamp: datetime | None = None
    evaluated_from_runtime_metadata: bool = False

    def __post_init__(self) -> None:
        features = tuple(self.features)
        if not all(isinstance(item, RuntimeFeatureDescriptor) for item in features):
            raise TypeError("features must contain RuntimeFeatureDescriptor values")
        ids = tuple(item.id for item in features)
        if ids != tuple(sorted(ids)):
            raise ValueError("features must use deterministic id ordering")
        if len(set(ids)) != len(ids):
            raise ValueError("features cannot contain duplicate ids")
        if not isinstance(self.features_by_category, Mapping):
            raise TypeError("features_by_category must be a mapping")
        grouped: dict[str, tuple[RuntimeFeatureDescriptor, ...]] = {}
        for category in sorted(self.features_by_category):
            _text(category, "feature category", maximum=128)
            values = tuple(self.features_by_category[category])
            if not values or any(item.category != category for item in values):
                raise ValueError("feature groups must be non-empty and match category")
            if tuple(item.id for item in values) != tuple(
                sorted(item.id for item in values)
            ):
                raise ValueError("feature category groups must use id ordering")
            grouped[category] = values
        flattened = tuple(
            sorted(
                (item for values in grouped.values() for item in values),
                key=lambda item: item.id,
            )
        )
        if flattened != features:
            raise ValueError("feature groups must contain every feature exactly once")
        summaries = tuple(self.public_summaries)
        if not all(
            isinstance(item, RuntimeFeaturePublicSummary) for item in summaries
        ):
            raise TypeError(
                "public_summaries must contain RuntimeFeaturePublicSummary values"
            )
        expected_public = tuple(
            item.id
            for item in features
            if item.commercial_visibility
            is RuntimeFeatureCommercialVisibility.PUBLIC
        )
        if tuple(item.id for item in summaries) != expected_public:
            raise ValueError("public summaries must match public features in id order")
        if self.diagnostics_timestamp is not None:
            _time(self.diagnostics_timestamp, "diagnostics_timestamp")
        if not isinstance(self.evaluated_from_runtime_metadata, bool):
            raise TypeError("evaluated_from_runtime_metadata must be a bool")
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "features_by_category", MappingProxyType(grouped))
        object.__setattr__(self, "public_summaries", summaries)

    def get(self, feature_id: str) -> RuntimeFeatureDescriptor | None:
        """Return one retained descriptor by id."""

        _text(feature_id, "feature_id", maximum=128)
        return next((item for item in self.features if item.id == feature_id), None)

    def by_category(self, category: str) -> tuple[RuntimeFeatureDescriptor, ...]:
        """Return an immutable category group or an empty tuple."""

        _text(category, "category", maximum=128)
        return self.features_by_category.get(category, ())

    def export_public_summaries(self) -> tuple[RuntimeFeaturePublicSummary, ...]:
        """Return the immutable public catalogue export."""

        return self.public_summaries


class RuntimeFeatureRegistry:
    """Register immutable feature definitions and produce passive snapshots."""

    def __init__(
        self,
        features: Iterable[RuntimeFeatureDescriptor] = (),
    ) -> None:
        if isinstance(features, (str, bytes)):
            raise TypeError("features must contain RuntimeFeatureDescriptor values")
        self._lock = RLock()
        self._features: dict[str, RuntimeFeatureDescriptor] = {}
        self.register_many(features)

    def register(
        self,
        descriptor: RuntimeFeatureDescriptor,
    ) -> RuntimeFeatureDescriptor:
        """Register one descriptor, rejecting duplicate feature ids."""

        if not isinstance(descriptor, RuntimeFeatureDescriptor):
            raise TypeError("descriptor must be a RuntimeFeatureDescriptor")
        with self._lock:
            if descriptor.id in self._features:
                raise ValueError(f"feature id '{descriptor.id}' is already registered")
            self._features[descriptor.id] = descriptor
        return descriptor

    def register_many(
        self,
        descriptors: Iterable[RuntimeFeatureDescriptor],
    ) -> tuple[RuntimeFeatureDescriptor, ...]:
        """Atomically register several descriptors after validating uniqueness."""

        if isinstance(descriptors, (str, bytes)):
            raise TypeError("descriptors must contain RuntimeFeatureDescriptor values")
        try:
            values = tuple(descriptors)
        except TypeError as error:
            raise TypeError(
                "descriptors must contain RuntimeFeatureDescriptor values"
            ) from error
        if not all(isinstance(item, RuntimeFeatureDescriptor) for item in values):
            raise TypeError("descriptors must contain RuntimeFeatureDescriptor values")
        ids = tuple(item.id for item in values)
        if len(set(ids)) != len(ids):
            raise ValueError("descriptors cannot contain duplicate feature ids")
        with self._lock:
            duplicate = next((item for item in ids if item in self._features), None)
            if duplicate is not None:
                raise ValueError(f"feature id '{duplicate}' is already registered")
            self._features.update((item.id, item) for item in values)
        return values

    def get(self, feature_id: str) -> RuntimeFeatureDescriptor | None:
        """Return one registered immutable descriptor."""

        _text(feature_id, "feature_id", maximum=128)
        with self._lock:
            return self._features.get(feature_id)

    def snapshot(
        self,
        *,
        service_registry_snapshot: RuntimeServiceRegistrySnapshot | None = None,
        capability_manifest: RuntimeCapabilityManifest | None = None,
        diagnostics_timestamp: datetime | None = None,
    ) -> RuntimeFeatureRegistrySnapshot:
        """Return a deterministic snapshot, optionally evaluated from metadata."""

        if (service_registry_snapshot is None) != (capability_manifest is None):
            raise ValueError(
                "service_registry_snapshot and capability_manifest must be provided together"
            )
        if service_registry_snapshot is not None and not isinstance(
            service_registry_snapshot,
            RuntimeServiceRegistrySnapshot,
        ):
            raise TypeError(
                "service_registry_snapshot must be a RuntimeServiceRegistrySnapshot"
            )
        if capability_manifest is not None and not isinstance(
            capability_manifest,
            RuntimeCapabilityManifest,
        ):
            raise TypeError("capability_manifest must be a RuntimeCapabilityManifest")
        captured_at = diagnostics_timestamp
        if captured_at is not None:
            _time(captured_at, "diagnostics_timestamp")
        if service_registry_snapshot is not None and capability_manifest is not None:
            source_timestamp = service_registry_snapshot.diagnostics_timestamp
            if capability_manifest.diagnostics_timestamp != source_timestamp:
                raise ValueError("runtime metadata timestamps must match")
            if captured_at is None:
                captured_at = source_timestamp
            elif captured_at != source_timestamp:
                raise ValueError("feature and runtime metadata timestamps must match")
        with self._lock:
            features = tuple(self._features[name] for name in sorted(self._features))
        evaluated = (
            service_registry_snapshot is not None and capability_manifest is not None
        )
        if evaluated:
            features = self._evaluate(
                features,
                service_registry_snapshot,
                capability_manifest,
            )
        grouped: dict[str, tuple[RuntimeFeatureDescriptor, ...]] = {}
        for category in sorted({item.category for item in features}):
            grouped[category] = tuple(
                item for item in features if item.category == category
            )
        public = tuple(
            RuntimeFeaturePublicSummary.from_descriptor(item)
            for item in features
            if item.commercial_visibility
            is RuntimeFeatureCommercialVisibility.PUBLIC
        )
        return RuntimeFeatureRegistrySnapshot(
            features=features,
            features_by_category=grouped,
            public_summaries=public,
            diagnostics_timestamp=captured_at,
            evaluated_from_runtime_metadata=evaluated,
        )

    def group_by_category(
        self,
    ) -> Mapping[str, tuple[RuntimeFeatureDescriptor, ...]]:
        """Return immutable deterministic feature groups."""

        return self.snapshot().features_by_category

    def export_public_summaries(self) -> tuple[RuntimeFeaturePublicSummary, ...]:
        """Return immutable summaries for publicly visible features."""

        return self.snapshot().public_summaries

    @staticmethod
    def _evaluate(
        features: tuple[RuntimeFeatureDescriptor, ...],
        service_registry_snapshot: RuntimeServiceRegistrySnapshot,
        capability_manifest: RuntimeCapabilityManifest,
    ) -> tuple[RuntimeFeatureDescriptor, ...]:
        service_names = {
            service.service_name for service in service_registry_snapshot.services
        }
        available_capabilities = {
            *capability_manifest.supported_subsystems,
            *capability_manifest.available_diagnostics,
            *capability_manifest.readiness.available_capabilities,
            *(
                name
                for name, enabled in capability_manifest.feature_flags.items()
                if enabled
            ),
        }
        return tuple(
            replace(item, availability=RuntimeFeatureAvailability.UNAVAILABLE)
            if (
                item.availability is RuntimeFeatureAvailability.AVAILABLE
                and (
                    not set(item.required_services).issubset(service_names)
                    or not set(item.required_capabilities).issubset(
                        available_capabilities
                    )
                )
            )
            else item
            for item in features
        )


def default_runtime_feature_descriptors() -> tuple[RuntimeFeatureDescriptor, ...]:
    """Return the Version 1.5 Sprint 1 built-in runtime metadata catalogue."""

    definitions = (
        (
            "runtime.capability_manifest",
            "Runtime Capability Manifest",
            "Describes runtime composition and readiness from passive metadata.",
            ("runtime_capability_manifest",),
            ("runtime_capability_manifest",),
        ),
        (
            "runtime.diagnostics",
            "Runtime Diagnostics",
            "Reports immutable lifecycle, compatibility, and health metadata.",
            ("runtime_diagnostics",),
            ("diagnostics",),
        ),
        (
            "runtime.feature_registry",
            "Runtime Feature Registry",
            "Publishes immutable, deterministic feature catalogue snapshots.",
            ("runtime_feature_registry",),
            ("runtime_feature_registry",),
        ),
        (
            "runtime.service_registry",
            "Runtime Service Registry",
            "Reports passive service registration and dependency metadata.",
            ("runtime_service_registry",),
            ("runtime_service_registry",),
        ),
    )
    return tuple(
        RuntimeFeatureDescriptor(
            id=feature_id,
            display_name=display_name,
            description=description,
            category="runtime_observability",
            maturity=RuntimeFeatureMaturity.STABLE,
            availability=RuntimeFeatureAvailability.AVAILABLE,
            required_services=services,
            required_capabilities=capabilities,
            safety_level=RuntimeFeatureSafetyLevel.METADATA_ONLY,
            commercial_visibility=RuntimeFeatureCommercialVisibility.PUBLIC,
            experimental=False,
        )
        for feature_id, display_name, description, services, capabilities in definitions
    )


def build_runtime_feature_registry() -> RuntimeFeatureRegistry:
    """Build the default registry without performing runtime discovery."""

    return RuntimeFeatureRegistry(default_runtime_feature_descriptors())


__all__ = [
    "RuntimeFeatureAvailability",
    "RuntimeFeatureCommercialVisibility",
    "RuntimeFeatureDescriptor",
    "RuntimeFeatureMaturity",
    "RuntimeFeaturePublicSummary",
    "RuntimeFeatureRegistry",
    "RuntimeFeatureRegistrySnapshot",
    "RuntimeFeatureSafetyLevel",
    "build_runtime_feature_registry",
    "default_runtime_feature_descriptors",
]
