"""Skills package for NARVIS."""

from .builtin import (
    DesktopSkill,
    HelpSkill,
    InternetSkill,
    MemorySkill,
    RuntimeStatusSkill,
    build_builtin_skills,
)
from .desktop_commands import (
    DesktopCommandSkill,
    DesktopCommandMatch,
    DesktopCommandPipeline,
    DesktopCommandServices,
    build_desktop_command_services,
    build_desktop_command_skills,
    register_desktop_command_services,
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
    "DesktopCommandSkill",
    "DesktopCommandMatch",
    "DesktopCommandPipeline",
    "DesktopCommandServices",
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
    "build_desktop_command_services",
    "build_desktop_command_skills",
    "build_skill_services",
    "register_desktop_command_services",
    "register_skill_services",
]
