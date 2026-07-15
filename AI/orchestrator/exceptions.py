"""Typed failures for architecture-only AI orchestration coordination."""

from __future__ import annotations

from AI.core.exceptions import AIOrchestratorError


class AIOrchestrationError(AIOrchestratorError):
    """Base failure for deterministic orchestration coordination."""


class OrchestrationValidationError(AIOrchestrationError, ValueError):
    """Raised when orchestration input or immutable state is invalid."""


class OrchestrationSessionError(AIOrchestrationError):
    """Base failure for orchestration session lifecycle operations."""


class SessionAlreadyExistsError(OrchestrationSessionError, ValueError):
    """Raised when an orchestration session identifier already exists."""


class SessionNotFoundError(OrchestrationSessionError, LookupError):
    """Raised when an orchestration session cannot be found."""


class SessionInactiveError(OrchestrationSessionError):
    """Raised when a terminal orchestration session is modified."""


class SessionExpiredError(SessionInactiveError):
    """Raised when an orchestration session has expired."""


class DuplicatePlanError(OrchestrationSessionError, ValueError):
    """Raised when a plan or request is recorded twice in one session."""


class PreferenceResolutionError(AIOrchestrationError):
    """Raised when no model option satisfies an immutable preference policy."""


class ProviderNegotiationError(AIOrchestrationError):
    """Raised when provider and capability negotiation cannot complete."""


class PlanGenerationError(AIOrchestrationError):
    """Raised when a non-executing orchestration plan cannot be generated."""


__all__ = [
    "AIOrchestrationError",
    "DuplicatePlanError",
    "OrchestrationSessionError",
    "OrchestrationValidationError",
    "PlanGenerationError",
    "PreferenceResolutionError",
    "ProviderNegotiationError",
    "SessionAlreadyExistsError",
    "SessionExpiredError",
    "SessionInactiveError",
    "SessionNotFoundError",
]
