"""Skills package for NARVIS."""

from .builtin import (
    DesktopSkill,
    HelpSkill,
    InternetSkill,
    MemorySkill,
    RuntimeStatusSkill,
    build_builtin_skills,
)
from .framework import (
    BaseSkill,
    Skill,
    SkillExecutor,
    SkillMatch,
    SkillRegistry,
    SkillRequest,
    SkillResult,
    SkillServices,
    build_skill_services,
    register_skill_services,
)

__all__ = [
    "BaseSkill",
    "DesktopSkill",
    "HelpSkill",
    "InternetSkill",
    "MemorySkill",
    "RuntimeStatusSkill",
    "Skill",
    "SkillExecutor",
    "SkillMatch",
    "SkillRegistry",
    "SkillRequest",
    "SkillResult",
    "SkillServices",
    "build_builtin_skills",
    "build_skill_services",
    "register_skill_services",
]
