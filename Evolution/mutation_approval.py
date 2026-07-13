"""Typed mutation approval recording and validation for future Phase 7 work."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import MutationApproval, compact_text, sanitize_durable_mapping, stable_id, utc_now

_ALLOWED_EXECUTION_MODES = frozenset({"apply", "rollback"})
_MUTATION_RUN_METADATA_KEY = "mutation_run_id"


def _normalized_key(value: str) -> str:
    """Normalize one approval key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


def _normalize_text(value: Any, *, max_chars: int = 120) -> str:
    """Normalize one text binding into a durable bounded string."""

    return compact_text(str(value or ""), max_chars=max_chars)


def _normalize_sequence(values: Any, *, max_chars: int = 120, allow_empty: bool) -> tuple[str, ...] | None:
    """Normalize one ordered identifier sequence without reordering or deduping."""

    if values is None:
        return () if allow_empty else None
    if not isinstance(values, list | tuple):
        return None

    normalized: list[str] = []
    for value in values:
        text = _normalize_text(value, max_chars=max_chars)
        if not text:
            return None
        normalized.append(text)

    if not normalized and not allow_empty:
        return None
    return tuple(normalized)


def _normalize_timestamp(value: Any) -> datetime | None:
    """Normalize one timestamp into an aware UTC datetime."""

    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True, frozen=True)
class MutationApprovalRequest:
    """One exact approval request or revalidation request for a mutation run."""

    proposal_id: str
    mutation_run_id: str
    approval_decision_id: str
    mutation_target_ids: tuple[str, ...]
    expires_at: datetime
    actor: str
    recovery_outcome_id: str = ""
    recovery_outcome_fingerprint: str = ""
    recovery_run_id: str = ""
    recovery_run_fingerprint: str = ""
    execution_request_id: str = ""
    request_fingerprint: str = ""
    plan_id: str = ""
    plan_fingerprint: str = ""
    proposal_fingerprint: str = ""
    proposal_version: int = 0
    execution_step_request_ids: tuple[str, ...] = ()
    mode: str = "apply"
    note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class MutationApprovalDecision:
    """One typed mutation approval decision."""

    decision: str
    proposal_id: str
    mutation_run_id: str
    mutation_target_ids: tuple[str, ...]
    mode: str
    reason_code: str
    reason: str
    expires_at: datetime | None = None
    mutation_approval: MutationApproval | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        """Return True only when the approval decision is explicitly approved."""

        return self.decision == "approved"


@dataclass(slots=True, frozen=True)
class _PreparedMutationApprovalRequest:
    """Normalized internal approval bindings shared by record and validate paths."""

    proposal_id: str
    mutation_run_id: str
    approval_decision_id: str
    mutation_target_ids: tuple[str, ...]
    expires_at: datetime
    actor: str
    recovery_outcome_id: str
    recovery_outcome_fingerprint: str
    recovery_run_id: str
    recovery_run_fingerprint: str
    execution_request_id: str
    request_fingerprint: str
    plan_id: str
    plan_fingerprint: str
    proposal_fingerprint: str
    proposal_version: int
    execution_step_request_ids: tuple[str, ...]
    mode: str
    note: str | None
    metadata: dict[str, Any]


