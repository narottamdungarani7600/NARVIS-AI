"""Immutable state transitions for safe execution coordination."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from Execution.session.models import utc_now

from .exceptions import InvalidStateTransitionError
from .models import CoordinatorState, ExecutionCoordination, StateTransition

_ALLOWED_TRANSITIONS: dict[CoordinatorState, frozenset[CoordinatorState]] = {
    CoordinatorState.CREATED: frozenset(
        {
            CoordinatorState.VALIDATED,
            CoordinatorState.CANCELLED,
            CoordinatorState.FAILED,
        }
    ),
    CoordinatorState.VALIDATED: frozenset(
        {
            CoordinatorState.PREVIEW_READY,
            CoordinatorState.CANCELLED,
            CoordinatorState.FAILED,
        }
    ),
    CoordinatorState.PREVIEW_READY: frozenset(
        {
            CoordinatorState.RISK_ANALYZED,
            CoordinatorState.CANCELLED,
            CoordinatorState.FAILED,
        }
    ),
    CoordinatorState.RISK_ANALYZED: frozenset(
        {
            CoordinatorState.WAITING_FOR_APPROVAL,
            CoordinatorState.APPROVED,
            CoordinatorState.READY,
            CoordinatorState.CANCELLED,
            CoordinatorState.FAILED,
        }
    ),
    CoordinatorState.WAITING_FOR_APPROVAL: frozenset(
        {
            CoordinatorState.APPROVED,
            CoordinatorState.CANCELLED,
            CoordinatorState.FAILED,
        }
    ),
    CoordinatorState.APPROVED: frozenset(
        {
            CoordinatorState.READY,
            CoordinatorState.CANCELLED,
            CoordinatorState.FAILED,
        }
    ),
    CoordinatorState.READY: frozenset({CoordinatorState.CANCELLED}),
    CoordinatorState.CANCELLED: frozenset(),
    CoordinatorState.FAILED: frozenset(),
}


class ExecutionStateMachine:
    """Apply validated transitions by returning new coordination snapshots."""

    @property
    def transitions(self) -> dict[CoordinatorState, frozenset[CoordinatorState]]:
        """Return a detached view of supported transitions."""

        return dict(_ALLOWED_TRANSITIONS)

    def can_transition(
        self,
        current: CoordinatorState,
        target: CoordinatorState,
    ) -> bool:
        """Return whether ``current`` may transition to ``target``."""

        if not isinstance(current, CoordinatorState) or not isinstance(
            target, CoordinatorState
        ):
            return False
        return target in _ALLOWED_TRANSITIONS[current]

    def transition(
        self,
        coordination: ExecutionCoordination,
        target: CoordinatorState,
        *,
        reason: str,
        at: datetime | None = None,
    ) -> ExecutionCoordination:
        """Return a new lifecycle snapshot in ``target`` state."""

        if not isinstance(coordination, ExecutionCoordination):
            raise TypeError("transition requires an ExecutionCoordination")
        if not isinstance(target, CoordinatorState):
            raise TypeError("target must be a CoordinatorState")
        if not self.can_transition(coordination.state, target):
            raise InvalidStateTransitionError(
                f"cannot transition from {coordination.state.value} to {target.value}"
            )
        timestamp = at or utc_now()
        if timestamp < coordination.updated_at:
            raise InvalidStateTransitionError(
                "transition timestamp cannot precede the current snapshot"
            )
        transition = StateTransition(
            from_state=coordination.state,
            to_state=target,
            reason=reason,
            transitioned_at=timestamp,
        )
        return replace(
            coordination,
            state=target,
            transitions=(*coordination.transitions, transition),
            updated_at=timestamp,
        )


CoordinatorStateMachine = ExecutionStateMachine
StateMachine = ExecutionStateMachine


__all__ = [
    "CoordinatorStateMachine",
    "ExecutionStateMachine",
    "StateMachine",
]
