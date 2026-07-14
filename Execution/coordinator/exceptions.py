"""Exception hierarchy for safe execution coordination."""

from __future__ import annotations


class CoordinatorError(Exception):
    """Base exception for planning-only coordination failures."""


class CoordinatorValidationError(CoordinatorError, ValueError):
    """Raised when coordinator input cannot satisfy the typed contract."""


class CoordinationNotFoundError(CoordinatorError, LookupError):
    """Raised when a coordination record cannot be found."""


class DuplicateCoordinationError(CoordinatorError, ValueError):
    """Raised when a coordination identifier is retained twice."""


class InvalidStateTransitionError(CoordinatorError, ValueError):
    """Raised when a lifecycle transition is not permitted."""


class ReadinessError(CoordinatorError, ValueError):
    """Raised when readiness cannot be evaluated safely."""


class PlanCreationError(CoordinatorError, ValueError):
    """Raised when a non-executing plan cannot be created."""


__all__ = [
    "CoordinationNotFoundError",
    "CoordinatorError",
    "CoordinatorValidationError",
    "DuplicateCoordinationError",
    "InvalidStateTransitionError",
    "PlanCreationError",
    "ReadinessError",
]
