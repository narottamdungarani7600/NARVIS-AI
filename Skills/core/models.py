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

    def create(self) -> SkillInterface[Any, Any]:
        """Create or return the explicitly configured implementation."""

        if self.factory is not None:
            return self.factory()
        assert self.implementation is not None
        return self.implementation


__all__ = [
    "SkillCapability",
    "SkillCategory",
    "SkillDefinition",
    "SkillFactory",
    "SkillMetadata",
]
