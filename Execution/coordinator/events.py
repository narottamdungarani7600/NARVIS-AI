"""Lifecycle event publishing for safe execution coordination."""

from __future__ import annotations

from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent
from Execution.session.queue import EventPublisher

from .models import ExecutionCoordination

EXECUTION_CREATED_EVENT = "execution.created"
EXECUTION_VALIDATED_EVENT = "execution.validated"
EXECUTION_READY_EVENT = "execution.ready"
EXECUTION_CANCELLED_EVENT = "execution.cancelled"
EXECUTION_FAILED_EVENT = "execution.failed"


class LifecycleEventSink(Protocol):
    """Structural event sink accepted by the coordinator."""

    def publish(
        self,
        event_name: str,
        coordination: ExecutionCoordination,
        **extra: object,
    ) -> None:
        """Publish one lifecycle event."""


class CoordinatorEvents:
    """Publish non-sensitive coordinator events through the existing EventBus."""

    def __init__(
        self,
        event_bus: EventPublisher | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        """Initialize event and logging dependencies."""

        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.execution.coordinator.events")

    def publish(
        self,
        event_name: str,
        coordination: ExecutionCoordination,
        **extra: object,
    ) -> None:
        """Publish one safe lifecycle event without exposing action parameters."""

        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "coordination_id": coordination.coordination_id,
            "request_id": coordination.request_id,
            "session_id": coordination.session_id,
            "state": coordination.state.value,
            "preview_id": (
                coordination.preview.preview_id
                if coordination.preview is not None
                else ""
            ),
            "plan_id": (
                coordination.plan.plan_id if coordination.plan is not None else ""
            ),
            "dry_run": True,
            "executed": False,
            "dispatcher_invoked": False,
        }
        payload.update(extra)
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish execution coordinator event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failure to alter coordination."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "CoordinatorEvents",
    "EXECUTION_CANCELLED_EVENT",
    "EXECUTION_CREATED_EVENT",
    "EXECUTION_FAILED_EVENT",
    "EXECUTION_READY_EVENT",
    "EXECUTION_VALIDATED_EVENT",
    "LifecycleEventSink",
]
