"""Standalone trusted authorization boundary for future real execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .action_registry import ActionCategory
from .execution_validator import (
    ExecutionValidationReason,
    ExecutionValidationRequest,
    ExecutionValidationResult,
    ExecutionValidatorService,
)


class TrustedExecutionDecisionType(str, Enum):
    """The only authorization decisions emitted by the trusted gateway."""

    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(slots=True, frozen=True)
class TrustedExecutionDecision:
    """One immutable gateway decision containing exact validation bindings only."""

    decision: TrustedExecutionDecisionType
    reason: ExecutionValidationReason
    detail: str
    validation_result: ExecutionValidationResult
    action_id: str = ""
    context_snapshot_id: str = ""
    mutation_approval_id: str = ""
    recovery_outcome_id: str = ""
    mutation_target_ids: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        """Return True only for one explicit gateway ALLOW decision."""

        return self.decision is TrustedExecutionDecisionType.ALLOW

    @property
    def reason_code(self) -> str:
        """Return the stable machine-readable validation reason."""

        return self.reason.value


class TrustedExecutionGateway:
    """Authorize future execution without invoking runtime or host capabilities.

    The gateway deliberately orchestrates the existing Phase 10 validator instead
    of duplicating its proposal, approval, recovery, mutation-target, expiry, and
    protected-surface checks.  A distinct decision type gives later execution
    integrations one boundary-specific authorization artifact to require.
    """

    def __init__(self, *, validator: ExecutionValidatorService | None = None) -> None:
        if validator is not None and not isinstance(validator, ExecutionValidatorService):
            raise ValueError("Trusted execution requires one typed ExecutionValidatorService.")
        self._validator = validator or ExecutionValidatorService()

    def list_supported_action_categories(self) -> tuple[ActionCategory, ...]:
        """Return the closed action categories accepted by the delegated validator."""

        return self._validator.list_supported_action_categories()

    def authorize(self, request: ExecutionValidationRequest) -> TrustedExecutionDecision:
        """Return one typed decision without executing or mutating anything."""

        validation_result = self._validator.validate(request)
        decision = (
            TrustedExecutionDecisionType.ALLOW
            if validation_result.allowed
            else TrustedExecutionDecisionType.DENY
        )
        return TrustedExecutionDecision(
            decision=decision,
            reason=validation_result.reason,
            detail=validation_result.detail,
            validation_result=validation_result,
            action_id=validation_result.action_id,
            context_snapshot_id=validation_result.context_snapshot_id,
            mutation_approval_id=validation_result.mutation_approval_id,
            recovery_outcome_id=validation_result.recovery_outcome_id,
            mutation_target_ids=validation_result.mutation_target_ids,
        )


TrustedExecutionGatewayService = TrustedExecutionGateway


__all__ = [
    "TrustedExecutionDecision",
    "TrustedExecutionDecisionType",
    "TrustedExecutionGateway",
    "TrustedExecutionGatewayService",
]
