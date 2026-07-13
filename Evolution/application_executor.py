"""Standalone placeholder application executor for future Phase 10 management work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Literal

from .execution_validator import ExecutionValidationReason, ExecutionValidationResult
from .models import stable_id


class ApplicationOperation(str, Enum):
    """The closed application-management operations represented by this placeholder."""

    LAUNCH_APPLICATION = "launch_application"
    CLOSE_APPLICATION = "close_application"
    FOCUS_APPLICATION = "focus_application"
    MINIMIZE_APPLICATION = "minimize_application"
    MAXIMIZE_APPLICATION = "maximize_application"
    RESTART_APPLICATION = "restart_application"
    QUERY_APPLICATION = "query_application"


@dataclass(slots=True, frozen=True)
class ApplicationExecutionRequest:
    """One future application request bound to a prior typed ALLOW validation result."""

    validation_result: ExecutionValidationResult
    operation: ApplicationOperation
    application_id: str


@dataclass(slots=True, frozen=True)
class ApplicationExecutionResult:
    """One deterministic placeholder result that never creates, controls, or queries a process."""

    decision: Literal["simulated", "rejected"]
    reason_code: str
    reason: str
    operation: ApplicationOperation | None = None
    application_id: str = ""
    context_snapshot_id: str = ""
    execution_id: str = ""
    operating_system_interaction_performed: bool = False
    process_created: bool = False
    process_terminated: bool = False
    desktop_interaction_performed: bool = False
    filesystem_operation_performed: bool = False

    @property
    def successful(self) -> bool:
        """Return True only when one typed application operation was simulated."""

        return self.decision == "simulated"


_APPLICATION_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


class ApplicationExecutorService:
    """Simulate closed application-management operations without host or runtime integration."""

    def list_supported_operations(self) -> tuple[ApplicationOperation, ...]:
        """Return all supported placeholder operations in deterministic declaration order."""

        return tuple(ApplicationOperation)

    def execute(self, request: ApplicationExecutionRequest) -> ApplicationExecutionResult:
        """Return one typed placeholder result after validating explicit in-memory request data."""

        if not isinstance(request, ApplicationExecutionRequest):
            return self._reject(
                reason_code="invalid_application_execution_request",
                reason="Application execution requires one typed ApplicationExecutionRequest.",
            )
        if not isinstance(request.operation, ApplicationOperation):
            return self._reject(
                reason_code="invalid_application_operation",
                reason="Application execution accepts only one typed supported application operation.",
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
        application_id = self._normalize_application_id(request.application_id)
        if application_id is None:
            return self._reject(
                reason_code="invalid_application_identifier",
                reason="Application identifiers must be compact local identifiers without paths, URLs, or whitespace.",
                operation=request.operation,
                validation_result=request.validation_result,
            )

        execution_id = stable_id(
            "application_execution_placeholder",
            request.operation.value,
            application_id,
            request.validation_result.action_id,
            request.validation_result.context_snapshot_id,
            request.validation_result.mutation_approval_id,
            request.validation_result.recovery_outcome_id,
            request.validation_result.mutation_target_ids,
        )
        return ApplicationExecutionResult(
            decision="simulated",
            reason_code="application_operation_simulated",
            reason="The approved application operation was represented as a deterministic placeholder only.",
            operation=request.operation,
            application_id=application_id,
            context_snapshot_id=request.validation_result.context_snapshot_id,
            execution_id=execution_id,
        )

    def _validate_prior_result(
        self,
        validation_result: ExecutionValidationResult,
    ) -> tuple[str, str] | None:
        """Require complete immutable evidence from the standalone execution validation boundary."""

        if not isinstance(validation_result, ExecutionValidationResult):
            return (
                "execution_validation_required",
                "Application execution requires one typed prior ExecutionValidationResult.",
            )
        if (
            not validation_result.allowed
            or validation_result.decision != "ALLOW"
            or validation_result.reason is not ExecutionValidationReason.ALLOWED
        ):
            return (
                "execution_not_validated",
                "Application execution remains denied until prior validation explicitly allows it.",
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
                "Application execution requires complete action, context, approval, recovery, and target bindings.",
            )
        return None

    def _normalize_application_id(self, value: str) -> str | None:
        """Return one normalized local application identifier without resolving any host application."""

        if not isinstance(value, str) or value != value.strip() or not _APPLICATION_IDENTIFIER_PATTERN.fullmatch(value):
            return None
        return value.lower()

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        operation: ApplicationOperation | None = None,
        validation_result: ExecutionValidationResult | None = None,
    ) -> ApplicationExecutionResult:
        """Build one typed rejection without application, process, desktop, or filesystem interaction."""

        return ApplicationExecutionResult(
            decision="rejected",
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            context_snapshot_id=(
                validation_result.context_snapshot_id
                if isinstance(validation_result, ExecutionValidationResult)
                else ""
            ),
        )


__all__ = [
    "ApplicationExecutionRequest",
    "ApplicationExecutionResult",
    "ApplicationExecutorService",
    "ApplicationOperation",
]
