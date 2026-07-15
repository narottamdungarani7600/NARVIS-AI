"""Strongly typed immutable models for provider-agnostic AI orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class ProviderCapability(str, Enum):
    """Provider capabilities understood by the architecture-only selector."""

    CHAT = "chat"
    TEXT_GENERATION = "text_generation"
    REASONING = "reasoning"
    STRUCTURED_OUTPUT = "structured_output"
    EMBEDDINGS = "embeddings"
    VISION = "vision"
    TOOL_USE = "tool_use"
    STREAMING = "streaming"


class ProviderStatus(str, Enum):
    """Availability states reported without probing or model execution."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    HEALTHY = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    OFFLINE = "unavailable"
    DISABLED = "disabled"


class ProviderPriority(IntEnum):
    """Stable provider preference where lower values are selected first."""

    HIGHEST = 0
    HIGH = 25
    NORMAL = 50
    DEFAULT = 50
    LOW = 75
    LOWEST = 100


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_id() -> str:
    """Return an opaque, non-semantic identifier."""

    return uuid4().hex


def _text(
    value: object,
    name: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        value != value.strip()
        or len(value) > maximum
        or (not value and not allow_empty)
    ):
        raise ValueError(
            f"{name} must be normalized text of at most {maximum} characters"
        )
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("mapping keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a recursively detached read-only mapping."""

    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return _freeze(value)


def _capabilities(values: object, name: str) -> tuple[ProviderCapability, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must contain ProviderCapability values")
    try:
        capabilities = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    if any(not isinstance(value, ProviderCapability) for value in capabilities):
        raise TypeError(f"{name} must contain ProviderCapability values")
    if len(set(capabilities)) != len(capabilities):
        raise ValueError(f"{name} cannot contain duplicates")
    return capabilities


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    try:
        identifiers = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        for value in identifiers
    ):
        raise ValueError(f"{name} must contain normalized non-empty strings")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{name} cannot contain duplicates")
    return identifiers


@dataclass(slots=True, frozen=True)
class ProviderMetadata:
    """Immutable descriptive and selection metadata for one provider."""

    name: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0"
    capabilities: tuple[ProviderCapability, ...] = ()
    priority: ProviderPriority = ProviderPriority.NORMAL
    supported_models: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        _text(self.name, "provider name", maximum=128)
        _text(self.display_name, "display_name", maximum=256, allow_empty=True)
        if not isinstance(self.description, str) or len(self.description) > 4000:
            raise ValueError("description must be a string of at most 4000 characters")
        _text(self.version, "version", maximum=128)
        object.__setattr__(
            self,
            "capabilities",
            _capabilities(self.capabilities, "capabilities"),
        )
        if not isinstance(self.priority, ProviderPriority):
            raise TypeError("priority must be a ProviderPriority")
        object.__setattr__(
            self,
            "supported_models",
            _identifiers(self.supported_models, "supported_models"),
        )
        object.__setattr__(self, "tags", _identifiers(self.tags, "tags"))
        object.__setattr__(self, "attributes", immutable_mapping(self.attributes))
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")

    @property
    def provider_id(self) -> str:
        """Return the stable provider identifier."""

        return self.name

    @property
    def label(self) -> str:
        """Return the display label with a stable fallback."""

        return self.display_name or self.name

    def supports(self, capability: ProviderCapability) -> bool:
        """Return whether this metadata advertises one typed capability."""

        if not isinstance(capability, ProviderCapability):
            raise TypeError("capability must be a ProviderCapability")
        return capability in self.capabilities


@dataclass(slots=True, frozen=True)
class ProviderHealth:
    """Immutable provider health supplied externally without active probing."""

    provider_id: str
    status: ProviderStatus = ProviderStatus.UNKNOWN
    checked_at: datetime = field(default_factory=utc_now)
    message: str = ""
    consecutive_failures: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id", maximum=128)
        if not isinstance(self.status, ProviderStatus):
            raise TypeError("status must be a ProviderStatus")
        _time(self.checked_at, "checked_at")
        if not isinstance(self.message, str) or len(self.message) > 2000:
            raise ValueError("message must be a string of at most 2000 characters")
        if (
            isinstance(self.consecutive_failures, bool)
            or not isinstance(self.consecutive_failures, int)
            or self.consecutive_failures < 0
        ):
            raise ValueError("consecutive_failures must be a non-negative integer")
        object.__setattr__(self, "details", immutable_mapping(self.details))

    @property
    def selectable(self) -> bool:
        """Return whether selection may use this externally supplied status."""

        return self.status in {
            ProviderStatus.AVAILABLE,
            ProviderStatus.DEGRADED,
        }

    @property
    def healthy(self) -> bool:
        """Return whether the provider is reported fully available."""

        return self.status is ProviderStatus.AVAILABLE


@dataclass(slots=True, frozen=True)
class AIProvider:
    """Immutable provider descriptor registered for future orchestration."""

    metadata: ProviderMetadata
    health: ProviderHealth | None = None
    registered_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderMetadata):
            raise TypeError("metadata must be ProviderMetadata")
        health = self.health
        if health is None:
            health = ProviderHealth(
                provider_id=self.metadata.name,
                status=(
                    ProviderStatus.AVAILABLE
                    if self.metadata.enabled
                    else ProviderStatus.DISABLED
                ),
                checked_at=self.registered_at,
            )
            object.__setattr__(self, "health", health)
        elif not isinstance(health, ProviderHealth):
            raise TypeError("health must be ProviderHealth or None")
        if health.provider_id != self.metadata.name:
            raise ValueError("health must belong to provider metadata")
        if not self.metadata.enabled and health.status is not ProviderStatus.DISABLED:
            raise ValueError("disabled providers require disabled health")
        _time(self.registered_at, "registered_at")

    @property
    def provider_id(self) -> str:
        """Return the provider metadata identifier."""

        return self.metadata.name

    @property
    def name(self) -> str:
        """Return the concise provider identifier."""

        return self.provider_id

    @property
    def status(self) -> ProviderStatus:
        """Return the immutable health status."""

        assert self.health is not None
        return self.health.status

    @property
    def priority(self) -> ProviderPriority:
        """Return the selection priority."""

        return self.metadata.priority

    @property
    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return advertised provider capabilities."""

        return self.metadata.capabilities

    @property
    def selectable(self) -> bool:
        """Return whether metadata and externally supplied health permit selection."""

        assert self.health is not None
        return self.metadata.enabled and self.health.selectable


@dataclass(slots=True, frozen=True)
class AIRequest:
    """Immutable provider-agnostic request description; never executed here."""

    prompt: str
    required_capabilities: tuple[ProviderCapability, ...] = ()
    preferred_provider_id: str | None = None
    model_hint: str | None = None
    system_prompt: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if len(self.prompt) > 200_000:
            raise ValueError("prompt cannot exceed 200000 characters")
        _text(self.request_id, "request_id", maximum=128)
        object.__setattr__(
            self,
            "required_capabilities",
            _capabilities(self.required_capabilities, "required_capabilities"),
        )
        if self.preferred_provider_id is not None:
            _text(
                self.preferred_provider_id,
                "preferred_provider_id",
                maximum=128,
            )
        if self.model_hint is not None:
            _text(self.model_hint, "model_hint", maximum=256)
        if not isinstance(self.system_prompt, str) or len(self.system_prompt) > 100_000:
            raise ValueError(
                "system_prompt must be a string of at most 100000 characters"
            )
        object.__setattr__(self, "parameters", immutable_mapping(self.parameters))
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        _time(self.created_at, "created_at")


@dataclass(slots=True, frozen=True)
class AIResponse:
    """Immutable normalized future response model with no generation behavior."""

    request_id: str
    provider_id: str
    content: str
    model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    response_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", maximum=128)
        _text(self.provider_id, "provider_id", maximum=128)
        _text(self.response_id, "response_id", maximum=128)
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if self.model is not None:
            _text(self.model, "model", maximum=256)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        _time(self.created_at, "created_at")


__all__ = [
    "AIProvider",
    "AIRequest",
    "AIResponse",
    "ProviderCapability",
    "ProviderHealth",
    "ProviderMetadata",
    "ProviderPriority",
    "ProviderStatus",
]
