"""Strongly typed, immutable models for planning and workflows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


def _normalized_text(value: object, field_name: str) -> str:
    """Validate one normalized, non-empty text value."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


def _optional_normalized_text(value: object, field_name: str) -> str:
    """Validate text that may be empty but may not contain edge whitespace."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    """Return a detached tuple of unique, normalized strings."""

    if isinstance(value, str):
        value = (value,)
    try:
        supplied = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{field_name} must be an iterable of strings") from error
    if not all(
        isinstance(item, str) and item and item == item.strip()
        for item in supplied
    ):
        raise ValueError(f"{field_name} must contain normalized non-empty strings")
    if len({item.casefold() for item in supplied}) != len(supplied):
        raise ValueError(f"{field_name} must not contain duplicate values")
    return supplied


def _immutable_mapping(
    value: Mapping[str, Any],
    field_name: str,
) -> Mapping[str, Any]:
    """Validate and detach a mapping used by an immutable model."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


def _stable_identifier(prefix: str, *parts: object) -> str:
    """Build a compact deterministic identifier from JSON-safe values."""

    encoded = json.dumps(
        parts,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


class PlanningStatus(str, Enum):
    """Lifecycle states for a planning request."""

    PENDING = "pending"
    CREATED = "created"
    VALIDATED = "validated"
    COMPLETED = "completed"
    INVALID = "invalid"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class PlanStep:
    """One ordered, non-executable step selected for a plan."""

    step_id: str
    order: int
    description: str
    skill_name: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    optional: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalized_text(self.step_id, "plan step id")
        if not isinstance(self.order, int) or isinstance(self.order, bool):
            raise TypeError("plan step order must be an integer")
        if self.order < 1:
            raise ValueError("plan step order must be at least 1")
        _normalized_text(self.description, "plan step description")
        _normalized_text(self.skill_name, "plan step skill name")
        if not isinstance(self.optional, bool):
            raise TypeError("plan step optional flag must be a boolean")
        capabilities = _string_tuple(self.capabilities, "plan step capabilities")
        dependencies = _string_tuple(self.dependencies, "plan step dependencies")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(
            self,
            "metadata",
            _immutable_mapping(self.metadata, "plan step metadata"),
        )

    @property
    def sequence(self) -> int:
        """Return the one-based order using workflow terminology."""

        return self.order

    @property
    def depends_on(self) -> tuple[str, ...]:
        """Return dependencies using a concise compatibility alias."""

        return self.dependencies


@dataclass(slots=True, frozen=True)
class Plan:
    """A deterministic collection of ordered planning steps."""

    plan_id: str
    intent: str
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)
    status: PlanningStatus = PlanningStatus.CREATED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalized_text(self.plan_id, "plan id")
        _normalized_text(self.intent, "plan intent")
        try:
            steps = tuple(self.steps)
        except TypeError as error:
            raise TypeError("plan steps must be an iterable") from error
        if not all(isinstance(step, PlanStep) for step in steps):
            raise TypeError("plan steps must contain PlanStep values")
        if not isinstance(self.status, PlanningStatus):
            raise TypeError("plan status must be a PlanningStatus")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(
            self,
            "metadata",
            _immutable_mapping(self.metadata, "plan metadata"),
        )

    @property
    def user_intent(self) -> str:
        """Return the source intent using explicit terminology."""

        return self.intent

    @property
    def ordered_steps(self) -> tuple[PlanStep, ...]:
        """Return steps in their declared deterministic order."""

        return tuple(sorted(self.steps, key=lambda step: (step.order, step.step_id)))

    @property
    def step_count(self) -> int:
        """Return the number of plan steps."""

        return len(self.steps)


@dataclass(slots=True, frozen=True)
class PlanningResult:
    """The typed outcome of one complete planning lifecycle."""

    status: PlanningStatus
    plan: Plan | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, PlanningStatus):
            raise TypeError("planning result status must be a PlanningStatus")
        if self.plan is not None and not isinstance(self.plan, Plan):
            raise TypeError("planning result plan must be a Plan or None")
        errors = _string_tuple(self.errors, "planning result errors")
        if not isinstance(self.message, str):
            raise TypeError("planning result message must be a string")
        object.__setattr__(self, "errors", errors)
        object.__setattr__(
            self,
            "metadata",
            _immutable_mapping(self.metadata, "planning result metadata"),
        )

    @property
    def successful(self) -> bool:
        """Return whether planning completed with a validated plan."""

        return (
            self.status is PlanningStatus.COMPLETED
            and self.plan is not None
            and not self.errors
        )

    @property
    def completed(self) -> bool:
        """Return whether the lifecycle reached successful completion."""

        return self.successful


@dataclass(slots=True, frozen=True)
class WorkflowStep:
    """One declarative step in a sequential planning workflow."""

    step_id: str
    order: int
    description: str
    skill_name: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    optional: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalized_text(self.step_id, "workflow step id")
        if not isinstance(self.order, int) or isinstance(self.order, bool):
            raise TypeError("workflow step order must be an integer")
        if self.order < 1:
            raise ValueError("workflow step order must be at least 1")
        _normalized_text(self.description, "workflow step description")
        _optional_normalized_text(self.skill_name, "workflow step skill name")
        if not isinstance(self.optional, bool):
            raise TypeError("workflow step optional flag must be a boolean")
        object.__setattr__(
            self,
            "capabilities",
            _string_tuple(self.capabilities, "workflow step capabilities"),
        )
        object.__setattr__(
            self,
            "dependencies",
            _string_tuple(self.dependencies, "workflow step dependencies"),
        )
        object.__setattr__(
            self,
            "metadata",
            _immutable_mapping(self.metadata, "workflow step metadata"),
        )

    @property
    def sequence(self) -> int:
        """Return the one-based order using sequence terminology."""

        return self.order

    @property
    def depends_on(self) -> tuple[str, ...]:
        """Return dependencies using a concise compatibility alias."""

        return self.dependencies


@dataclass(slots=True, frozen=True)
class WorkflowDefinition:
    """A declarative, non-executing sequential workflow definition."""

    name: str
    steps: tuple[WorkflowStep, ...] = field(default_factory=tuple)
    workflow_id: str = ""
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalized_text(self.name, "workflow name")
        _optional_normalized_text(self.workflow_id, "workflow id")
        if not isinstance(self.description, str):
            raise TypeError("workflow description must be a string")
        try:
            steps = tuple(self.steps)
        except TypeError as error:
            raise TypeError("workflow steps must be an iterable") from error
        if not all(isinstance(step, WorkflowStep) for step in steps):
            raise TypeError("workflow steps must contain WorkflowStep values")
        workflow_id = self.workflow_id or _stable_identifier(
            "workflow",
            self.name,
            tuple(
                (
                    step.step_id,
                    step.order,
                    step.skill_name,
                    step.capabilities,
                    step.dependencies,
                    step.optional,
                )
                for step in steps
            ),
        )
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(
            self,
            "metadata",
            _immutable_mapping(self.metadata, "workflow metadata"),
        )

    @property
    def ordered_steps(self) -> tuple[WorkflowStep, ...]:
        """Return workflow steps in deterministic sequential order."""

        return tuple(sorted(self.steps, key=lambda step: (step.order, step.step_id)))


__all__ = [
    "Plan",
    "PlanStep",
    "PlanningResult",
    "PlanningStatus",
    "WorkflowDefinition",
    "WorkflowStep",
]
