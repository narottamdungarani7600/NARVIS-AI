"""Strongly typed domain models for the NARVIS skill framework."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from .interfaces import SkillInterface


class SkillCategory(str, Enum):
    """Stable high-level categories available to skill metadata."""

    GENERAL = "general"
    CORE = "core"
    SYSTEM = "system"
    PRODUCTIVITY = "productivity"
    AUTOMATION = "automation"
    COMMUNICATION = "communication"
    INFORMATION = "information"
    INTEGRATION = "integration"
    DEVELOPMENT = "development"
    CUSTOM = "custom"


def _require_normalized_text(value: object, field_name: str) -> str:
    """Validate and return one non-empty, whitespace-normalized text value."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


@dataclass(slots=True, frozen=True)
class SkillCapability:
    """One capability explicitly advertised by a skill."""

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "capability name")
        if not isinstance(self.description, str):
            raise TypeError("capability description must be a string")


@dataclass(slots=True, frozen=True)
class SkillMetadata:
    """Immutable descriptive metadata required for every registered skill."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    category: SkillCategory = SkillCategory.GENERAL
    capabilities: tuple[SkillCapability, ...] = field(default_factory=tuple)
    author: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    priority: int = 0
    available: bool = True
    preferred: bool = False

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "skill name")
        _require_normalized_text(self.version, "skill version")
        if not isinstance(self.description, str):
            raise TypeError("skill description must be a string")
        if not isinstance(self.author, str):
            raise TypeError("skill author must be a string")
        if not isinstance(self.category, SkillCategory):
            raise TypeError("skill category must be a SkillCategory")

        capabilities = tuple(self.capabilities)
        if not all(
            isinstance(capability, SkillCapability) for capability in capabilities
        ):
            raise TypeError("skill capabilities must contain SkillCapability values")

        tags = tuple(self.tags)
        if not all(isinstance(tag, str) and tag.strip() == tag and tag for tag in tags):
            raise ValueError("skill tags must be normalized non-empty strings")
        if not isinstance(self.attributes, Mapping):
            raise TypeError("skill attributes must be a mapping")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("skill priority must be an integer")
        if not isinstance(self.available, bool):
            raise TypeError("skill availability must be a boolean")
        if not isinstance(self.preferred, bool):
            raise TypeError("skill preferred flag must be a boolean")

        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )

    @property
    def skill_id(self) -> str:
        """Return the stable registry identifier for this metadata."""

        return self.name

    @property
    def availability(self) -> bool:
        """Return the availability flag using descriptive terminology."""

        return self.available

    @property
    def is_available(self) -> bool:
        """Return whether the skill is available."""

        return self.available

    @property
    def is_preferred(self) -> bool:
        """Return whether the skill is preferred."""

        return self.preferred


SkillFactory = Callable[[], SkillInterface[Any, Any]]


@dataclass(slots=True, frozen=True)
class SkillDefinition:
    """Bind required metadata to an injected skill implementation provider.

    A factory is preferred for independent lifecycle ownership. Supplying an
    implementation instance is also supported for simple adapters and tests.
    Exactly one provider must be supplied.
    """

    metadata: SkillMetadata
    factory: SkillFactory | None = field(default=None, repr=False, compare=False)
    implementation: SkillInterface[Any, Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, SkillMetadata):
            raise TypeError("skill definition metadata must be SkillMetadata")
        if (self.factory is None) == (self.implementation is None):
            raise ValueError(
                "skill definition requires exactly one factory or implementation"
            )
        if self.factory is not None and not callable(self.factory):
            raise TypeError("skill factory must be callable")

    @property
    def name(self) -> str:
        """Return the metadata identifier used by the registry."""

        return self.metadata.name

    @property
    def priority(self) -> int:
        """Return the resolver priority advertised by the skill."""

        return self.metadata.priority

    @property
    def available(self) -> bool:
        """Return whether the skill is currently available for selection."""

        return self.metadata.available

    @property
    def preferred(self) -> bool:
        """Return whether the skill is a metadata-level preferred candidate."""

        return self.metadata.preferred

    @property
    def is_available(self) -> bool:
        """Return whether the skill is available."""

        return self.available

    @property
    def is_preferred(self) -> bool:
        """Return whether the skill is preferred."""

        return self.preferred

    def create(self) -> SkillInterface[Any, Any]:
        """Create or return the explicitly configured implementation."""

        if self.factory is not None:
            return self.factory()
        assert self.implementation is not None
        return self.implementation


@dataclass(slots=True, frozen=True)
class SkillDiscoveryResult:
    """Describe one registered skill returned by an intelligent discovery query."""

    definition: SkillDefinition
    requested_capabilities: tuple[str, ...] = field(default_factory=tuple)
    matched_capabilities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.definition, SkillDefinition):
            raise TypeError("discovery result definition must be a SkillDefinition")
        requested = _capability_names(
            self.requested_capabilities,
            "requested capabilities",
        )
        matched = _capability_names(
            self.matched_capabilities,
            "matched capabilities",
        )
        object.__setattr__(self, "requested_capabilities", requested)
        object.__setattr__(self, "matched_capabilities", matched)

    @property
    def skill(self) -> SkillDefinition:
        """Return the discovered definition using a concise compatibility alias."""

        return self.definition

    @property
    def metadata(self) -> SkillMetadata:
        """Return the immutable metadata for the discovered skill."""

        return self.definition.metadata

    @property
    def name(self) -> str:
        """Return the discovered skill identifier."""

        return self.definition.name

    @property
    def priority(self) -> int:
        """Return the discovered skill priority."""

        return self.definition.priority

    @property
    def available(self) -> bool:
        """Return the discovered skill availability."""

        return self.definition.available

    @property
    def availability(self) -> bool:
        """Return availability using descriptive terminology."""

        return self.available

    @property
    def preferred(self) -> bool:
        """Return the discovered skill preferred flag."""

        return self.definition.preferred

    @property
    def is_available(self) -> bool:
        """Return whether the discovered skill is available."""

        return self.available

    @property
    def is_preferred(self) -> bool:
        """Return whether the discovered skill is preferred."""

        return self.preferred

    @property
    def capabilities(self) -> tuple[SkillCapability, ...]:
        """Return all capabilities advertised by the discovered skill."""

        return self.metadata.capabilities


@dataclass(slots=True, frozen=True)
class CapabilityMatchResult:
    """Represent the deterministic capability score for one skill candidate."""

    definition: SkillDefinition
    requested_capabilities: tuple[str, ...]
    matched_capabilities: tuple[str, ...]
    unmatched_capabilities: tuple[str, ...]
    capability_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.definition, SkillDefinition):
            raise TypeError("match result definition must be a SkillDefinition")
        requested = _capability_names(
            self.requested_capabilities,
            "requested capabilities",
        )
        matched = _capability_names(
            self.matched_capabilities,
            "matched capabilities",
        )
        unmatched = _capability_names(
            self.unmatched_capabilities,
            "unmatched capabilities",
        )
        if not isinstance(self.capability_score, (int, float)) or isinstance(
            self.capability_score,
            bool,
        ):
            raise TypeError("capability score must be a number")
        score = float(self.capability_score)
        if not 0.0 <= score <= 1.0:
            raise ValueError("capability score must be between 0.0 and 1.0")
        object.__setattr__(self, "requested_capabilities", requested)
        object.__setattr__(self, "matched_capabilities", matched)
        object.__setattr__(self, "unmatched_capabilities", unmatched)
        object.__setattr__(self, "capability_score", score)

    @property
    def skill(self) -> SkillDefinition:
        """Return the matched definition using a concise compatibility alias."""

        return self.definition

    @property
    def metadata(self) -> SkillMetadata:
        """Return immutable metadata for the matched skill."""

        return self.definition.metadata

    @property
    def name(self) -> str:
        """Return the matched skill identifier."""

        return self.definition.name

    @property
    def score(self) -> float:
        """Return the capability score using a concise compatibility alias."""

        return self.capability_score

    @property
    def priority(self) -> int:
        """Return the matched skill priority."""

        return self.definition.priority

    @property
    def available(self) -> bool:
        """Return the matched skill availability."""

        return self.definition.available

    @property
    def availability(self) -> bool:
        """Return availability using descriptive terminology."""

        return self.available

    @property
    def preferred(self) -> bool:
        """Return the matched skill preferred flag."""

        return self.definition.preferred

    @property
    def is_available(self) -> bool:
        """Return whether the matched skill is available."""

        return self.available

    @property
    def is_preferred(self) -> bool:
        """Return whether the matched skill is preferred."""

        return self.preferred

    @property
    def exact_match(self) -> bool:
        """Return whether the skill provides every requested capability."""

        return bool(self.requested_capabilities) and not self.unmatched_capabilities

    @property
    def partial_match(self) -> bool:
        """Return whether the skill provides only part of the request."""

        return bool(self.matched_capabilities) and bool(self.unmatched_capabilities)

    @property
    def is_exact(self) -> bool:
        """Return whether this is an exact match."""

        return self.exact_match

    @property
    def is_partial(self) -> bool:
        """Return whether this is a partial match."""

        return self.partial_match

    @property
    def missing_capabilities(self) -> tuple[str, ...]:
        """Return unmatched capabilities using missing-capability terminology."""

        return self.unmatched_capabilities


@dataclass(slots=True, frozen=True)
class SkillResolutionResult:
    """Represent a complete best-skill resolution outcome without execution."""

    decision: str
    reason_code: str
    reason: str
    requested_capabilities: tuple[str, ...]
    selected: CapabilityMatchResult | None = None
    candidates: tuple[CapabilityMatchResult, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.decision not in {"resolved", "unresolved"}:
            raise ValueError("resolution decision must be 'resolved' or 'unresolved'")
        _require_normalized_text(self.reason_code, "resolution reason code")
        _require_normalized_text(self.reason, "resolution reason")
        requested = _capability_names(
            self.requested_capabilities,
            "requested capabilities",
        )
        candidates = tuple(self.candidates)
        if not all(
            isinstance(candidate, CapabilityMatchResult) for candidate in candidates
        ):
            raise TypeError(
                "resolution candidates must contain CapabilityMatchResult values"
            )
        if self.selected is not None and not isinstance(
            self.selected,
            CapabilityMatchResult,
        ):
            raise TypeError("selected skill must be a CapabilityMatchResult or None")
        if self.decision == "resolved" and self.selected is None:
            raise ValueError("a resolved result requires a selected skill")
        if self.decision == "unresolved" and self.selected is not None:
            raise ValueError("an unresolved result cannot contain a selected skill")
        object.__setattr__(self, "requested_capabilities", requested)
        object.__setattr__(self, "candidates", candidates)

    @property
    def resolved(self) -> bool:
        """Return whether a matching skill was selected."""

        return self.decision == "resolved" and self.selected is not None

    @property
    def selected_match(self) -> CapabilityMatchResult | None:
        """Return the selected capability match using descriptive terminology."""

        return self.selected

    @property
    def match(self) -> CapabilityMatchResult | None:
        """Return the selected capability match using a concise alias."""

        return self.selected

    @property
    def definition(self) -> SkillDefinition | None:
        """Return the selected definition when resolution succeeded."""

        return self.selected.definition if self.selected is not None else None

    @property
    def skill(self) -> SkillDefinition | None:
        """Return the selected definition using a concise compatibility alias."""

        return self.definition

    @property
    def selected_skill(self) -> SkillDefinition | None:
        """Return the selected definition using resolver terminology."""

        return self.definition


def _capability_names(values: object, field_name: str) -> tuple[str, ...]:
    """Validate an immutable sequence of normalized capability identifiers."""

    if isinstance(values, str):
        values = (values,)
    try:
        names = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{field_name} must be an iterable of strings") from error
    if not all(isinstance(name, str) and name and name.strip() == name for name in names):
        raise ValueError(f"{field_name} must contain normalized non-empty strings")
    return names


# Public aliases retain intuitive terminology for callers and future adapters.
CapabilityMatch = CapabilityMatchResult
SkillMatchResult = CapabilityMatchResult


__all__ = [
    "CapabilityMatch",
    "CapabilityMatchResult",
    "SkillCapability",
    "SkillCategory",
    "SkillDefinition",
    "SkillDiscoveryResult",
    "SkillFactory",
    "SkillMatchResult",
    "SkillMetadata",
    "SkillResolutionResult",
]
