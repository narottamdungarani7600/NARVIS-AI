"""Typed exceptions for the NARVIS skill framework foundation."""

from __future__ import annotations


class SkillFrameworkError(Exception):
    """Base exception for failures raised by the skill framework."""


class SkillRegistryError(SkillFrameworkError):
    """Base exception for registry failures."""


class DuplicateSkillError(SkillRegistryError):
    """Raised when a skill identifier is already registered."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill '{skill_name}' is already registered")


class SkillNotFoundError(SkillRegistryError):
    """Raised when a requested skill is not registered."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill '{skill_name}' is not registered")


class SkillLoaderError(SkillFrameworkError):
    """Base exception for loader and lifecycle failures."""


class SkillAlreadyLoadedError(SkillLoaderError):
    """Raised when a loaded skill is loaded again."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill '{skill_name}' is already loaded")


class SkillNotLoadedError(SkillLoaderError):
    """Raised when an unloaded skill is requested for unloading."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill '{skill_name}' is not loaded")


class SkillLoadError(SkillLoaderError):
    """Raised when a skill cannot be created or initialized."""

    def __init__(self, skill_name: str, reason: str) -> None:
        self.skill_name = skill_name
        self.reason = reason
        super().__init__(f"Unable to load skill '{skill_name}': {reason}")


class SkillUnloadError(SkillLoaderError):
    """Raised when a loaded skill cannot be shut down."""

    def __init__(self, skill_name: str, reason: str) -> None:
        self.skill_name = skill_name
        self.reason = reason
        super().__init__(f"Unable to unload skill '{skill_name}': {reason}")


# Descriptive aliases retained for callers that prefer lifecycle terminology.
SkillAlreadyRegisteredError = DuplicateSkillError
SkillNotRegisteredError = SkillNotFoundError


__all__ = [
    "DuplicateSkillError",
    "SkillAlreadyLoadedError",
    "SkillAlreadyRegisteredError",
    "SkillFrameworkError",
    "SkillLoadError",
    "SkillLoaderError",
    "SkillNotFoundError",
    "SkillNotLoadedError",
    "SkillNotRegisteredError",
    "SkillRegistryError",
    "SkillUnloadError",
]
