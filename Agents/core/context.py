"""Ephemeral, strongly typed context supplied to the task planner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from Skills.core.models import SkillDefinition


def _context_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    """Validate and detach one in-memory context mapping."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


@dataclass(slots=True, frozen=True)
class PlanningContext:
    """In-memory context available during one planning request.

    The context owns no storage or persistence behavior. Mapping values are
    detached from caller-owned dictionaries and exposed read-only.
    """

    conversation_context: Mapping[str, Any] = field(default_factory=dict)
    memory_context: Mapping[str, Any] = field(default_factory=dict)
    user_context: Mapping[str, Any] = field(default_factory=dict)
    available_skills: tuple[SkillDefinition, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conversation_context",
            _context_mapping(self.conversation_context, "conversation context"),
        )
        object.__setattr__(
            self,
            "memory_context",
            _context_mapping(self.memory_context, "memory context"),
        )
        object.__setattr__(
            self,
            "user_context",
            _context_mapping(self.user_context, "user context"),
        )
        try:
            skills = tuple(self.available_skills)
        except TypeError as error:
            raise TypeError("available skills must be an iterable") from error
        if not all(isinstance(skill, SkillDefinition) for skill in skills):
            raise TypeError("available skills must contain SkillDefinition values")
        names = [skill.name.casefold() for skill in skills]
        if len(set(names)) != len(names):
            raise ValueError("available skills must not contain duplicate names")
        object.__setattr__(
            self,
            "available_skills",
            tuple(
                sorted(
                    skills,
                    key=lambda skill: (skill.name.casefold(), skill.name),
                )
            ),
        )

    @property
    def conversation(self) -> Mapping[str, Any]:
        """Return ephemeral conversation context."""

        return self.conversation_context

    @property
    def memory(self) -> Mapping[str, Any]:
        """Return ephemeral memory context."""

        return self.memory_context

    @property
    def user(self) -> Mapping[str, Any]:
        """Return ephemeral user context."""

        return self.user_context


__all__ = ["PlanningContext"]
