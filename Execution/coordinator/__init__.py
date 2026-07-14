"""Public API for the NARVIS Safe Execution Coordinator."""

from .coordinator import Coordinator, ExecutionCoordinator, SafeExecutionCoordinator
from .events import (
    EXECUTION_CANCELLED_EVENT,
    EXECUTION_CREATED_EVENT,
    EXECUTION_FAILED_EVENT,
    EXECUTION_READY_EVENT,
    EXECUTION_VALIDATED_EVENT,
    CoordinatorEvents,
    LifecycleEventSink,
)
from .exceptions import (
    CoordinationNotFoundError,
    CoordinatorError,
    CoordinatorValidationError,
    DuplicateCoordinationError,
    InvalidStateTransitionError,
    PlanCreationError,
    ReadinessError,
)
from .models import (
    ApprovalRecord,
    CoordinationRecord,
    CoordinatorResult,
    CoordinatorState,
    ExecutionCoordination,
    ExecutionPlan,
    ExecutionReadinessReport,
    ExecutionState,
    ReadinessReport,
    SafeExecutionPlan,
    StateTransition,
    ValidationReport,
)
from .readiness import ExecutionReadinessEvaluator, ReadinessEvaluator
from .state_machine import (
    CoordinatorStateMachine,
    ExecutionStateMachine,
    StateMachine,
)
from .validator import CoordinatorValidator, ExecutionValidator

__all__ = [
    "ApprovalRecord",
    "CoordinationNotFoundError",
    "CoordinationRecord",
    "Coordinator",
    "CoordinatorError",
    "CoordinatorEvents",
    "CoordinatorResult",
    "CoordinatorState",
    "CoordinatorStateMachine",
    "CoordinatorValidationError",
    "DuplicateCoordinationError",
    "EXECUTION_CANCELLED_EVENT",
    "EXECUTION_CREATED_EVENT",
    "EXECUTION_FAILED_EVENT",
    "EXECUTION_READY_EVENT",
    "EXECUTION_VALIDATED_EVENT",
    "ExecutionCoordination",
    "ExecutionCoordinator",
    "ExecutionPlan",
    "ExecutionReadinessEvaluator",
    "ExecutionReadinessReport",
    "ExecutionState",
    "ExecutionStateMachine",
    "ExecutionValidator",
    "InvalidStateTransitionError",
    "LifecycleEventSink",
    "PlanCreationError",
    "ReadinessError",
    "ReadinessEvaluator",
    "ReadinessReport",
    "SafeExecutionCoordinator",
    "SafeExecutionPlan",
    "StateMachine",
    "StateTransition",
    "ValidationReport",
]
