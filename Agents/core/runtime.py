"""Planning lifecycle coordination with execution deliberately absent."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent
from Skills.core.interfaces import EventPublisher

from .context import PlanningContext
from .models import Plan, PlanningResult, PlanningStatus
from .planner import TaskPlanner
from .workflow import WorkflowValidator


class Planner(Protocol):
    """Structural contract required from an injected task planner."""

    @property
    def event_bus(self) -> EventPublisher | None:
        """Return the planner's optional event publisher."""

    def plan(
        self,
        user_intent: str,
        context: PlanningContext | None = None,
        *,
        requested_capabilities: Iterable[str] | str | None = None,
    ) -> Plan:
        """Create one planning-only plan."""


class PlanValidator(Protocol):
    """Structural contract required from an injected plan validator."""

    def validate_plan(self, plan: Plan) -> Plan:
        """Validate and return one plan."""


class AgentRuntime:
    """Create, validate, and return plans without executing any plan step."""

    CREATED_EVENT = "plan.created"
    VALIDATED_EVENT = "plan.validated"
    COMPLETED_EVENT = "plan.completed"

    def __init__(
        self,
        planner: Planner | None = None,
        *,
        validator: PlanValidator | None = None,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        resolved_planner = planner or TaskPlanner(
            logger=logger,
            event_bus=event_bus,
        )
        if not callable(getattr(resolved_planner, "plan", None)):
            raise TypeError("planner must provide a callable plan method")
        resolved_validator = validator or WorkflowValidator()
        if not callable(getattr(resolved_validator, "validate_plan", None)):
            raise TypeError("validator must provide a callable validate_plan method")
        self._planner = resolved_planner
        self._validator = resolved_validator
        self._logger = logger or NullLogger("narvis.agents.runtime")
        self._event_bus = event_bus

    @property
    def planner(self) -> Planner:
        """Return the injected planner."""

        return self._planner

    @property
    def validator(self) -> PlanValidator:
        """Return the injected plan validator."""

        return self._validator

    def plan(
        self,
        user_intent: str,
        context: PlanningContext | None = None,
        *,
        requested_capabilities: Iterable[str] | str | None = None,
    ) -> PlanningResult:
        """Run the complete planning lifecycle and return its typed result."""

        try:
            plan = self._planner.plan(
                user_intent,
                context,
                requested_capabilities=requested_capabilities,
            )
        except Exception as error:
            result = PlanningResult(
                status=PlanningStatus.FAILED,
                errors=(str(error) or type(error).__name__,),
                message="Planning failed before a plan was created.",
                metadata=_result_metadata(),
            )
            self._log(
                LogLevel.WARNING,
                "Planning completed",
                status=result.status.value,
                error_type=type(error).__name__,
                execution_performed=False,
            )
            self._publish_completed(result)
            return result

        if not isinstance(plan, Plan):
            result = PlanningResult(
                status=PlanningStatus.FAILED,
                errors=("planner returned an invalid plan value",),
                message="Planning failed before validation.",
                metadata=_result_metadata(),
            )
            self._publish_completed(result)
            return result

        planner_event_bus = getattr(self._planner, "event_bus", None)
        if self._event_bus is not None and planner_event_bus is not self._event_bus:
            self._publish(
                self.CREATED_EVENT,
                plan,
                status=PlanningStatus.CREATED,
            )

        try:
            self._validator.validate_plan(plan)
        except (TypeError, ValueError) as error:
            invalid_plan = replace(plan, status=PlanningStatus.INVALID)
            result = PlanningResult(
                status=PlanningStatus.INVALID,
                plan=invalid_plan,
                errors=(str(error) or type(error).__name__,),
                message="The created plan failed structural validation.",
                metadata=_result_metadata(),
            )
            self._log(
                LogLevel.WARNING,
                "Planning completed",
                plan_id=plan.plan_id,
                status=result.status.value,
                error_type=type(error).__name__,
                execution_performed=False,
            )
            self._publish_completed(result)
            return result

        validated_plan = replace(plan, status=PlanningStatus.VALIDATED)
        self._log(
            LogLevel.INFO,
            "Plan validated",
            plan_id=plan.plan_id,
            step_count=plan.step_count,
            execution_performed=False,
        )
        self._publish(
            self.VALIDATED_EVENT,
            validated_plan,
            status=PlanningStatus.VALIDATED,
        )

        completed_plan = replace(validated_plan, status=PlanningStatus.COMPLETED)
        result = PlanningResult(
            status=PlanningStatus.COMPLETED,
            plan=completed_plan,
            message="Planning completed successfully without execution.",
            metadata=_result_metadata(),
        )
        self._log(
            LogLevel.INFO,
            "Planning completed",
            plan_id=plan.plan_id,
            status=result.status.value,
            step_count=plan.step_count,
            execution_performed=False,
        )
        self._publish_completed(result)
        return result

    def create_plan(
        self,
        user_intent: str,
        context: PlanningContext | None = None,
        *,
        requested_capabilities: Iterable[str] | str | None = None,
    ) -> PlanningResult:
        """Run planning using an explicit compatibility-oriented method name."""

        return self.plan(
            user_intent,
            context,
            requested_capabilities=requested_capabilities,
        )

    def validate_plan(self, plan: Plan) -> Plan:
        """Expose injected plan validation without executing the plan."""

        return self._validator.validate_plan(plan)

    def _publish_completed(self, result: PlanningResult) -> None:
        """Publish the terminal lifecycle event for any planning outcome."""

        plan = result.plan
        self._publish(
            self.COMPLETED_EVENT,
            plan,
            status=result.status,
            successful=result.successful,
            errors=result.errors,
        )

    def _publish(
        self,
        event_name: str,
        plan: Plan | None,
        *,
        status: PlanningStatus,
        **payload: object,
    ) -> None:
        """Publish one lifecycle event without changing the planning result."""

        if self._event_bus is None:
            return
        event_payload: dict[str, object] = {
            "plan_id": plan.plan_id if plan is not None else None,
            "status": status.value,
            "step_count": plan.step_count if plan is not None else 0,
            "execution_performed": False,
            **payload,
        }
        try:
            self._event_bus.publish(
                SystemEvent(name=event_name, payload=event_payload)
            )
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish planning lifecycle event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit one logger entry without changing runtime behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


def _result_metadata() -> dict[str, object]:
    """Return invariant planning-only lifecycle metadata."""

    return {
        "planning_only": True,
        "execution_performed": False,
        "executor_invoked": False,
        "computer_control_used": False,
        "internet_actions_performed": False,
    }


__all__ = ["AgentRuntime", "Planner", "PlanValidator"]
