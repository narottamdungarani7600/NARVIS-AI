"""Standalone fail-closed validation for future Phase 10 execution requests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from .action_registry import ActionCategory, ActionRecord, ActionRegistryService
from .execution_context import ExecutionContextService, ExecutionContextSnapshot
from .models import MutationApproval, MutationTarget, RecoveryOutcome
from .mutation_policy import MutationGuardRequest, MutationGuardService


class ExecutionValidationReason(str, Enum):
    """The closed reasons emitted by the future-execution validation boundary."""

    ALLOWED = "allowed"
    INVALID_REQUEST = "invalid_request"
    ACTION_UNREGISTERED = "action_unregistered"
    UNSUPPORTED_ACTION_CATEGORY = "unsupported_action_category"
    CONTEXT_INVALID = "context_invalid"
    CONTEXT_SNAPSHOT_UNRECOGNIZED = "context_snapshot_unrecognized"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    MUTATION_APPROVAL_INVALID = "mutation_approval_invalid"
    MUTATION_APPROVAL_REFERENCE_REQUIRED = "mutation_approval_reference_required"
    MUTATION_APPROVAL_REFERENCE_MISMATCH = "mutation_approval_reference_mismatch"
    MUTATION_APPROVAL_EXPIRED = "mutation_approval_expired"
    MUTATION_APPROVAL_MODE_MISMATCH = "mutation_approval_mode_mismatch"
    RECOVERY_OUTCOME_REQUIRED = "recovery_outcome_required"
    RECOVERY_OUTCOME_INVALID = "recovery_outcome_invalid"
    RECOVERY_NOT_READY = "recovery_not_ready"
    RECOVERY_APPROVAL_BINDING_MISMATCH = "recovery_approval_binding_mismatch"
    MUTATION_TARGETS_REQUIRED = "mutation_targets_required"
    MUTATION_TARGET_INVALID = "mutation_target_invalid"
    MUTATION_TARGET_APPROVAL_MISMATCH = "mutation_target_approval_mismatch"
    PROTECTED_TARGET_RESTRICTED = "protected_target_restricted"
    MUTATION_TARGET_DENIED = "mutation_target_denied"


@dataclass(slots=True, frozen=True)
class ExecutionValidationRequest:
    """One explicit, non-executing future-action request to validate."""

    action: ActionRecord | str
    context_snapshot: ExecutionContextSnapshot
    mutation_approval: MutationApproval | None
    mutation_approval_reference: str
    recovery_outcome: RecoveryOutcome | None
    mutation_targets: tuple[MutationTarget, ...]
    execution_mode: str
    evaluated_at: datetime


@dataclass(slots=True, frozen=True)
class ExecutionValidationResult:
    """One typed ALLOW or DENY result that never enables or invokes execution."""

    decision: Literal["ALLOW", "DENY"]
    reason: ExecutionValidationReason
    detail: str
    action_id: str = ""
    context_snapshot_id: str = ""
    mutation_approval_id: str = ""
    recovery_outcome_id: str = ""
    mutation_target_ids: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        """Return True only for an explicit, fully validated future-action request."""

        return self.decision == "ALLOW"

    @property
    def reason_code(self) -> str:
        """Return the stable machine-readable typed reason value."""

        return self.reason.value


_TARGET_SURFACES = {
    "approved_source_file": "approved_source_file",
    "code_development": "approved_source_file",
    "package_management": "package",
    "plugin_management": "plugin",
    "sandbox_execution": "sandbox",
}
_ALLOWED_EXECUTION_MODES = frozenset({"apply", "rollback"})


def _normalized_text(value: Any) -> str:
    """Return one bounded comparison value without interpreting it as an instruction."""

    return value.strip() if isinstance(value, str) else ""


def _normalized_key(value: Any) -> str:
    """Return one normalized key used only for closed-set membership checks."""

    return _normalized_text(value).lower()


def _normalized_timestamp(value: Any) -> datetime | None:
    """Return one UTC timestamp from explicit supplied data without reading the host clock."""

    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ExecutionValidatorService:
    """Validate future-action prerequisites without runtime wiring, mutation, or execution."""

    def __init__(
        self,
        *,
        action_registry: ActionRegistryService | None = None,
        context_service: ExecutionContextService | None = None,
        mutation_guard: MutationGuardService | None = None,
        workspace_root: str | Path | None = None,
        supported_action_categories: Iterable[ActionCategory] | None = None,
    ) -> None:
        self.action_registry = action_registry or ActionRegistryService()
        self.context_service = context_service or ExecutionContextService()
        self.mutation_guard = mutation_guard or MutationGuardService(workspace_root=workspace_root)
        categories = tuple(ActionCategory) if supported_action_categories is None else tuple(supported_action_categories)
        if not categories or any(not isinstance(category, ActionCategory) for category in categories):
            raise ValueError("Execution validation requires one or more typed supported action categories.")
        self._supported_action_categories = tuple(dict.fromkeys(categories))

    def list_supported_action_categories(self) -> tuple[ActionCategory, ...]:
        """Return the immutable supported future-action categories in declaration order."""

        return self._supported_action_categories

    def validate(self, request: ExecutionValidationRequest) -> ExecutionValidationResult:
        """Return one deterministic typed permission result without invoking an action."""

        if not isinstance(request, ExecutionValidationRequest):
            return self._deny(
                ExecutionValidationReason.INVALID_REQUEST,
                "Execution validation requires one typed ExecutionValidationRequest.",
            )

        action_validation = self.action_registry.validate_action(request.action)
        if not action_validation.valid or action_validation.action is None:
            return self._deny(
                ExecutionValidationReason.ACTION_UNREGISTERED,
                "The requested future action is not registered as an exact inert action record.",
                request,
            )
        action = action_validation.action
        if action.category not in self._supported_action_categories:
            return self._deny(
                ExecutionValidationReason.UNSUPPORTED_ACTION_CATEGORY,
                "The registered action category is not supported by this validation boundary.",
                request,
            )

        context_validation = self.context_service.validate_snapshot(request.context_snapshot)
        if not context_validation.valid:
            return self._deny(
                ExecutionValidationReason.CONTEXT_INVALID,
                "The supplied execution context snapshot is not internally valid.",
                request,
            )
        assert isinstance(request.context_snapshot, ExecutionContextSnapshot)
        retained_snapshot = self.context_service.get_snapshot(request.context_snapshot.snapshot_id)
        if retained_snapshot != request.context_snapshot:
            return self._deny(
                ExecutionValidationReason.CONTEXT_SNAPSHOT_UNRECOGNIZED,
                "The valid context snapshot was not previously retained by this context service.",
                request,
            )

        evaluated_at = _normalized_timestamp(request.evaluated_at)
        if evaluated_at is None:
            return self._deny(
                ExecutionValidationReason.INVALID_REQUEST,
                "Execution validation requires one explicit evaluation timestamp.",
                request,
            )
        execution_mode = _normalized_key(request.execution_mode)
        if execution_mode not in _ALLOWED_EXECUTION_MODES:
            return self._deny(
                ExecutionValidationReason.MUTATION_APPROVAL_INVALID,
                "Execution validation accepts only apply or rollback modes.",
                request,
            )

        approval = request.mutation_approval
        if approval is None:
            return self._deny(
                ExecutionValidationReason.HUMAN_APPROVAL_REQUIRED,
                "A current explicit human MutationApproval is required before future execution can be permitted.",
                request,
            )
        if not isinstance(approval, MutationApproval):
            return self._deny(
                ExecutionValidationReason.MUTATION_APPROVAL_INVALID,
                "Execution validation accepts only a typed MutationApproval record.",
                request,
            )
        approval_error = self._validate_approval(approval, request, evaluated_at, execution_mode)
        if approval_error is not None:
            reason, detail = approval_error
            return self._deny(reason, detail, request)

        recovery_error = self._validate_recovery(request.recovery_outcome, approval)
        if recovery_error is not None:
            reason, detail = recovery_error
            return self._deny(reason, detail, request)

        target_error = self._validate_targets(request.mutation_targets, approval)
        if target_error is not None:
            reason, detail = target_error
            return self._deny(reason, detail, request)

        for target in request.mutation_targets:
            target_error = self._validate_target_surface(target)
            if target_error is not None:
                reason, detail = target_error
                return self._deny(reason, detail, request)

        return self._allow(request, action.action_id)

    def _validate_approval(
        self,
        approval: MutationApproval,
        request: ExecutionValidationRequest,
        evaluated_at: datetime,
        execution_mode: str,
    ) -> tuple[ExecutionValidationReason, str] | None:
        """Validate immutable human-approval facts without changing or re-recording approval."""

        reference = _normalized_text(request.mutation_approval_reference)
        if not reference:
            return (
                ExecutionValidationReason.MUTATION_APPROVAL_REFERENCE_REQUIRED,
                "The request must include the exact MutationApproval identifier it intends to use.",
            )
        if reference != approval.mutation_approval_id:
            return (
                ExecutionValidationReason.MUTATION_APPROVAL_REFERENCE_MISMATCH,
                "The supplied mutation approval reference does not match the typed approval record.",
            )
        if (
            _normalized_key(approval.decision) != "approved"
            or not _normalized_text(approval.mutation_approval_id)
            or not _normalized_text(approval.mutation_approval_fingerprint)
            or not _normalized_text(approval.approval_decision_id)
            or not _normalized_text(approval.actor)
        ):
            return (
                ExecutionValidationReason.MUTATION_APPROVAL_INVALID,
                "The mutation approval must contain an explicit human-approved decision and complete identity bindings.",
            )
        expires_at = _normalized_timestamp(approval.expires_at)
        if expires_at is None:
            return (
                ExecutionValidationReason.MUTATION_APPROVAL_INVALID,
                "The mutation approval must include one valid expiry timestamp.",
            )
        if expires_at <= evaluated_at:
            return (
                ExecutionValidationReason.MUTATION_APPROVAL_EXPIRED,
                "The mutation approval has expired and cannot permit future execution.",
            )
        if _normalized_key(approval.mode) != execution_mode:
            return (
                ExecutionValidationReason.MUTATION_APPROVAL_MODE_MISMATCH,
                "The requested execution mode does not match the exact approved mutation mode.",
            )
        return None

    def _validate_recovery(
        self,
        recovery_outcome: RecoveryOutcome | None,
        approval: MutationApproval,
    ) -> tuple[ExecutionValidationReason, str] | None:
        """Validate ready recovery and its exact immutable binding to the supplied approval."""

        if recovery_outcome is None:
            return (
                ExecutionValidationReason.RECOVERY_OUTCOME_REQUIRED,
                "A ready typed RecoveryOutcome is required before future execution can be permitted.",
            )
        if not isinstance(recovery_outcome, RecoveryOutcome):
            return (
                ExecutionValidationReason.RECOVERY_OUTCOME_INVALID,
                "Execution validation accepts only a typed RecoveryOutcome record.",
            )
        if (
            not _normalized_text(recovery_outcome.recovery_outcome_id)
            or not _normalized_text(recovery_outcome.recovery_run_id)
            or not _normalized_text(recovery_outcome.run_fingerprint)
            or not _normalized_text(recovery_outcome.outcome_fingerprint)
        ):
            return (
                ExecutionValidationReason.RECOVERY_OUTCOME_INVALID,
                "The recovery outcome must contain complete immutable identity and fingerprint bindings.",
            )
        if _normalized_key(recovery_outcome.status) != "ready":
            return (
                ExecutionValidationReason.RECOVERY_NOT_READY,
                "Future execution remains denied until the recovery outcome has status 'ready'.",
            )
        if (
            approval.recovery_outcome_id != recovery_outcome.recovery_outcome_id
            or approval.recovery_outcome_fingerprint != recovery_outcome.outcome_fingerprint
            or approval.recovery_run_id != recovery_outcome.recovery_run_id
            or approval.recovery_run_fingerprint != recovery_outcome.run_fingerprint
        ):
            return (
                ExecutionValidationReason.RECOVERY_APPROVAL_BINDING_MISMATCH,
                "The mutation approval must exactly bind to the supplied ready recovery outcome and recovery run.",
            )
        return None

    def _validate_targets(
        self,
        targets: tuple[MutationTarget, ...],
        approval: MutationApproval,
    ) -> tuple[ExecutionValidationReason, str] | None:
        """Validate exact typed target identity before evaluating any mutation surface."""

        if not isinstance(targets, tuple) or not targets:
            return (
                ExecutionValidationReason.MUTATION_TARGETS_REQUIRED,
                "Future execution validation requires one non-empty ordered tuple of mutation targets.",
            )
        if any(not isinstance(target, MutationTarget) for target in targets):
            return (
                ExecutionValidationReason.MUTATION_TARGET_INVALID,
                "Future execution validation accepts only typed MutationTarget records.",
            )
        target_ids = tuple(target.mutation_target_id for target in targets)
        if (
            any(not _normalized_text(target_id) for target_id in target_ids)
            or len(set(target_ids)) != len(target_ids)
            or target_ids != tuple(approval.mutation_target_ids)
        ):
            return (
                ExecutionValidationReason.MUTATION_TARGET_APPROVAL_MISMATCH,
                "Mutation target identifiers must exactly match the ordered target list bound to human approval.",
            )
        return None

    def _validate_target_surface(
        self,
        target: MutationTarget,
    ) -> tuple[ExecutionValidationReason, str] | None:
        """Reapply the existing deny-by-default guard to every approved mutation target."""

        surface_id = _TARGET_SURFACES.get(_normalized_key(target.executor_category))
        if surface_id is None:
            return (
                ExecutionValidationReason.MUTATION_TARGET_DENIED,
                "The mutation target does not map to one supported protected mutation surface.",
            )
        if not isinstance(target.metadata, dict):
            return (
                ExecutionValidationReason.MUTATION_TARGET_INVALID,
                "Mutation target metadata must remain a typed mapping for surface validation.",
            )
        guard_decision = self.mutation_guard.validate(
            MutationGuardRequest(
                surface_id=surface_id,
                locator=target.locator,
                target_kind=target.target_kind,
                risk_classification=target.risk_classification,
                metadata=target.metadata,
            )
        )
        if guard_decision.allowed:
            return None
        if guard_decision.reason_code == "protected_surface":
            return (
                ExecutionValidationReason.PROTECTED_TARGET_RESTRICTED,
                "The mutation target is protected and cannot be permitted for future execution.",
            )
        return (
            ExecutionValidationReason.MUTATION_TARGET_DENIED,
            "The mutation target was denied by the existing workspace and mutation-surface guard.",
        )

    def _allow(self, request: ExecutionValidationRequest, action_id: str) -> ExecutionValidationResult:
        """Build one explicit typed ALLOW result without enabling execution in any service."""

        return ExecutionValidationResult(
            decision="ALLOW",
            reason=ExecutionValidationReason.ALLOWED,
            detail="All registered action, context, approval, recovery, target, and protected-surface checks passed without execution.",
            action_id=action_id,
            context_snapshot_id=request.context_snapshot.snapshot_id,
            mutation_approval_id=request.mutation_approval.mutation_approval_id if request.mutation_approval else "",
            recovery_outcome_id=request.recovery_outcome.recovery_outcome_id if request.recovery_outcome else "",
            mutation_target_ids=tuple(target.mutation_target_id for target in request.mutation_targets),
        )

    def _deny(
        self,
        reason: ExecutionValidationReason,
        detail: str,
        request: ExecutionValidationRequest | None = None,
    ) -> ExecutionValidationResult:
        """Build one explicit typed DENY result without execution, mutation, or orchestration."""

        action_id = ""
        context_snapshot_id = ""
        mutation_approval_id = ""
        recovery_outcome_id = ""
        mutation_target_ids: tuple[str, ...] = ()
        if isinstance(request, ExecutionValidationRequest):
            action_id = request.action.action_id if isinstance(request.action, ActionRecord) else _normalized_text(request.action)
            context_snapshot_id = (
                request.context_snapshot.snapshot_id
                if isinstance(request.context_snapshot, ExecutionContextSnapshot)
                else ""
            )
            mutation_approval_id = (
                request.mutation_approval.mutation_approval_id
                if isinstance(request.mutation_approval, MutationApproval)
                else ""
            )
            recovery_outcome_id = (
                request.recovery_outcome.recovery_outcome_id
                if isinstance(request.recovery_outcome, RecoveryOutcome)
                else ""
            )
            if isinstance(request.mutation_targets, tuple):
                mutation_target_ids = tuple(
                    target.mutation_target_id
                    for target in request.mutation_targets
                    if isinstance(target, MutationTarget)
                )
        return ExecutionValidationResult(
            decision="DENY",
            reason=reason,
            detail=detail,
            action_id=action_id,
            context_snapshot_id=context_snapshot_id,
            mutation_approval_id=mutation_approval_id,
            recovery_outcome_id=recovery_outcome_id,
            mutation_target_ids=mutation_target_ids,
        )


__all__ = [
    "ExecutionValidationReason",
    "ExecutionValidationRequest",
    "ExecutionValidationResult",
    "ExecutionValidatorService",
]
