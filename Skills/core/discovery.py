"""Registry-backed intelligent skill discovery and filtering."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .interfaces import EventPublisher
from .models import (
    SkillCapability,
    SkillCategory,
    SkillDefinition,
    SkillDiscoveryResult,
)


class _SkillCatalog(Protocol):
    """Minimum catalog contract required by discovery."""

    def list(
        self,
        category: SkillCategory | None = None,
    ) -> tuple[SkillDefinition, ...]:
        """Return registered skill definitions."""


class SkillDiscovery:
    """Discover typed skill candidates from an injected registry or manager.

    Discovery is deliberately limited to already registered definitions. It
    performs no module imports, filesystem scans, planning, or execution.
    """

    DISCOVERED_EVENT = "skill.discovered"

    def __init__(
        self,
        registry: _SkillCatalog,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not callable(getattr(registry, "list", None)):
            raise TypeError("discovery registry must provide list()")
        self._registry = registry
        self._logger = logger or NullLogger("narvis.skills.discovery")
        self._event_bus = event_bus

    @property
    def registry(self) -> _SkillCatalog:
        """Return the injected registry-compatible discovery source."""

        return self._registry

    def discover(
        self,
        category: SkillCategory | None = None,
        capabilities: Iterable[str | SkillCapability] | str | SkillCapability | None = None,
        *,
        available: bool | None = None,
        availability: bool | None = None,
        available_only: bool = False,
        require_all_capabilities: bool = True,
    ) -> tuple[SkillDiscoveryResult, ...]:
        """Return deterministic registered skills satisfying the supplied filters.

        ``available`` and ``availability`` are equivalent explicit filters.
        ``available_only`` is a convenience for the common available-skills
        query. Capability filters require every requested capability by default;
        callers preparing partial matching can set ``require_all_capabilities``
        to ``False``.
        """

        if category is not None and not isinstance(category, SkillCategory):
            raise TypeError("category must be a SkillCategory or None")
        if not isinstance(available_only, bool):
            raise TypeError("available_only must be a boolean")
        if not isinstance(require_all_capabilities, bool):
            raise TypeError("require_all_capabilities must be a boolean")
        availability_filter = self._availability_filter(
            available,
            availability,
            available_only,
        )
        requested = _normalize_capabilities(capabilities, allow_empty=True)
        requested_keys = {name.casefold() for name in requested}

        self._log(
            LogLevel.DEBUG,
            "Skill discovery started",
            category=category.value if category is not None else None,
            requested_capabilities=requested,
            availability=availability_filter,
            require_all_capabilities=require_all_capabilities,
        )
        definitions = self._registry.list(category)
        if not all(isinstance(definition, SkillDefinition) for definition in definitions):
            raise TypeError("discovery registry must return SkillDefinition values")

        results: list[SkillDiscoveryResult] = []
        for definition in sorted(definitions, key=_definition_order):
            advertised = {
                capability.name.casefold(): capability.name
                for capability in definition.metadata.capabilities
            }
            matched = tuple(
                name for name in requested if name.casefold() in advertised
            )
            capability_selected = (
                not requested_keys
                or (
                    len(matched) == len(requested)
                    if require_all_capabilities
                    else bool(matched)
                )
            )
            availability_selected = (
                availability_filter is None
                or definition.available is availability_filter
            )
            selected = capability_selected and availability_selected
            self._log(
                LogLevel.DEBUG,
                "Skill discovery candidate evaluated",
                skill=definition.name,
                matched_capabilities=matched,
                available=definition.available,
                selected=selected,
            )
            if not selected:
                continue

            result = SkillDiscoveryResult(
                definition=definition,
                requested_capabilities=requested,
                matched_capabilities=matched,
            )
            results.append(result)
            self._publish(result)

        discovered = tuple(results)
        self._log(
            LogLevel.INFO,
            "Skill discovery completed",
            count=len(discovered),
            category=category.value if category is not None else None,
            requested_capabilities=requested,
        )
        return discovered

    @staticmethod
    def _availability_filter(
        available: bool | None,
        availability: bool | None,
        available_only: bool,
    ) -> bool | None:
        """Resolve compatible availability arguments into one explicit filter."""

        for value in (available, availability):
            if value is not None and not isinstance(value, bool):
                raise TypeError("availability filter must be a boolean or None")
        if available is not None and availability is not None and available != availability:
            raise ValueError("available and availability filters must agree")
        explicit = available if available is not None else availability
        if available_only and explicit is False:
            raise ValueError("available_only conflicts with unavailable filtering")
        return True if available_only else explicit

    def _publish(self, result: SkillDiscoveryResult) -> None:
        """Publish one discovery event without changing query behavior on failure."""

        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "name": result.name,
            "version": result.metadata.version,
            "category": result.metadata.category.value,
            "matched_capabilities": result.matched_capabilities,
            "priority": result.priority,
            "available": result.available,
            "preferred": result.preferred,
        }
        try:
            self._event_bus.publish(
                SystemEvent(name=self.DISCOVERED_EVENT, payload=payload)
            )
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish skill discovery event",
                skill=result.name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit one Core logger entry without changing discovery behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


def _normalize_capabilities(
    capabilities: Iterable[str | SkillCapability] | str | SkillCapability | None,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    """Return unique normalized capability names in caller-supplied order."""

    if capabilities is None:
        values: tuple[str | SkillCapability, ...] = ()
    elif isinstance(capabilities, (str, SkillCapability)):
        values = (capabilities,)
    else:
        try:
            values = tuple(capabilities)
        except TypeError as error:
            raise TypeError("capabilities must be an iterable") from error

    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = value.name if isinstance(value, SkillCapability) else value
        if not isinstance(name, str) or not name.strip():
            raise ValueError("capabilities must contain non-empty strings")
        if name != name.strip():
            raise ValueError("capabilities must not contain surrounding whitespace")
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            names.append(name)
    if not names and not allow_empty:
        raise ValueError("at least one requested capability is required")
    return tuple(names)


def _definition_order(definition: SkillDefinition) -> tuple[str, str, str, str]:
    """Return a case-stable deterministic definition order."""

    return (
        definition.name.casefold(),
        definition.name,
        definition.metadata.version.casefold(),
        definition.metadata.version,
    )


__all__ = ["SkillDiscovery"]
