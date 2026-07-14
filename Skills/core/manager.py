"""High-level coordination API for the NARVIS skill framework."""

from __future__ import annotations

from typing import Any

from Core.logger import Logger

from .interfaces import EventPublisher, SkillInterface
from .loader import SkillLoader
from .models import SkillCategory, SkillDefinition
from .registry import SkillRegistry


class SkillManager:
    """Coordinate an injected registry and registry-backed lifecycle loader."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        loader: SkillLoader | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if registry is None and loader is not None:
            registry = loader.registry
        self._registry = (
            registry
            if registry is not None
            else SkillRegistry(logger=logger, event_bus=event_bus)
        )
        self._loader = loader or SkillLoader(
            self._registry,
            logger=logger,
            event_bus=event_bus,
        )
        if self._loader.registry is not self._registry:
            raise ValueError("manager registry and loader registry must be identical")

    @property
    def registry(self) -> SkillRegistry:
        """Return the coordinated registry."""

        return self._registry

    @property
    def loader(self) -> SkillLoader:
        """Return the coordinated loader."""

        return self._loader

    def register(self, definition: SkillDefinition) -> SkillDefinition:
        """Register one skill definition."""

        return self._registry.register(definition)

    def unregister(self, name: str) -> SkillDefinition:
        """Unload a skill when needed, then remove its definition."""

        if self._loader.is_loaded(name):
            self._loader.unload(name)
        return self._registry.unregister(name)

    def find(self, name: str) -> SkillDefinition | None:
        """Find a registered skill definition."""

        return self._registry.find(name)

    def list(
        self,
        category: SkillCategory | None = None,
    ) -> tuple[SkillDefinition, ...]:
        """List registered skill definitions."""

        return self._registry.list(category)

    def exists(self, name: str) -> bool:
        """Return whether a skill is registered."""

        return self._registry.exists(name)

    def discover(self) -> tuple[SkillDefinition, ...]:
        """Discover skills through the registry-backed loader."""

        return self._loader.discover()

    def load(self, name: str) -> SkillInterface[Any, Any]:
        """Load one registered skill."""

        return self._loader.load(name)

    def unload(self, name: str) -> SkillInterface[Any, Any]:
        """Unload one loaded skill."""

        return self._loader.unload(name)

    def find_loaded(self, name: str) -> SkillInterface[Any, Any] | None:
        """Find one loaded skill implementation."""

        return self._loader.find_loaded(name)

    def list_loaded(self) -> tuple[SkillInterface[Any, Any], ...]:
        """List loaded skill implementations."""

        return self._loader.list_loaded()

    def is_loaded(self, name: str) -> bool:
        """Return whether a named skill is loaded."""

        return self._loader.is_loaded(name)


__all__ = ["SkillManager"]
