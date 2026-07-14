"""Typed failures raised by the planning-only agent framework."""

from __future__ import annotations


class AgentPlanningError(Exception):
    """Base class for agent planning failures."""


class InvalidIntentError(AgentPlanningError, ValueError):
    """Raised when planning receives an invalid user intent."""


class SkillResolutionError(AgentPlanningError):
    """Raised when no skill can satisfy a planning request."""


class PlanValidationError(AgentPlanningError, ValueError):
    """Raised when a plan violates structural planning constraints."""


class EmptyPlanError(PlanValidationError):
    """Raised when validation receives a plan without any steps."""


class WorkflowValidationError(AgentPlanningError, ValueError):
    """Raised when a workflow violates structural constraints."""


class DependencyValidationError(PlanValidationError, WorkflowValidationError):
    """Raised for missing, cyclic, or incorrectly ordered dependencies."""


__all__ = [
    "AgentPlanningError",
    "DependencyValidationError",
    "EmptyPlanError",
    "InvalidIntentError",
    "PlanValidationError",
    "SkillResolutionError",
    "WorkflowValidationError",
]
