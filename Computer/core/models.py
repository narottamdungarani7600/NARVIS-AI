"""Strongly typed models for the NARVIS Computer service foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


class ComputerStatus(str, Enum):
    """Provider health states understood by the Computer service layer."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"


def _require_normalized_text(value: object, field_name: str) -> str:
    """Return validated non-empty text without changing caller input."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


def _immutable_mapping(
    value: Mapping[str, Any],
    field_name: str,
) -> Mapping[str, Any]:
    """Validate and detach a mapping used by an immutable model."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


@dataclass(slots=True, frozen=True)
class ComputerCapability:
    """One inert capability advertised by a computer provider."""

    name: str
    description: str = ""
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "capability name")
        if not isinstance(self.description, str):
            raise TypeError("capability description must be a string")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "capability attributes"),
        )

    @property
    def capability_id(self) -> str:
        """Return the stable capability identifier."""

        return self.name


@dataclass(slots=True, frozen=True)
class ComputerProviderInfo:
    """Immutable identity and descriptive metadata for a provider."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    vendor: str = ""
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "provider name")
        _require_normalized_text(self.version, "provider version")
        if not isinstance(self.description, str):
            raise TypeError("provider description must be a string")
        if not isinstance(self.vendor, str):
            raise TypeError("provider vendor must be a string")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "provider attributes"),
        )

    @property
    def provider_id(self) -> str:
        """Return the registry identifier for this provider."""

        return self.name


@dataclass(slots=True, frozen=True)
class ComputerHealth:
    """A provider-supplied health observation with detached details."""

    status: ComputerStatus = ComputerStatus.UNKNOWN
    message: str = ""
    details: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComputerStatus):
            raise TypeError("computer health status must be a ComputerStatus")
        if not isinstance(self.message, str):
            raise TypeError("computer health message must be a string")
        object.__setattr__(
            self,
            "details",
            _immutable_mapping(self.details, "computer health details"),
        )

    @property
    def is_healthy(self) -> bool:
        """Return whether this observation represents full health."""

        return self.status is ComputerStatus.HEALTHY


__all__ = [
    "ComputerCapability",
    "ComputerHealth",
    "ComputerProviderInfo",
    "ComputerStatus",
]
