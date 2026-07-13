"""Standalone non-executing workflow composition for future Phase 10 actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .execution_validator import ExecutionValidationReason, ExecutionValidationResult
from .models import stable_id


class WorkflowExecutionStatus(str, Enum):
    """The terminal states emitted by the non-executing workflow composition boundary."""

    PLANNED = "planned"
    REJECTED = "rejected"


@dataclass(slots=True, frozen=True)
class WorkflowExecutionStep:
    """One validated future-action step with explicit sequential dependency bindings."""

    step_id: str
    sequence: int
    validation_result: ExecutionValidationResult
    depends_on_step_ids: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class WorkflowExecutionRequest:
    """One typed request to compose a deterministic future-action workflow without execution."""

    workflow_id: str
    steps: tuple[WorkflowExecutionStep, ...]


@dataclass(slots=True, frozen=True)
class WorkflowExecutionResult:
    """One typed workflow plan or rejection that never invokes another executor."""

    status: WorkflowExecutionStatus
    reason_code: str
    reason: str
    workflow_id: str = ""
    workflow_fingerprint: str = ""
    workflow_plan_id: str = ""
    ordered_steps: tuple[WorkflowExecutionStep, ...] = ()
    executor_invoked: bool = False
    desktop_executor_invoked: bool = False
    application_executor_invoked: bool = False
    browser_executor_invoked: bool = False
    filesystem_operation_performed: bool = False
    network_accessed: bool = False
    operating_system_interaction_performed: bool = False
    browser_interaction_performed: bool = False

    @property
    def planned(self) -> bool:
        """Return True only when a deterministic workflow plan was composed."""

        return self.status is WorkflowExecutionStatus.PLANNED


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


class WorkflowExecutorService:
    """Compose validated future-action workflows without executor, runtime, or host interaction."""

    def compose(self, request: WorkflowExecutionRequest) -> WorkflowExecutionResult:
        """Return one deterministic dependency-respecting plan or a typed fail-closed rejection."""

        if not isinstance(request, WorkflowExecutionRequest):
            return self._reject(
                reason_code="invalid_workflow_execution_request",
                reason="Workflow composition requires one typed WorkflowExecutionRequest.",
            )
        if not self._is_identifier(request.workflow_id):
            return self._reject(
                reason_code="invalid_workflow_identifier",
                reason="Workflow identifiers must be compact non-empty identifiers without paths or whitespace.",
            )
        if not isinstance(request.steps, tuple) or not request.steps:
            return self._reject(
                reason_code="workflow_steps_required",
                reason="Workflow composition requires one non-empty typed step tuple.",
                workflow_id=request.workflow_id,
            )
        if any(not isinstance(step, WorkflowExecutionStep) for step in request.steps):
            return self._reject(
                reason_code="invalid_workflow_step",
                reason="Workflow composition accepts only typed WorkflowExecutionStep records.",
                workflow_id=request.workflow_id,
            )

        structure_error = self._validate_structure(request.steps)
        if structure_error is not None:
            reason_code, reason = structure_error
            return self._reject(reason_code=reason_code, reason=reason, workflow_id=request.workflow_id)
        validation_error = self._validate_prior_results(request.steps)
        if validation_error is not None:
            reason_code, reason = validation_error
            return self._reject(reason_code=reason_code, reason=reason, workflow_id=request.workflow_id)

        step_by_id = {step.step_id: step for step in request.steps}
        dependency_error = self._validate_dependencies(step_by_id)
        if dependency_error is not None:
            reason_code, reason = dependency_error
            return self._reject(reason_code=reason_code, reason=reason, workflow_id=request.workflow_id)
        if self._has_cycle(step_by_id):
            return self._reject(
                reason_code="workflow_dependency_cycle",
                reason="Workflow dependencies contain a cycle and cannot form a deterministic execution plan.",
                workflow_id=request.workflow_id,
            )
        ordering_error = self._validate_dependency_order(step_by_id)
        if ordering_error is not None:
            reason_code, reason = ordering_error
            return self._reject(reason_code=reason_code, reason=reason, workflow_id=request.workflow_id)

        ordered_steps = tuple(sorted(request.steps, key=lambda step: (step.sequence, step.step_id)))
        fingerprint = stable_id(
            "workflow_execution_fingerprint",
            request.workflow_id,
            tuple(
                (
                    step.step_id,
                    step.sequence,
                    step.depends_on_step_ids,
                    step.validation_result.action_id,
                    step.validation_result.context_snapshot_id,
                    step.validation_result.mutation_approval_id,
                    step.validation_result.recovery_outcome_id,
                    step.validation_result.mutation_target_ids,
                )
                for step in ordered_steps
            ),
        )
        return WorkflowExecutionResult(
            status=WorkflowExecutionStatus.PLANNED,
            reason_code="workflow_execution_plan_created",
            reason="Validated workflow steps were composed into a deterministic dependency-respecting plan without execution.",
            workflow_id=request.workflow_id,
            workflow_fingerprint=fingerprint,
            workflow_plan_id=stable_id("workflow_execution_plan", fingerprint),
            ordered_steps=ordered_steps,
        )

    def _validate_structure(
        self,
        steps: tuple[WorkflowExecutionStep, ...],
    ) -> tuple[str, str] | None:
        """Validate immutable step identities and complete one-based sequence numbering."""

        step_ids = tuple(step.step_id for step in steps)
        sequences = tuple(step.sequence for step in steps)
        if (
            not all(self._is_identifier(step_id) for step_id in step_ids)
            or len(set(step_ids)) != len(step_ids)
            or any(not isinstance(sequence, int) or isinstance(sequence, bool) for sequence in sequences)
            or set(sequences) != set(range(1, len(steps) + 1))
        ):
            return (
                "invalid_workflow_step_order",
                "Workflow step identifiers must be unique and sequences must be complete one-based integers.",
            )
        return None

    def _validate_prior_results(
        self,
        steps: tuple[WorkflowExecutionStep, ...],
    ) -> tuple[str, str] | None:
        """Require complete typed ALLOW results for every planned workflow step."""

        for step in steps:
            result = step.validation_result
            if not isinstance(result, ExecutionValidationResult):
                return (
                    "step_execution_validation_required",
                    "Every workflow step requires one typed prior ExecutionValidationResult.",
                )
            if (
                not result.allowed
                or result.decision != "ALLOW"
                or result.reason is not ExecutionValidationReason.ALLOWED
            ):
                return (
                    "step_execution_not_validated",
                    "Every workflow step must have one explicit prior ALLOW validation result.",
                )
            if (
                not result.action_id
                or not result.context_snapshot_id
                or not result.mutation_approval_id
                or not result.recovery_outcome_id
                or not result.mutation_target_ids
            ):
                return (
                    "step_validation_binding_incomplete",
                    "Every workflow step requires complete action, context, approval, recovery, and target bindings.",
                )
        return None

    def _validate_dependencies(
        self,
        step_by_id: dict[str, WorkflowExecutionStep],
    ) -> tuple[str, str] | None:
        """Validate typed, unique references only to distinct known workflow steps."""

        known_step_ids = set(step_by_id)
        for step in step_by_id.values():
            dependencies = step.depends_on_step_ids
            if not isinstance(dependencies, tuple) or any(not self._is_identifier(item) for item in dependencies):
                return (
                    "invalid_dependency_reference",
                    "Workflow dependency references must be a tuple of compact step identifiers.",
                )
            if len(set(dependencies)) != len(dependencies) or step.step_id in dependencies:
                return (
                    "invalid_dependency_reference",
                    "Workflow dependencies must be unique references to distinct workflow steps.",
                )
            if any(dependency not in known_step_ids for dependency in dependencies):
                return (
                    "unknown_dependency_reference",
                    "Every workflow dependency must reference one known workflow step.",
                )
        return None

    def _has_cycle(self, step_by_id: dict[str, WorkflowExecutionStep]) -> bool:
        """Return True when depth-first traversal finds a dependency cycle."""

        visiting: set[str] = set()
        completed: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in completed:
                return False
            if step_id in visiting:
                return True
            visiting.add(step_id)
            if any(visit(dependency) for dependency in step_by_id[step_id].depends_on_step_ids):
                return True
            visiting.remove(step_id)
            completed.add(step_id)
            return False

        return any(visit(step_id) for step_id in sorted(step_by_id))

    def _validate_dependency_order(
        self,
        step_by_id: dict[str, WorkflowExecutionStep],
    ) -> tuple[str, str] | None:
        """Require every prerequisite to appear before its dependent in the explicit sequence order."""

        for step in step_by_id.values():
            if any(step_by_id[dependency].sequence >= step.sequence for dependency in step.depends_on_step_ids):
                return (
                    "dependency_order_invalid",
                    "Each workflow dependency must have a lower sequence than the step that depends on it.",
                )
        return None

    def _is_identifier(self, value: str) -> bool:
        """Return True only for compact immutable workflow identifiers without path semantics."""

        return bool(isinstance(value, str) and value == value.strip() and _IDENTIFIER_PATTERN.fullmatch(value))

    def _reject(self, *, reason_code: str, reason: str, workflow_id: str = "") -> WorkflowExecutionResult:
        """Build one typed rejection without executor invocation or host interaction."""

        return WorkflowExecutionResult(
            status=WorkflowExecutionStatus.REJECTED,
            reason_code=reason_code,
            reason=reason,
            workflow_id=workflow_id if self._is_identifier(workflow_id) else "",
        )


__all__ = [
    "WorkflowExecutionRequest",
    "WorkflowExecutionResult",
    "WorkflowExecutionStatus",
    "WorkflowExecutionStep",
    "WorkflowExecutorService",
]