class MutationApprovalService:
    """Record and revalidate narrow human mutation approvals without executing them."""

    def list_allowed_modes(self) -> tuple[str, ...]:
        """Return allowed execution modes in deterministic order."""

        return tuple(sorted(_ALLOWED_EXECUTION_MODES))

    def record_approval(
        self,
        request: MutationApprovalRequest,
        *,
        now: datetime | None = None,
    ) -> MutationApprovalDecision:
        """Build one exact mutation approval record when the request is valid."""

        current_time = _normalize_timestamp(now) or utc_now()
        prepared, invalid_decision = self._prepare_request(request, now=current_time)
        if invalid_decision is not None or prepared is None:
            return invalid_decision or self._deny(
                proposal_id="",
                mutation_run_id="",
                mutation_target_ids=(),
                mode="",
                reason_code="approval_request_invalid",
                reason="The mutation approval request could not be normalized safely.",
            )

        mutation_approval = self._build_mutation_approval(prepared)
        return self._approve(
            proposal_id=prepared.proposal_id,
            mutation_run_id=prepared.mutation_run_id,
            mutation_target_ids=prepared.mutation_target_ids,
            mode=prepared.mode,
            expires_at=prepared.expires_at,
            mutation_approval=mutation_approval,
            metadata={
                "validation_layer": "mutation_approval_service",
                "operation": "record_approval",
            },
        )

    def validate_approval(
        self,
        approval: MutationApproval,
        request: MutationApprovalRequest,
        *,
        now: datetime | None = None,
    ) -> MutationApprovalDecision:
        """Revalidate one mutation approval against one exact request binding."""

        current_time = _normalize_timestamp(now) or utc_now()
        prepared, invalid_decision = self._prepare_request(request, now=current_time)
        if invalid_decision is not None or prepared is None:
            return invalid_decision or self._deny(
                proposal_id=_normalize_text(getattr(approval, "proposal_id", ""), max_chars=120),
                mutation_run_id=self._bound_mutation_run_id(approval),
                mutation_target_ids=tuple(approval.mutation_target_ids),
                mode=_normalized_key(getattr(approval, "mode", "")),
                reason_code="approval_request_invalid",
                reason="The mutation approval request could not be normalized safely.",
                expires_at=_normalize_timestamp(getattr(approval, "expires_at", None)),
            )

        if _normalized_key(approval.decision) != "approved":
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="approval_not_granted",
                reason="Only an explicitly approved mutation approval can be used for validation.",
                expires_at=_normalize_timestamp(approval.expires_at),
                mutation_approval=approval,
            )

        bound_mutation_run_id = self._bound_mutation_run_id(approval)
        if not bound_mutation_run_id:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="approval_binding_missing",
                reason="The stored mutation approval is missing its bound mutation run identity.",
                expires_at=_normalize_timestamp(approval.expires_at),
                mutation_approval=approval,
                metadata={"missing_binding": _MUTATION_RUN_METADATA_KEY},
            )

        stored_expiry = _normalize_timestamp(approval.expires_at)
        if stored_expiry is None:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="approval_binding_missing",
                reason="The stored mutation approval is missing its expiry binding.",
                mutation_approval=approval,
                metadata={"missing_binding": "expires_at"},
            )
        if stored_expiry <= current_time:
            return self._decision(
                decision="expired",
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="approval_expired",
                reason="Expired mutation approvals cannot be reused.",
                expires_at=stored_expiry,
                mutation_approval=approval,
                metadata={
                    "validation_layer": "mutation_approval_service",
                    "operation": "validate_approval",
                },
            )
        if stored_expiry != prepared.expires_at:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="expiry_mismatch",
                reason="The mutation approval is not bound to the exact requested expiry timestamp.",
                expires_at=stored_expiry,
                mutation_approval=approval,
            )
        if approval.proposal_id != prepared.proposal_id:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="proposal_mismatch",
                reason="The mutation approval is not bound to the exact proposal id.",
                expires_at=stored_expiry,
                mutation_approval=approval,
            )
        if bound_mutation_run_id != prepared.mutation_run_id:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="mutation_run_mismatch",
                reason="The mutation approval is not bound to the exact mutation run id.",
                expires_at=stored_expiry,
                mutation_approval=approval,
            )
        if tuple(approval.mutation_target_ids) != prepared.mutation_target_ids:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="target_mismatch",
                reason="The mutation approval target list does not exactly match the requested targets.",
                expires_at=stored_expiry,
                mutation_approval=approval,
            )
        if _normalized_key(approval.mode) != prepared.mode:
            return self._deny(
                proposal_id=prepared.proposal_id,
                mutation_run_id=prepared.mutation_run_id,
                mutation_target_ids=prepared.mutation_target_ids,
                mode=prepared.mode,
                reason_code="mode_mismatch",
                reason="The mutation approval mode does not exactly match the requested execution mode.",
                expires_at=stored_expiry,
                mutation_approval=approval,
            )

        binding_mismatch = self._optional_binding_mismatch(approval=approval, request=prepared)
        if binding_mismatch is not None:
            return binding_mismatch

        return self._approve(
            proposal_id=prepared.proposal_id,
            mutation_run_id=prepared.mutation_run_id,
            mutation_target_ids=prepared.mutation_target_ids,
            mode=prepared.mode,
            expires_at=stored_expiry,
            mutation_approval=approval,
            metadata={
                "validation_layer": "mutation_approval_service",
                "operation": "validate_approval",
            },
        )

    def _prepare_request(
        self,
        request: MutationApprovalRequest,
        *,
        now: datetime,
    ) -> tuple[_PreparedMutationApprovalRequest | None, MutationApprovalDecision | None]:
        """Normalize one request or return one typed invalid decision."""

        proposal_id = _normalize_text(request.proposal_id, max_chars=120)
        if not proposal_id:
            return None, self._deny(
                proposal_id="",
                mutation_run_id="",
                mutation_target_ids=(),
                mode="",
                reason_code="missing_proposal_id",
                reason="Mutation approval requests require one exact proposal id.",
            )

        mutation_run_id = _normalize_text(request.mutation_run_id, max_chars=120)
        if not mutation_run_id:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id="",
                mutation_target_ids=(),
                mode="",
                reason_code="missing_mutation_run_id",
                reason="Mutation approval requests require one exact mutation run id.",
            )

        approval_decision_id = _normalize_text(request.approval_decision_id, max_chars=120)
        if not approval_decision_id:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=(),
                mode="",
                reason_code="missing_approval_decision_id",
                reason="Mutation approval requests require one originating approval decision id.",
            )

        mutation_target_ids = _normalize_sequence(request.mutation_target_ids, max_chars=120, allow_empty=False)
        if mutation_target_ids is None:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=(),
                mode="",
                reason_code="invalid_target_list",
                reason="Mutation approval requests require one exact non-empty target id list.",
            )

        normalized_mode = _normalized_key(request.mode)
        if normalized_mode not in _ALLOWED_EXECUTION_MODES:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=mutation_target_ids,
                mode=normalized_mode,
                reason_code="invalid_mode",
                reason="Mutation approval validation only allows apply or rollback modes.",
            )

        actor = _normalize_text(request.actor, max_chars=120)
        if not actor:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=mutation_target_ids,
                mode=normalized_mode,
                reason_code="missing_actor",
                reason="Mutation approval requests require one human actor identity.",
            )

        expires_at = _normalize_timestamp(request.expires_at)
        if expires_at is None:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=mutation_target_ids,
                mode=normalized_mode,
                reason_code="missing_expiry",
                reason="Mutation approval requests require one exact expiry timestamp.",
            )
        if expires_at <= now:
            return None, self._decision(
                decision="expired",
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=mutation_target_ids,
                mode=normalized_mode,
                reason_code="approval_expired",
                reason="Expired mutation approvals cannot be recorded or validated.",
                expires_at=expires_at,
            )

        execution_step_request_ids = _normalize_sequence(
            request.execution_step_request_ids,
            max_chars=120,
            allow_empty=True,
        )
        if execution_step_request_ids is None:
            return None, self._deny(
                proposal_id=proposal_id,
                mutation_run_id=mutation_run_id,
                mutation_target_ids=mutation_target_ids,
                mode=normalized_mode,
                reason_code="invalid_step_request_list",
                reason="Execution step request ids must be an ordered string sequence when provided.",
                expires_at=expires_at,
            )

        prepared = _PreparedMutationApprovalRequest(
            proposal_id=proposal_id,
            mutation_run_id=mutation_run_id,
            approval_decision_id=approval_decision_id,
            mutation_target_ids=mutation_target_ids,
            expires_at=expires_at,
            actor=actor,
            recovery_outcome_id=_normalize_text(request.recovery_outcome_id, max_chars=120),
            recovery_outcome_fingerprint=_normalize_text(request.recovery_outcome_fingerprint, max_chars=120),
            recovery_run_id=_normalize_text(request.recovery_run_id, max_chars=120),
            recovery_run_fingerprint=_normalize_text(request.recovery_run_fingerprint, max_chars=120),
            execution_request_id=_normalize_text(request.execution_request_id, max_chars=120),
            request_fingerprint=_normalize_text(request.request_fingerprint, max_chars=120),
            plan_id=_normalize_text(request.plan_id, max_chars=120),
            plan_fingerprint=_normalize_text(request.plan_fingerprint, max_chars=120),
            proposal_fingerprint=_normalize_text(request.proposal_fingerprint, max_chars=120),
            proposal_version=max(int(request.proposal_version or 0), 0),
            execution_step_request_ids=execution_step_request_ids,
            mode=normalized_mode,
            note=_normalize_text(request.note or "", max_chars=320) or None,
            metadata=sanitize_durable_mapping(request.metadata),
        )
        return prepared, None

    def _build_mutation_approval(self, request: _PreparedMutationApprovalRequest) -> MutationApproval:
        """Build one durable mutation approval record from normalized bindings."""

        approval_metadata = sanitize_durable_mapping(
            {
                **request.metadata,
                _MUTATION_RUN_METADATA_KEY: request.mutation_run_id,
            }
        )
        fingerprint = stable_id(
            "mutation_approval_fingerprint",
            {
                "recovery_outcome_id": request.recovery_outcome_id,
                "recovery_outcome_fingerprint": request.recovery_outcome_fingerprint,
                "recovery_run_id": request.recovery_run_id,
                "recovery_run_fingerprint": request.recovery_run_fingerprint,
                "execution_request_id": request.execution_request_id,
                "request_fingerprint": request.request_fingerprint,
                "plan_id": request.plan_id,
                "plan_fingerprint": request.plan_fingerprint,
                "proposal_id": request.proposal_id,
                "proposal_fingerprint": request.proposal_fingerprint,
                "proposal_version": request.proposal_version,
                "approval_decision_id": request.approval_decision_id,
                "mutation_run_id": request.mutation_run_id,
                "execution_step_request_ids": list(request.execution_step_request_ids),
                "mutation_target_ids": list(request.mutation_target_ids),
                "mode": request.mode,
                "actor": request.actor,
                "expires_at": request.expires_at.isoformat(),
                "note": request.note or "",
            },
        )
        return MutationApproval(
            mutation_approval_id=stable_id("mutation_approval", fingerprint),
            mutation_approval_fingerprint=fingerprint,
            recovery_outcome_id=request.recovery_outcome_id,
            recovery_outcome_fingerprint=request.recovery_outcome_fingerprint,
            recovery_run_id=request.recovery_run_id,
            recovery_run_fingerprint=request.recovery_run_fingerprint,
            execution_request_id=request.execution_request_id,
            request_fingerprint=request.request_fingerprint,
            plan_id=request.plan_id,
            plan_fingerprint=request.plan_fingerprint,
            proposal_id=request.proposal_id,
            proposal_fingerprint=request.proposal_fingerprint,
            proposal_version=request.proposal_version,
            approval_decision_id=request.approval_decision_id,
            execution_step_request_ids=request.execution_step_request_ids,
            mutation_target_ids=request.mutation_target_ids,
            mode=request.mode,
            decision="approved",
            actor=request.actor,
            note=request.note,
            expires_at=request.expires_at,
            metadata=approval_metadata,
        )

    def _optional_binding_mismatch(
        self,
        *,
        approval: MutationApproval,
        request: _PreparedMutationApprovalRequest,
    ) -> MutationApprovalDecision | None:
        """Return one mismatch decision when optional stored bindings drift."""

        exact_text_bindings = (
            ("approval_decision_id", request.approval_decision_id, approval.approval_decision_id),
            ("recovery_outcome_id", request.recovery_outcome_id, approval.recovery_outcome_id),
            ("recovery_outcome_fingerprint", request.recovery_outcome_fingerprint, approval.recovery_outcome_fingerprint),
            ("recovery_run_id", request.recovery_run_id, approval.recovery_run_id),
            ("recovery_run_fingerprint", request.recovery_run_fingerprint, approval.recovery_run_fingerprint),
            ("execution_request_id", request.execution_request_id, approval.execution_request_id),
            ("request_fingerprint", request.request_fingerprint, approval.request_fingerprint),
            ("plan_id", request.plan_id, approval.plan_id),
            ("plan_fingerprint", request.plan_fingerprint, approval.plan_fingerprint),
            ("proposal_fingerprint", request.proposal_fingerprint, approval.proposal_fingerprint),
        )
        for field_name, expected, actual in exact_text_bindings:
            if expected and expected != actual:
                return self._deny(
                    proposal_id=request.proposal_id,
                    mutation_run_id=request.mutation_run_id,
                    mutation_target_ids=request.mutation_target_ids,
                    mode=request.mode,
                    reason_code="binding_mismatch",
                    reason=f"The mutation approval is not bound to the exact {field_name}.",
                    expires_at=_normalize_timestamp(approval.expires_at),
                    mutation_approval=approval,
                    metadata={"mismatch_field": field_name},
                )

        if request.proposal_version and request.proposal_version != approval.proposal_version:
            return self._deny(
                proposal_id=request.proposal_id,
                mutation_run_id=request.mutation_run_id,
                mutation_target_ids=request.mutation_target_ids,
                mode=request.mode,
                reason_code="binding_mismatch",
                reason="The mutation approval is not bound to the exact proposal_version.",
                expires_at=_normalize_timestamp(approval.expires_at),
                mutation_approval=approval,
                metadata={"mismatch_field": "proposal_version"},
            )

        if request.execution_step_request_ids and request.execution_step_request_ids != tuple(approval.execution_step_request_ids):
            return self._deny(
                proposal_id=request.proposal_id,
                mutation_run_id=request.mutation_run_id,
                mutation_target_ids=request.mutation_target_ids,
                mode=request.mode,
                reason_code="binding_mismatch",
                reason="The mutation approval is not bound to the exact execution_step_request_ids.",
                expires_at=_normalize_timestamp(approval.expires_at),
                mutation_approval=approval,
                metadata={"mismatch_field": "execution_step_request_ids"},
            )

        return None

    def _bound_mutation_run_id(self, approval: MutationApproval) -> str:
        """Return the stored mutation run id binding from approval metadata."""

        return _normalize_text(approval.metadata.get(_MUTATION_RUN_METADATA_KEY, ""), max_chars=120)

    def _approve(
        self,
        *,
        proposal_id: str,
        mutation_run_id: str,
        mutation_target_ids: tuple[str, ...],
        mode: str,
        expires_at: datetime | None,
        mutation_approval: MutationApproval | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MutationApprovalDecision:
        """Build one approved mutation approval decision."""

        return self._decision(
            decision="approved",
            proposal_id=proposal_id,
            mutation_run_id=mutation_run_id,
            mutation_target_ids=mutation_target_ids,
            mode=mode,
            reason_code="approval_valid",
            reason="The mutation approval exactly matches the requested human-approved binding.",
            expires_at=expires_at,
            mutation_approval=mutation_approval,
            metadata=metadata,
        )

    def _deny(
        self,
        *,
        proposal_id: str,
        mutation_run_id: str,
        mutation_target_ids: tuple[str, ...],
        mode: str,
        reason_code: str,
        reason: str,
        expires_at: datetime | None = None,
        mutation_approval: MutationApproval | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MutationApprovalDecision:
        """Build one denied mutation approval decision."""

        return self._decision(
            decision="denied",
            proposal_id=proposal_id,
            mutation_run_id=mutation_run_id,
            mutation_target_ids=mutation_target_ids,
            mode=mode,
            reason_code=reason_code,
            reason=reason,
            expires_at=expires_at,
            mutation_approval=mutation_approval,
            metadata=metadata,
        )

    def _decision(
        self,
        *,
        decision: str,
        proposal_id: str,
        mutation_run_id: str,
        mutation_target_ids: tuple[str, ...],
        mode: str,
        reason_code: str,
        reason: str,
        expires_at: datetime | None = None,
        mutation_approval: MutationApproval | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MutationApprovalDecision:
        """Build one typed mutation approval decision."""

        return MutationApprovalDecision(
            decision=_normalize_text(decision, max_chars=80),
            proposal_id=_normalize_text(proposal_id, max_chars=120),
            mutation_run_id=_normalize_text(mutation_run_id, max_chars=120),
            mutation_target_ids=tuple(mutation_target_ids),
            mode=_normalize_text(mode, max_chars=80),
            reason_code=_normalize_text(reason_code, max_chars=120),
            reason=_normalize_text(reason, max_chars=320),
            expires_at=_normalize_timestamp(expires_at),
            mutation_approval=mutation_approval,
            metadata=sanitize_durable_mapping(metadata or {}),
        )


__all__ = [
    "MutationApprovalDecision",
    "MutationApprovalRequest",
    "MutationApprovalService",
]
