"""Structural validation for plans and declarative workflows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

from .exceptions import (
    DependencyValidationError,
    EmptyPlanError,
    PlanValidationError,
    WorkflowValidationError,
)
from .models import Plan, PlanStep, WorkflowDefinition, WorkflowStep


class _OrderedStep(Protocol):
    """Structural subset shared by plan and workflow steps."""

    step_id: str
    order: int
    dependencies: tuple[str, ...]


StepT = TypeVar("StepT", bound=_OrderedStep)


def _validate_steps(
    steps: Sequence[StepT],
    *,
    empty_error: type[ValueError],
    structure_error: type[ValueError],
) -> tuple[StepT, ...]:
    """Validate one sequential acyclic dependency graph."""

    if not steps:
        raise empty_error("at least one step is required")

    identifiers = [step.step_id for step in steps]
    if len(set(identifiers)) != len(identifiers):
        raise structure_error("step identifiers must be unique")
    orders = [step.order for step in steps]
    if len(set(orders)) != len(orders):
        raise structure_error("step order values must be unique")
    expected_orders = list(range(1, len(steps) + 1))
    if sorted(orders) != expected_orders:
        raise structure_error("step order values must be contiguous and start at 1")

    ordered = tuple(sorted(steps, key=lambda step: step.order))
    known_orders = {step.step_id: step.order for step in ordered}
    for step in ordered:
        for dependency in step.dependencies:
            if dependency not in known_orders:
                raise DependencyValidationError(
                    f"step '{step.step_id}' depends on missing step '{dependency}'"
                )
            if dependency == step.step_id:
                raise DependencyValidationError(
                    f"step '{step.step_id}' cannot depend on itself"
                )
            if known_orders[dependency] >= step.order:
                raise DependencyValidationError(
                    f"step '{step.step_id}' must depend only on earlier steps"
                )
    return ordered


def validate_plan(plan: Plan) -> Plan:
    """Validate a plan and return it unchanged when structurally valid."""

    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    _validate_steps(
        plan.steps,
        empty_error=EmptyPlanError,
        structure_error=PlanValidationError,
    )
    return plan


def validate_workflow(workflow: WorkflowDefinition) -> WorkflowDefinition:
    """Validate a declarative workflow and return it unchanged."""

    if not isinstance(workflow, WorkflowDefinition):
        raise TypeError("workflow must be a WorkflowDefinition")
    _validate_steps(
        workflow.steps,
        empty_error=WorkflowValidationError,
        structure_error=WorkflowValidationError,
    )
    return workflow


class WorkflowValidator:
    """Injected validator for plans and workflow definitions."""

    def validate(
        self,
        value: Plan | WorkflowDefinition,
    ) -> Plan | WorkflowDefinition:
        """Validate one supported planning structure."""

        if isinstance(value, Plan):
            return validate_plan(value)
        if isinstance(value, WorkflowDefinition):
            return validate_workflow(value)
        raise TypeError("value must be a Plan or WorkflowDefinition")

    def validate_plan(self, plan: Plan) -> Plan:
        """Validate one plan."""

        return validate_plan(plan)

    def validate_workflow(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        """Validate one workflow definition."""

        return validate_workflow(workflow)

    def is_valid(self, value: Plan | WorkflowDefinition) -> bool:
        """Return whether a supported structure passes validation."""

        try:
            self.validate(value)
        except (TypeError, ValueError):
            return False
        return True


__all__ = [
    "Plan",
    "PlanStep",
    "WorkflowDefinition",
    "WorkflowStep",
    "WorkflowValidator",
    "validate_plan",
    "validate_workflow",
]
