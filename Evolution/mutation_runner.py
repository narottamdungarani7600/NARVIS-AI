"""Simulated narrow mutation-run execution for future Phase 7 work."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import (
    MutationApproval,
    MutationObservation,
    MutationOutcome,
    MutationRun,
    MutationStepRun,
    MutationTarget,
    RollbackArtifact,
    compact_text,
    sanitize_durable_mapping,
    stable_id,
    utc_now,
)
from .mutation_approval import MutationApprovalDecision

_ALLOWED_MUTATION_MODES = frozenset({"apply", "rollback"})
_VALIDATED_APPROVAL_OPERATION = "validate_approval"
_MUTATION_RUN_METADATA_KEY = "mutation_run_id"


def _normalized_key(value: str) -> str:
    """Normalize one runner key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


def _normalize_text(value: Any, *, max_chars: int = 120) -> str:
    """Normalize one text field into a durable bounded string."""

    return compact_text(str(value or ""), max_chars=max_chars)


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
class MutationRunRequest:
    """One simulated mutation-run execution request."""

    approval_decision: MutationApprovalDecision
    mutation_targets: tuple[MutationTarget, ...]
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class MutationRunResult:
    """One typed mutation-run execution result."""

    decision: str
    reason_code: str
    reason: str
    mutation_run: MutationRun | None = None
    step_runs: tuple[MutationStepRun, ...] = ()
    observations: tuple[MutationObservation, ...] = ()
    outcome: MutationOutcome | None = None
    rollback_artifacts: tuple[RollbackArtifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True only when the simulated mutation run completed successfully."""

        return bool(self.outcome and self.outcome.status in {"applied", "rolled_back"})


@dataclass(slots=True, frozen=True)
class _PreparedMutationRunRequest:
    """Normalized runner inputs shared by execution helpers."""

    approval: MutationApproval
    mutation_run_id: str
    mode: str
    mutation_targets: tuple[MutationTarget, ...]
    actor: str
    metadata: dict[str, Any]


@dataclass(slots=True, frozen=True)
class _SimulatedStepExecution:
    """One internal placeholder execution result."""

    status: str
    reason_code: str
    reason: str
    observation_kind: str
    evidence: dict[str, Any]


class MutationRunService:
    """Execute one approved mutation run through simulated step execution only."""

    def list_supported_modes(self) -> tuple[str, ...]:
        """Return supported execution modes in deterministic order."""

        return tuple(sorted(_ALLOWED_MUTATION_MODES))

    def execute(
        self,
        request: MutationRunRequest,
        *,
        now: datetime | None = None,
    ) -> MutationRunResult:
        """Execute one validated mutation run without performing any real mutation."""

        current_time = _normalize_timestamp(now) or utc_now()
        prepared, rejected = self._prepare_request(request, now=current_time)
        if rejected is not None or prepared is None:
            return rejected or self._reject(
                reason_code="mutation_run_request_invalid",
                reason="The mutation run request could not be normalized safely.",
            )

        step_runs: list[MutationStepRun] = []
        observations: list[MutationObservation] = []
        rollback_artifacts: list[RollbackArtifact] = []
        step_results: list[dict[str, Any]] = []
        failure_reason_code = ""
        failure_reason = ""

        for sequence, target in enumerate(prepared.mutation_targets, start=1):
            simulated = self._simulate_step(mode=prepared.mode, target=target, sequence=sequence)
            step_run = self._build_step_run(
                mutation_run_id=prepared.mutation_run_id,
                target=target,
                sequence=sequence,
                mode=prepared.mode,
                actor=prepared.actor,
                status=simulated.status,
            )
            observation = self._build_observation(
                mutation_run_id=prepared.mutation_run_id,
                step_run=step_run,
                target=target,
                actor=prepared.actor,
                simulated=simulated,
            )

            step_runs.append(step_run)
            observations.append(observation)
            step_results.append(
                sanitize_durable_mapping(
                    {
                        "mutation_step_run_id": step_run.mutation_step_run_id,
                        "mutation_target_id": target.mutation_target_id,
                        "status": step_run.status,
                        "reason_code": simulated.reason_code,
                        "observation_id": observation.observation_id,
                    }
                )
            )

            if simulated.status == "failed":
                failure_reason_code = simulated.reason_code
                failure_reason = simulated.reason
                break

        if failure_reason_code:
            final_status = "failed"
            reason_code = failure_reason_code
            reason = failure_reason
        else:
            final_status = "applied" if prepared.mode == "apply" else "rolled_back"
            reason_code = "mutation_run_completed"
            reason = (
                "The simulated mutation run completed in apply mode without performing real file changes."
                if prepared.mode == "apply"
                else "The simulated mutation run completed in rollback mode without performing real file changes."
            )

        mutation_run = self._build_mutation_run(
            approval=prepared.approval,
            mutation_run_id=prepared.mutation_run_id,
            mode=prepared.mode,
            actor=prepared.actor,
            step_runs=tuple(step_runs),
            rollback_artifacts=tuple(rollback_artifacts),
            status=final_status,
            metadata=prepared.metadata,
        )
        outcome = self._build_outcome(
            mutation_run=mutation_run,
            actor=prepared.actor,
            step_results=tuple(step_results),
            status=final_status,
            reason_code=reason_code,
        )

        return MutationRunResult(
            decision="executed",
            reason_code=reason_code,
            reason=reason,
            mutation_run=mutation_run,
            step_runs=tuple(step_runs),
            observations=tuple(observations),
            outcome=outcome,
            rollback_artifacts=tuple(rollback_artifacts),
            metadata=sanitize_durable_mapping(
                {
                    **prepared.metadata,
                    "simulated": True,
                    "mode": prepared.mode,
                }
            ),
        )

    def _prepare_request(
        self,
        request: MutationRunRequest,
        *,
        now: datetime,
    ) -> tuple[_PreparedMutationRunRequest | None, MutationRunResult | None]:
        """Normalize one runner request or return one typed rejection."""

        approval_decision = request.approval_decision
        if not approval_decision.approved or approval_decision.mutation_approval is None:
            return None, self._reject(
                reason_code="approval_not_validated",
                reason="Mutation execution accepts only one validated and approved mutation approval.",
            )

        if _normalized_key(approval_decision.metadata.get("operation", "")) != _VALIDATED_APPROVAL_OPERATION:
            return None, self._reject(
                reason_code="approval_not_validated",
                reason="Mutation execution requires a validate_approval decision before it can run.",
                metadata={"required_operation": _VALIDATED_APPROVAL_OPERATION},
            )

        approval = approval_decision.mutation_approval
        if _normalized_key(approval.decision) != "approved":
            return None, self._reject(
                reason_code="approval_not_validated",
                reason="Only an explicitly approved mutation approval can be executed.",
            )

        mode = _normalized_key(approval.mode)
        if mode not in _ALLOWED_MUTATION_MODES:
            return None, self._reject(
                reason_code="invalid_mode",
                reason="The mutation runner only supports apply or rollback modes.",
                metadata={"mode": approval.mode},
            )

        expires_at = _normalize_timestamp(approval.expires_at)
        if expires_at is None:
            return None, self._reject(
                reason_code="approval_binding_missing",
                reason="The validated mutation approval is missing its expiry binding.",
            )
        if expires_at <= now:
            return None, self._reject(
                reason_code="approval_expired",
                reason="Expired mutation approvals cannot be executed.",
                metadata={"expires_at": expires_at.isoformat()},
            )

        mutation_run_id = _normalize_text(approval_decision.mutation_run_id, max_chars=120)
        approval_bound_run_id = _normalize_text(approval.metadata.get(_MUTATION_RUN_METADATA_KEY, ""), max_chars=120)
        if not mutation_run_id or not approval_bound_run_id or mutation_run_id != approval_bound_run_id:
            return None, self._reject(
                reason_code="approval_binding_missing",
                reason="The validated mutation approval is missing its exact mutation run binding.",
            )

        actor = _normalize_text(request.actor, max_chars=120) or "narvis"
        targets = self._normalize_targets(request.mutation_targets)
        if targets is None:
            return None, self._reject(
                reason_code="invalid_target_list",
                reason="Mutation execution requires one ordered typed target list.",
            )
        target_ids = tuple(_normalize_text(target.mutation_target_id, max_chars=120) for target in targets)
        if target_ids != tuple(approval.mutation_target_ids):
            return None, self._reject(
                reason_code="target_mismatch",
                reason="The provided mutation targets do not exactly match the validated approval target list.",
            )

        return (
            _PreparedMutationRunRequest(
                approval=approval,
                mutation_run_id=mutation_run_id,
                mode=mode,
                mutation_targets=targets,
                actor=actor,
                metadata=sanitize_durable_mapping(request.metadata),
            ),
            None,
        )

    def _normalize_targets(self, values: Any) -> tuple[MutationTarget, ...] | None:
        """Normalize one ordered mutation-target sequence."""

        if not isinstance(values, list | tuple):
            return None

        targets: list[MutationTarget] = []
        for value in values:
            if not isinstance(value, MutationTarget):
                return None
            targets.append(value)

        return tuple(targets) if targets else None

    def _simulate_step(
        self,
        *,
        mode: str,
        target: MutationTarget,
        sequence: int,
    ) -> _SimulatedStepExecution:
        """Return one placeholder mutation-step execution result."""

        evidence = {
            "simulated": True,
            "mode": mode,
            "sequence": sequence,
            "target_kind": target.target_kind,
            "locator": target.locator,
            "executor_category": target.executor_category,
            "action_kind": target.action_kind,
        }
        if bool(target.metadata.get("simulate_failure", False)):
            reason_code = _normalize_text(target.metadata.get("simulate_reason_code", "simulated_step_failed"), max_chars=120)
            reason = _normalize_text(
                target.metadata.get(
                    "simulate_reason",
                    "The placeholder mutation executor simulated a step failure and stopped the run.",
                ),
                max_chars=320,
            )
            return _SimulatedStepExecution(
                status="failed",
                reason_code=reason_code,
                reason=reason,
                observation_kind=f"simulated_{mode}_failure",
                evidence=sanitize_durable_mapping(
                    {
                        **evidence,
                        "step_status": "failed",
                        "reason_code": reason_code,
                    }
                ),
            )

        status = "applied" if mode == "apply" else "rolled_back"
        reason_code = "simulated_apply_completed" if mode == "apply" else "simulated_rollback_completed"
        return _SimulatedStepExecution(
            status=status,
            reason_code=reason_code,
            reason=(
                "The placeholder mutation executor simulated one apply step without making real file changes."
                if mode == "apply"
                else "The placeholder mutation executor simulated one rollback step without making real file changes."
            ),
            observation_kind=f"simulated_{mode}_result",
            evidence=sanitize_durable_mapping(
                {
                    **evidence,
                    "step_status": status,
                    "reason_code": reason_code,
                }
            ),
        )

    def _build_step_run(
        self,
        *,
        mutation_run_id: str,
        target: MutationTarget,
        sequence: int,
        mode: str,
        actor: str,
        status: str,
    ) -> MutationStepRun:
        """Build one mutation-step run record."""

        step_run_fingerprint = stable_id(
            "mutation_step_run_fingerprint",
            {
                "mutation_run_id": mutation_run_id,
                "mutation_target_id": target.mutation_target_id,
                "execution_step_request_id": target.execution_step_request_id,
                "plan_step_id": target.plan_step_id,
                "sequence": sequence,
                "mode": mode,
                "status": status,
                "locator": target.locator,
            },
        )
        return MutationStepRun(
            mutation_step_run_id=stable_id("mutation_step_run", step_run_fingerprint),
            mutation_run_id=mutation_run_id,
            mutation_target_id=target.mutation_target_id,
            execution_step_request_id=target.execution_step_request_id,
            plan_step_id=target.plan_step_id,
            sequence=sequence,
            executor_category=target.executor_category,
            action_kind=target.action_kind,
            target=target.locator,
            inputs=sanitize_durable_mapping(
                {
                    "mode": mode,
                    "target_kind": target.target_kind,
                    "simulated": True,
                    "actor": actor,
                }
            ),
            risk_classification=target.risk_classification,
            step_run_fingerprint=step_run_fingerprint,
            status=status,
            metadata=sanitize_durable_mapping(
                {
                    "simulated": True,
                    "expected_after_fingerprint": target.expected_after_fingerprint,
                    "target_fingerprint": target.target_fingerprint,
                }
            ),
        )

    def _build_observation(
        self,
        *,
        mutation_run_id: str,
        step_run: MutationStepRun,
        target: MutationTarget,
        actor: str,
        simulated: _SimulatedStepExecution,
    ) -> MutationObservation:
        """Build one mutation observation record."""

        observation_fingerprint = stable_id(
            "mutation_observation_fingerprint",
            {
                "mutation_run_id": mutation_run_id,
                "mutation_step_run_id": step_run.mutation_step_run_id,
                "observation_kind": simulated.observation_kind,
                "status": "recorded",
                "evidence": simulated.evidence,
            },
        )
        return MutationObservation(
            observation_id=stable_id("mutation_observation", observation_fingerprint),
            mutation_run_id=mutation_run_id,
            mutation_step_run_id=step_run.mutation_step_run_id,
            observation_kind=simulated.observation_kind,
            evidence=sanitize_durable_mapping(
                {
                    **simulated.evidence,
                    "mutation_target_id": target.mutation_target_id,
                }
            ),
            status="recorded",
            observation_fingerprint=observation_fingerprint,
            actor=actor,
            metadata=sanitize_durable_mapping({"simulated": True}),
        )

    def _build_mutation_run(
        self,
        *,
        approval: MutationApproval,
        mutation_run_id: str,
        mode: str,
        actor: str,
        step_runs: tuple[MutationStepRun, ...],
        rollback_artifacts: tuple[RollbackArtifact, ...],
        status: str,
        metadata: dict[str, Any],
    ) -> MutationRun:
        """Build one terminal mutation-run record."""

        run_fingerprint = stable_id(
            "mutation_run_fingerprint",
            {
                "mutation_run_id": mutation_run_id,
                "mutation_approval_id": approval.mutation_approval_id,
                "mutation_approval_fingerprint": approval.mutation_approval_fingerprint,
                "proposal_id": approval.proposal_id,
                "proposal_fingerprint": approval.proposal_fingerprint,
                "proposal_version": approval.proposal_version,
                "approval_decision_id": approval.approval_decision_id,
                "mutation_target_ids": list(approval.mutation_target_ids),
                "mutation_step_run_ids": [step_run.mutation_step_run_id for step_run in step_runs],
                "rollback_artifact_ids": [artifact.rollback_artifact_id for artifact in rollback_artifacts],
                "mode": mode,
                "status": status,
            },
        )
        return MutationRun(
            mutation_run_id=mutation_run_id,
            run_fingerprint=run_fingerprint,
            mutation_approval_id=approval.mutation_approval_id,
            mutation_approval_fingerprint=approval.mutation_approval_fingerprint,
            recovery_outcome_id=approval.recovery_outcome_id,
            recovery_outcome_fingerprint=approval.recovery_outcome_fingerprint,
            recovery_run_id=approval.recovery_run_id,
            recovery_run_fingerprint=approval.recovery_run_fingerprint,
            execution_request_id=approval.execution_request_id,
            request_fingerprint=approval.request_fingerprint,
            plan_id=approval.plan_id,
            plan_fingerprint=approval.plan_fingerprint,
            proposal_id=approval.proposal_id,
            proposal_fingerprint=approval.proposal_fingerprint,
            proposal_version=approval.proposal_version,
            approval_decision_id=approval.approval_decision_id,
            mutation_target_ids=tuple(approval.mutation_target_ids),
            mutation_step_run_ids=tuple(step_run.mutation_step_run_id for step_run in step_runs),
            rollback_artifact_ids=tuple(artifact.rollback_artifact_id for artifact in rollback_artifacts),
            mode=mode,
            status=status,
            actor=actor,
            metadata=sanitize_durable_mapping(
                {
                    **metadata,
                    "simulated": True,
                    "real_mutation_performed": False,
                }
            ),
        )

    def _build_outcome(
        self,
        *,
        mutation_run: MutationRun,
        actor: str,
        step_results: tuple[dict[str, Any], ...],
        status: str,
        reason_code: str,
    ) -> MutationOutcome:
        """Build one terminal mutation outcome."""

        outcome_fingerprint = stable_id(
            "mutation_outcome_fingerprint",
            {
                "mutation_run_id": mutation_run.mutation_run_id,
                "run_fingerprint": mutation_run.run_fingerprint,
                "step_results": list(step_results),
                "status": status,
                "reason_code": reason_code,
            },
        )
        return MutationOutcome(
            mutation_outcome_id=stable_id("mutation_outcome", outcome_fingerprint),
            mutation_run_id=mutation_run.mutation_run_id,
            run_fingerprint=mutation_run.run_fingerprint,
            step_results=step_results,
            status=status,
            reason_code=reason_code,
            outcome_fingerprint=outcome_fingerprint,
            actor=actor,
            metadata=sanitize_durable_mapping(
                {
                    "simulated": True,
                    "real_mutation_performed": False,
                }
            ),
        )

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> MutationRunResult:
        """Build one typed preflight rejection result."""

        return MutationRunResult(
            decision="rejected",
            reason_code=_normalize_text(reason_code, max_chars=120),
            reason=_normalize_text(reason, max_chars=320),
            metadata=sanitize_durable_mapping(metadata or {}),
        )


__all__ = [
    "MutationRunRequest",
    "MutationRunResult",
    "MutationRunService",
]
