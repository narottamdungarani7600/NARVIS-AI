"""Standalone placeholder desktop executor for future Phase 10 automation work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from .execution_validator import ExecutionValidationReason, ExecutionValidationResult
from .models import stable_id


class DesktopExecutionOperation(str, Enum):
    """The closed desktop actions this placeholder executor can represent."""

    OPEN_APPLICATION = "open_application"
    FOCUS_WINDOW = "focus_window"
    TYPE_TEXT = "type_text"
    MOUSE_CLICK = "mouse_click"
    SCREENSHOT = "screenshot"


@dataclass(slots=True, frozen=True)
class DesktopExecutionRequest:
    """One future desktop-action request bound to a prior typed ALLOW validation result."""

    validation_result: ExecutionValidationResult
    operation: DesktopExecutionOperation


@dataclass(slots=True, frozen=True)
class DesktopExecutionResult:
    """One deterministic placeholder result that never represents a real desktop interaction."""

    decision: Literal["simulated", "rejected"]
    reason_code: str
    reason: str
    operation: DesktopExecutionOperation | None = None
    action_id: str = ""
    context_snapshot_id: str = ""
    execution_id: str = ""
    desktop_interaction_performed: bool = False
    operating_system_api_invoked: bool = False
    filesystem_mutated: bool = False

    @property
    def successful(self) -> bool:
        """Return True only when a typed placeholder operation was simulated."""

        return self.decision == "simulated"


_ACTION_ID_BY_OPERATION = {
    DesktopExecutionOperation.OPEN_APPLICATION: "desktop.open_application",
    DesktopExecutionOperation.FOCUS_WINDOW: "desktop.focus_window",
    DesktopExecutionOperation.TYPE_TEXT: "keyboard.type_text",
    DesktopExecutionOperation.MOUSE_CLICK: "mouse.click",
    DesktopExecutionOperation.SCREENSHOT: "vision.capture_screenshot",
}


class DesktopExecutorService:
    """Simulate closed future desktop actions without runtime, OS, or executor integration."""

    def list_supported_operations(self) -> tuple[DesktopExecutionOperation, ...]:
        """Return the closed placeholder operation set in deterministic declaration order."""

        return tuple(DesktopExecutionOperation)

    def execute(self, request: DesktopExecutionRequest) -> DesktopExecutionResult:
        """Validate one already-approved request and return a non-interacting simulation result."""

        if not isinstance(request, DesktopExecutionRequest):
            return self._reject(
                reason_code="invalid_desktop_execution_request",
                reason="Desktop execution requires one typed DesktopExecutionRequest.",
            )
        if not isinstance(request.operation, DesktopExecutionOperation):
            return self._reject(
                reason_code="invalid_desktop_operation",
                reason="Desktop execution accepts only one typed supported desktop operation.",
            )
        validation_error = self._validate_prior_result(request.validation_result)
        if validation_error is not None:
            reason_code, reason = validation_error
            return self._reject(
                reason_code=reason_code,
                reason=reason,
                operation=request.operation,
                validation_result=request.validation_result,
            )

        expected_action_id = _ACTION_ID_BY_OPERATION[request.operation]
        if request.validation_result.action_id != expected_action_id:
            return self._reject(
                reason_code="desktop_operation_action_mismatch",
                reason="The requested desktop operation does not match the exact action approved by validation.",
                operation=request.operation,
                validation_result=request.validation_result,
            )

        execution_id = stable_id(
            "desktop_execution_placeholder",
            request.operation.value,
            request.validation_result.action_id,
            request.validation_result.context_snapshot_id,
            request.validation_result.mutation_approval_id,
            request.validation_result.recovery_outcome_id,
            request.validation_result.mutation_target_ids,
        )
        return DesktopExecutionResult(
            decision="simulated",
            reason_code="desktop_operation_simulated",
            reason="The approved desktop operation was represented as a deterministic placeholder only.",
            operation=request.operation,
            action_id=request.validation_result.action_id,
            context_snapshot_id=request.validation_result.context_snapshot_id,
            execution_id=execution_id,
        )

    def _validate_prior_result(
        self,
        validation_result: ExecutionValidationResult,
    ) -> tuple[str, str] | None:
        """Require complete immutable evidence from the standalone validation boundary."""

        if not isinstance(validation_result, ExecutionValidationResult):
            return (
                "execution_validation_required",
                "Desktop execution requires one typed prior ExecutionValidationResult.",
            )
        if (
            not validation_result.allowed
            or validation_result.decision != "ALLOW"
            or validation_result.reason is not ExecutionValidationReason.ALLOWED
        ):
            return (
                "execution_not_validated",
                "Desktop execution remains denied until the prior validation result explicitly allows it.",
            )
        if (
            not validation_result.action_id
            or not validation_result.context_snapshot_id
            or not validation_result.mutation_approval_id
            or not validation_result.recovery_outcome_id
            or not validation_result.mutation_target_ids
        ):
            return (
                "execution_validation_binding_incomplete",
                "Desktop execution requires complete action, context, approval, recovery, and target bindings.",
            )
        return None

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        operation: DesktopExecutionOperation | None = None,
        validation_result: ExecutionValidationResult | None = None,
    ) -> DesktopExecutionResult:
        """Build one typed rejection without action execution or host interaction."""

        return DesktopExecutionResult(
            decision="rejected",
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            action_id=validation_result.action_id if isinstance(validation_result, ExecutionValidationResult) else "",
            context_snapshot_id=(
                validation_result.context_snapshot_id
                if isinstance(validation_result, ExecutionValidationResult)
                else ""
            ),
        )


__all__ = [
    "DesktopExecutionOperation",
    "DesktopExecutionRequest",
    "DesktopExecutionResult",
    "DesktopExecutorService",
]
