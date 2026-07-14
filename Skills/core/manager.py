"""High-level coordination API for the NARVIS skill framework."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from Core.logger import Logger

from .discovery import SkillDiscovery
from .interfaces import EventPublisher, SkillInterface
from .loader import SkillLoader
from .matcher import CapabilityMatcher, SkillCandidate
from .models import (
    CapabilityMatchResult,
    SkillCapability,
    SkillCategory,
    SkillDefinition,
    SkillDiscoveryResult,
    SkillResolutionResult,
)
from .registry import SkillRegistry
from .resolver import SkillResolver


class SkillManager:
    """Coordinate an injected registry and registry-backed lifecycle loader."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        loader: SkillLoader | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
        discovery: SkillDiscovery | None = None,
        matcher: CapabilityMatcher | None = None,
        resolver: SkillResolver | None = None,
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

        if resolver is not None and matcher is None:
            matcher = resolver.matcher
        if matcher is not None and discovery is None:
            discovery = matcher.discovery
        self._discovery = discovery or SkillDiscovery(
            self._registry,
            logger=logger,
            event_bus=event_bus,
        )
        if self._discovery.registry is not self._registry:
            raise ValueError("manager registry and discovery registry must be identical")
        self._matcher = matcher or CapabilityMatcher(
            self._discovery,
            logger=logger,
            event_bus=event_bus,
        )
        if self._matcher.discovery is not self._discovery:
            raise ValueError("manager discovery and matcher discovery must be identical")
        self._resolver = resolver or SkillResolver(
            self._matcher,
            logger=logger,
            event_bus=event_bus,
        )
        if self._resolver.matcher is not self._matcher:
            raise ValueError("manager matcher and resolver matcher must be identical")

    @property
    def registry(self) -> SkillRegistry:
        """Return the coordinated registry."""

        return self._registry

    @property
    def loader(self) -> SkillLoader:
        """Return the coordinated loader."""

        return self._loader

    @property
    def discovery_service(self) -> SkillDiscovery:
        """Return the coordinated intelligent discovery service."""

        return self._discovery

    @property
    def matcher(self) -> CapabilityMatcher:
        """Return the coordinated capability matcher."""

        return self._matcher

    @property
    def resolver(self) -> SkillResolver:
        """Return the coordinated skill resolver."""

        return self._resolver

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

    def discover_skills(
        self,
        category: SkillCategory | None = None,
        capabilities: (
            Iterable[str | SkillCapability] | str | SkillCapability | None
        ) = None,
        *,
        available: bool | None = None,
        availability: bool | None = None,
        available_only: bool = False,
        require_all_capabilities: bool = True,
    ) -> tuple[SkillDiscoveryResult, ...]:
        """Discover registered skills through the intelligent filter service."""

        return self._discovery.discover(
            category=category,
            capabilities=capabilities,
            available=available,
            availability=availability,
            available_only=available_only,
            require_all_capabilities=require_all_capabilities,
        )

    def match_capabilities(
        self,
        requested_capabilities: (
            Iterable[str | SkillCapability] | str | SkillCapability
        ),
        candidates: Iterable[SkillCandidate] | None = None,
        *,
        allow_partial: bool = True,
        minimum_score: float = 0.0,
        available_only: bool = True,
    ) -> tuple[CapabilityMatchResult, ...]:
        """Match registered or explicitly supplied skills by capability."""

        return self._matcher.match(
            requested_capabilities,
            candidates,
            allow_partial=allow_partial,
            minimum_score=minimum_score,
            available_only=available_only,
        )

    def resolve_skill(
        self,
        requested_capabilities: (
            Iterable[str | SkillCapability]
            | Iterable[CapabilityMatchResult]
            | str
            | SkillCapability
        ),
        candidates: Iterable[SkillCandidate | CapabilityMatchResult] | None = None,
        *,
        category: SkillCategory | None = None,
        preferred_skills: Iterable[str] | str = (),
        preferred_skill: str | None = None,
        allow_partial: bool = True,
        minimum_score: float = 0.0,
        available_only: bool = True,
    ) -> SkillResolutionResult:
        """Resolve one best matching skill without loading or executing it."""

        return self._resolver.resolve(
            requested_capabilities,
            candidates,
            category=category,
            preferred_skills=preferred_skills,
            preferred_skill=preferred_skill,
            allow_partial=allow_partial,
            minimum_score=minimum_score,
            available_only=available_only,
        )

    # Concise aliases make the manager convenient while preserving Sprint 1 APIs.
    match = match_capabilities
    resolve = resolve_skill

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
