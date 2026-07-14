"""Deterministic task planning backed by the existing skill resolver."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent
from Skills.core.interfaces import EventPublisher
from Skills.core.models import SkillDefinition, SkillResolutionResult
from Skills.core.resolver import SkillResolver

from .context import PlanningContext
from .exceptions import InvalidIntentError, SkillResolutionError
from .models import Plan, PlanStep, PlanningStatus


class Resolver(Protocol):
    """Structural contract required from an injected skill resolver."""

    def resolve(
        self,
        requested_capabilities: Iterable[str] | str,
        candidates: Iterable[SkillDefinition] | None = None,
        **options: object,
    ) -> SkillResolutionResult:
        """Resolve the best skill for the supplied capabilities."""


class TaskPlanner:
    """Build deterministic, ordered plans without executing their steps."""

    CREATED_EVENT = "plan.created"

    def __init__(
        self,
        skill_resolver: Resolver | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        resolved = skill_resolver or SkillResolver(
            logger=logger,
            event_bus=event_bus,
        )
        if not callable(getattr(resolved, "resolve", None)):
            raise TypeError("skill resolver must provide a callable resolve method")
        self._skill_resolver = resolved
        self._logger = logger or NullLogger("narvis.agents.planner")
        self._event_bus = event_bus

    @property
    def skill_resolver(self) -> Resolver:
        """Return the injected skill resolver."""

        return self._skill_resolver

    @property
    def event_bus(self) -> EventPublisher | None:
        """Return the event publisher used for plan creation events."""

        return self._event_bus

    def plan(
        self,
        user_intent: str,
        context: PlanningContext | None = None,
        *,
        requested_capabilities: Iterable[str] | str | None = None,
    ) -> Plan:
        """Create one deterministic plan for a typed, in-memory context."""

        intent = _normalize_intent(user_intent)
        resolved_context = context or PlanningContext()
        if not isinstance(resolved_context, PlanningContext):
            raise TypeError("planning context must be a PlanningContext or None")
        capabilities = (
            _normalize_capabilities(requested_capabilities)
            if requested_capabilities is not None
            else _capabilities_from_intent(intent, resolved_context.available_skills)
        )

        try:
            resolution = self._skill_resolver.resolve(
                capabilities,
                candidates=resolved_context.available_skills,
                allow_partial=False,
                available_only=True,
            )
        except Exception as error:
            raise SkillResolutionError(
                f"skill resolution failed: {type(error).__name__}"
            ) from error
        if not isinstance(resolution, SkillResolutionResult):
            raise SkillResolutionError(
                "skill resolver returned an invalid resolution result"
            )
        if not resolution.resolved or resolution.selected is None:
            raise SkillResolutionError(resolution.reason)
        selected = resolution.selected
        if selected.unmatched_capabilities:
            missing = ", ".join(selected.unmatched_capabilities)
            raise SkillResolutionError(
                f"selected skill does not cover requested capabilities: {missing}"
            )
        matched_capabilities = selected.matched_capabilities
        if not matched_capabilities:
            raise SkillResolutionError(
                "selected skill did not match a requested capability"
            )

        plan_id = _identifier(
            "plan",
            intent,
            selected.name,
            "\x1f".join(matched_capabilities),
        )
        steps = _build_steps(plan_id, selected.name, matched_capabilities)
        plan = Plan(
            plan_id=plan_id,
            intent=intent,
            steps=steps,
            status=PlanningStatus.CREATED,
            metadata={
                "planning_only": True,
                "execution_performed": False,
                "selected_skill": selected.name,
                "requested_capabilities": capabilities,
            },
        )
        self._log(
            LogLevel.INFO,
            "Plan created",
            plan_id=plan.plan_id,
            step_count=plan.step_count,
            selected_skill=selected.name,
            execution_performed=False,
        )
        self._publish_created(plan)
        return plan

    def create_plan(
        self,
        user_intent: str,
        context: PlanningContext | None = None,
        *,
        requested_capabilities: Iterable[str] | str | None = None,
    ) -> Plan:
        """Create a plan using an explicit compatibility-oriented method name."""

        return self.plan(
            user_intent,
            context,
            requested_capabilities=requested_capabilities,
        )

    def _publish_created(self, plan: Plan) -> None:
        """Publish plan creation without changing the planning outcome."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                SystemEvent(
                    name=self.CREATED_EVENT,
                    payload={
                        "plan_id": plan.plan_id,
                        "status": plan.status.value,
                        "step_count": plan.step_count,
                        "execution_performed": False,
                    },
                )
            )
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish plan creation event",
                plan_id=plan.plan_id,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit one logger entry without changing planner behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


def _normalize_intent(value: object) -> str:
    """Return a stable user intent with whitespace collapsed."""

    if not isinstance(value, str):
        raise InvalidIntentError("user intent must be a string")
    intent = " ".join(value.split())
    if not intent:
        raise InvalidIntentError("user intent must be non-empty")
    return intent


def _normalize_capabilities(value: Iterable[str] | str) -> tuple[str, ...]:
    """Validate explicit requested capabilities deterministically."""

    supplied = (value,) if isinstance(value, str) else tuple(value)
    if not supplied:
        raise InvalidIntentError("at least one requested capability is required")
    if not all(
        isinstance(capability, str)
        and capability
        and capability == capability.strip()
        for capability in supplied
    ):
        raise InvalidIntentError(
            "requested capabilities must be normalized non-empty strings"
        )
    unique = {capability.casefold(): capability for capability in supplied}
    return tuple(unique[key] for key in sorted(unique))


def _capabilities_from_intent(
    intent: str,
    available_skills: tuple[SkillDefinition, ...],
) -> tuple[str, ...]:
    """Match explicit advertised capability terms in the user intent."""

    intent_terms = set(re.findall(r"[a-z0-9]+", intent.casefold()))
    advertised: dict[str, str] = {}
    for skill in available_skills:
        for capability in skill.metadata.capabilities:
            advertised.setdefault(capability.name.casefold(), capability.name)

    matched: list[str] = []
    for key in sorted(advertised):
        capability_terms = set(re.findall(r"[a-z0-9]+", key))
        if key in intent.casefold() or (
            capability_terms and capability_terms.issubset(intent_terms)
        ):
            matched.append(advertised[key])
    return tuple(matched) or (intent,)


def _identifier(prefix: str, *parts: str) -> str:
    """Build a deterministic identifier from normalized planning inputs."""

    payload = "\x1e".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:20]}"


def _build_steps(
    plan_id: str,
    skill_name: str,
    capabilities: tuple[str, ...],
) -> tuple[PlanStep, ...]:
    """Build a sequential planning step for each resolved capability."""

    steps: list[PlanStep] = []
    previous_step_id: str | None = None
    for order, capability in enumerate(capabilities, start=1):
        step_id = _identifier("step", plan_id, str(order), capability, skill_name)
        steps.append(
            PlanStep(
                step_id=step_id,
                order=order,
                description=(
                    f"Plan use of skill '{skill_name}' for capability "
                    f"'{capability}'."
                ),
                skill_name=skill_name,
                capabilities=(capability,),
                dependencies=(previous_step_id,) if previous_step_id else (),
                metadata={
                    "planning_only": True,
                    "execution_performed": False,
                },
            )
        )
        previous_step_id = step_id
    return tuple(steps)


__all__ = ["Resolver", "TaskPlanner"]
