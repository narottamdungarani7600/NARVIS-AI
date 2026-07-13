"""Simulation-only rollback planning for trusted execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from Core.logger import LogLevel, Logger, NullLogger

from .models import (
    ExecutionRequest,
    RollbackAction,
    RollbackPlan,
    RollbackResult,
    RollbackStatus,
)


@runtime_checkable
class RollbackProvider(Protocol):
    """Future contract for a provider capable of real rollback."""

    def rollback(self, action: RollbackAction) -> bool:
        """Apply a rollback action and report whether it completed."""


class RollbackService(Protocol):
    """Rollback contract consumed by the trusted gateway."""

    def build_plan(
        self,
        request: ExecutionRequest,
        actions: Iterable[RollbackAction] = (),
    ) -> RollbackPlan:
        """Build a typed rollback plan."""

    def execute(self, plan: RollbackPlan) -> RollbackResult:
        """Return a simulated rollback result."""


class RollbackManager:
    """Build and simulate immutable rollback plans while retaining history.

    Provider registration is intentionally preparatory.  Sprint 3 never calls
    a provider and never performs a host mutation; executing a plan only records
    which inert actions would be attempted.
    """

    def __init__(
        self,
        providers: Mapping[str, RollbackProvider] | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        """Initialize rollback registries and in-memory immutable history."""

        self._providers: dict[str, RollbackProvider] = {}
        self._actions: dict[str, list[RollbackAction]] = {}
        self._plans: list[RollbackPlan] = []
        self._history: list[RollbackResult] = []
        self._logger = logger or NullLogger("narvis.execution.rollback")
        for name, provider in (providers or {}).items():
            self.register_provider(name, provider)

    @property
    def providers(self) -> Mapping[str, RollbackProvider]:
        """Return a detached, read-only provider registry."""

        return MappingProxyType(dict(self._providers))

    @property
    def plans(self) -> tuple[RollbackPlan, ...]:
        """Return all plans in creation order."""

        return tuple(self._plans)

    @property
    def history(self) -> tuple[RollbackResult, ...]:
        """Return immutable simulated execution history."""

        return tuple(self._history)

    @property
    def execution_history(self) -> tuple[RollbackResult, ...]:
        """Return a descriptive alias for :attr:`history`."""

        return self.history

    def register_provider(self, name: str, provider: RollbackProvider) -> None:
        """Register a future provider without enabling real rollback."""

        normalized_name = self._normalized_identifier("provider name", name)
        if not isinstance(provider, RollbackProvider):
            raise TypeError("rollback providers must implement rollback(action)")
        self._providers[normalized_name] = provider

    def register_action(self, request_id: str, action: RollbackAction) -> None:
        """Associate an inert rollback action with an execution request."""

        normalized_request_id = self._normalized_identifier(
            "request_id",
            request_id,
        )
        if not isinstance(action, RollbackAction):
            raise TypeError("registered rollback actions must be RollbackAction values")
        self._actions.setdefault(normalized_request_id, []).append(action)
        self._log(
            LogLevel.DEBUG,
            "Rollback action registered",
            request_id=normalized_request_id,
            rollback_action_id=action.action_id,
            provider=action.provider,
        )

    def register_rollback_action(
        self,
        request_id: str,
        action: RollbackAction,
    ) -> None:
        """Register an action using explicit rollback terminology."""

        self.register_action(request_id, action)

    def registered_actions(self, request_id: str) -> tuple[RollbackAction, ...]:
        """Return the actions currently registered for a request."""

        normalized_request_id = self._normalized_identifier(
            "request_id",
            request_id,
        )
        return tuple(self._actions.get(normalized_request_id, ()))

    def build_plan(
        self,
        request: ExecutionRequest,
        actions: Iterable[RollbackAction] = (),
    ) -> RollbackPlan:
        """Build and retain a plan from registered and supplied inert actions."""

        if not isinstance(request, ExecutionRequest):
            raise TypeError("rollback plans require a typed ExecutionRequest")
        supplied_actions = tuple(actions)
        if any(not isinstance(action, RollbackAction) for action in supplied_actions):
            raise TypeError("rollback plan actions must be RollbackAction values")
        plan = RollbackPlan(
            request_id=request.request_id,
            action=request.action,
            actions=self.registered_actions(request.request_id) + supplied_actions,
        )
        self._plans.append(plan)
        self._log(
            LogLevel.INFO,
            "Rollback plan built",
            request_id=request.request_id,
            action=request.action,
            plan_id=plan.plan_id,
            action_count=len(plan.actions),
            simulated_only=True,
        )
        return plan

    def execute(self, plan: RollbackPlan) -> RollbackResult:
        """Record a simulated rollback without invoking any provider."""

        if not isinstance(plan, RollbackPlan):
            result = RollbackResult(
                request_id="",
                plan_id="",
                status=RollbackStatus.FAILED,
                successful=False,
                simulated=True,
                message="Rollback simulation requires a typed RollbackPlan.",
            )
            self._history.append(result)
            self._log_result(result)
            return result

        result = RollbackResult(
            request_id=plan.request_id,
            plan_id=plan.plan_id,
            status=RollbackStatus.SIMULATED,
            successful=True,
            simulated=True,
            message=(
                "Rollback was simulated; no provider or computer action was invoked."
            ),
            actions_executed=tuple(action.action_id for action in plan.actions),
        )
        self._history.append(result)
        self._log_result(result)
        return result

    def execute_rollback(self, plan: RollbackPlan) -> RollbackResult:
        """Execute a plan using explicit rollback terminology."""

        return self.execute(plan)

    def execute_plan(self, plan: RollbackPlan) -> RollbackResult:
        """Execute a plan using plan-oriented terminology."""

        return self.execute(plan)

    @staticmethod
    def _normalized_identifier(name: str, value: object) -> str:
        """Return a normalized identifier or raise a configuration error."""

        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > 256
        ):
            raise ValueError(
                f"{name} must be a normalized non-empty string of at most "
                "256 characters"
            )
        return value

    def _log_result(self, result: RollbackResult) -> None:
        """Log a simulated rollback result."""

        self._log(
            LogLevel.INFO if result.successful else LogLevel.ERROR,
            "Rollback simulation completed",
            request_id=result.request_id,
            plan_id=result.plan_id,
            status=result.status.value,
            simulated=result.simulated,
            action_count=len(result.actions_executed),
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a structured log without changing rollback state."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["RollbackManager", "RollbackProvider", "RollbackService"]
