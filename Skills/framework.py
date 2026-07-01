"""Skill registry and execution framework for the NARVIS runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Skills."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


@dataclass(slots=True, frozen=True)
class SkillRequest:
    """Represents an incoming skill execution request."""

    text: str
    route: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None
    session_id: str | None = None


@dataclass(slots=True, frozen=True)
class SkillMatch:
    """Represents the match score for a skill request."""

    skill_name: str
    confidence: float
    reason: str = ""


@dataclass(slots=True, frozen=True)
class SkillResult:
    """Represents the outcome of a skill execution."""

    skill_name: str
    handled: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class Skill(Protocol):
    """Protocol implemented by executable runtime skills."""

    name: str
    description: str

    def match(self, request: SkillRequest) -> SkillMatch:
        """Return the skill's confidence for handling a request."""

    def execute(self, request: SkillRequest) -> SkillResult:
        """Execute the skill for the supplied request."""


class BaseSkill:
    """Convenience base class for keyword-oriented runtime skills."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        keywords: tuple[str, ...] = (),
        logger: Any | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.keywords = keywords
        self.logger = logger

    def match(self, request: SkillRequest) -> SkillMatch:
        """Score the request using simple keyword overlap."""

        normalized_text = " ".join(request.text.strip().lower().split())
        if not normalized_text:
            return SkillMatch(skill_name=self.name, confidence=0.0, reason="empty request")

        matches = [keyword for keyword in self.keywords if keyword in normalized_text]
        confidence = min(0.99, 0.15 + (len(matches) * 0.2)) if matches else 0.0
        reason = ", ".join(matches) if matches else "no keyword match"
        return SkillMatch(skill_name=self.name, confidence=confidence, reason=reason)


class SkillRegistry:
    """Store and expose runtime skills."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        """Register a skill and return it."""

        self._skills[skill.name] = skill
        _emit_log(self.logger, "debug", "Registered skill", skill=skill.name)
        return skill

    def resolve(self, name: str) -> Skill:
        """Return a registered skill by name."""

        return self._skills[name]

    def list_skills(self) -> tuple[Skill, ...]:
        """Return all registered skills sorted by name."""

        return tuple(self._skills[name] for name in sorted(self._skills))

    def count(self) -> int:
        """Return the number of registered skills."""

        return len(self._skills)


class SkillExecutor:
    """Resolve and execute skills from the registry."""

    def __init__(self, registry: SkillRegistry, logger: Any | None = None) -> None:
        self.registry = registry
        self.logger = logger

    def match_best(self, request: SkillRequest) -> tuple[Skill, SkillMatch] | None:
        """Return the highest-confidence skill for a request."""

        best: tuple[Skill, SkillMatch] | None = None
        for skill in self.registry.list_skills():
            match = skill.match(request)
            if best is None or match.confidence > best[1].confidence:
                best = (skill, match)
        return best

    def execute_best(self, request: SkillRequest, minimum_confidence: float = 0.45) -> SkillResult | None:
        """Execute the best matching skill when confidence crosses the threshold."""

        best = self.match_best(request)
        if best is None:
            return None

        skill, match = best
        if match.confidence < minimum_confidence:
            return None

        result = skill.execute(request)
        _emit_log(
            self.logger,
            "info",
            "Executed skill",
            skill=skill.name,
            confidence=match.confidence,
            handled=result.handled,
        )
        return SkillResult(
            skill_name=result.skill_name,
            handled=result.handled,
            message=result.message,
            data=dict(result.data),
            confidence=match.confidence,
        )


@dataclass(slots=True)
class SkillServices:
    """Container for runtime skill services."""

    registry: SkillRegistry
    executor: SkillExecutor


def build_skill_services(
    *,
    registry: SkillRegistry | None = None,
    executor: SkillExecutor | None = None,
    logger: Any | None = None,
) -> SkillServices:
    """Build the runtime skill service bundle."""

    resolved_registry = registry or SkillRegistry(logger=logger)
    resolved_executor = executor or SkillExecutor(registry=resolved_registry, logger=logger)
    _emit_log(logger, "info", "Built skill services")
    return SkillServices(registry=resolved_registry, executor=resolved_executor)


def register_skill_services(
    container: DependencyRegistrar,
    services: SkillServices,
    *,
    logger: Any | None = None,
) -> SkillServices:
    """Register runtime skill services in the dependency container."""

    container.register_instance("skill_registry", services.registry)
    container.register_instance("skill_executor", services.executor)
    _emit_log(logger, "info", "Registered skill services in container")
    return services


__all__ = [
    "BaseSkill",
    "Skill",
    "SkillExecutor",
    "SkillMatch",
    "SkillRegistry",
    "SkillRequest",
    "SkillResult",
    "SkillServices",
    "build_skill_services",
    "register_skill_services",
]
