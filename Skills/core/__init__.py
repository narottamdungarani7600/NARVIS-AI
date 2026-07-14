"""Phase 9 typed skill framework foundation for NARVIS."""

from .exceptions import (
    DuplicateSkillError,
    SkillAlreadyLoadedError,
    SkillAlreadyRegisteredError,
    SkillFrameworkError,
    SkillLoadError,
    SkillLoaderError,
    SkillNotFoundError,
    SkillNotLoadedError,
    SkillNotRegisteredError,
    SkillRegistryError,
    SkillUnloadError,
)
from .interfaces import EventPublisher, SkillInterface
from .discovery import SkillDiscovery
from .loader import SkillLoader
from .manager import SkillManager
from .matcher import CapabilityMatcher, SkillCandidate
from .models import (
    CapabilityMatch,
    CapabilityMatchResult,
    SkillCapability,
    SkillCategory,
    SkillDefinition,
    SkillDiscoveryResult,
    SkillFactory,
    SkillMatchResult,
    SkillMetadata,
    SkillResolutionResult,
)
from .registry import SkillRegistry
from .resolver import SkillResolver

__all__ = [
    "CapabilityMatch",
    "CapabilityMatcher",
    "CapabilityMatchResult",
    "DuplicateSkillError",
    "EventPublisher",
    "SkillAlreadyLoadedError",
    "SkillAlreadyRegisteredError",
    "SkillCapability",
    "SkillCategory",
    "SkillDefinition",
    "SkillDiscovery",
    "SkillDiscoveryResult",
    "SkillFactory",
    "SkillFrameworkError",
    "SkillInterface",
    "SkillLoadError",
    "SkillLoader",
    "SkillLoaderError",
    "SkillManager",
    "SkillMatchResult",
    "SkillMetadata",
    "SkillNotFoundError",
    "SkillNotLoadedError",
    "SkillNotRegisteredError",
    "SkillRegistry",
    "SkillRegistryError",
    "SkillResolutionResult",
    "SkillResolver",
    "SkillCandidate",
    "SkillUnloadError",
]
