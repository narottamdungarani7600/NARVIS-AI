"""Focused tests for the standalone Phase 10 future-execution validator."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from Evolution.action_registry import ActionCategory
from Evolution.execution_context import (
    ApplicationContext,
    DesktopContext,
    DisplayContext,
    ExecutionContextBuildRequest,
    ExecutionContextService,
    KeyboardContext,
    MouseContext,
    WindowContext,
    WorkspaceContext,
)
from Evolution.execution_validator import (
    ExecutionValidationReason,
    ExecutionValidationRequest,
    ExecutionValidatorService,
)
from Evolution.models import MutationApproval, MutationTarget, RecoveryOutcome


class ExecutionValidatorServiceTests(unittest.TestCase):
    """Verify future execution remains typed, exact, fail-closed, and non-executing."""

    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[1]
        self.context_service = ExecutionContextService()
        self.validator = ExecutionValidatorService(
            context_service=self.context_service,
            workspace_root=self.workspace_root,
        )
        self.evaluated_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
        self.target = MutationTarget(
            mutation_target_id="target-001",
            plan_step_id="plan-step-001",
            execution_step_request_id="step-request-001",
            executor_category="code_development",
            action_kind="source_modify",
            target_kind="source_file",
            locator="Skills/builtin.py",
            risk_classification="medium",
        )
        self.recovery_outcome = RecoveryOutcome(
            recovery_outcome_id="recovery-outcome-001",
            recovery_run_id="recovery-run-001",
            run_fingerprint="recovery-run-fingerprint-001",
            step_results=(),
            status="ready",
            reason_code="all_steps_ready",
            outcome_fingerprint="recovery-outcome-fingerprint-001",
        )
        self.approval = MutationApproval(
            mutation_approval_id="mutation-approval-001",
            mutation_approval_fingerprint="mutation-approval-fingerprint-001",
            recovery_outcome_id=self.recovery_outcome.recovery_outcome_id,
            recovery_outcome_fingerprint=self.recovery_outcome.outcome_fingerprint,
            recovery_run_id=self.recovery_outcome.recovery_run_id,
            recovery_run_fingerprint=self.recovery_outcome.run_fingerprint,
            execution_request_id="execution-request-001",
            request_fingerprint="execution-request-fingerprint-001",
            plan_id="plan-001",
            plan_fingerprint="plan-fingerprint-001",
            proposal_id="proposal-001",
            proposal_fingerprint="proposal-fingerprint-001",
            proposal_version=1,
            approval_decision_id="approval-decision-001",
            execution_step_request_ids=("step-request-001",),
            mutation_target_ids=(self.target.mutation_target_id,),
            mode="apply",
            decision="approved",
            actor="Narottam",
            expires_at=self.evaluated_at + timedelta(hours=1),
        )

    def _context_snapshot(self):
        session = self.context_service.create_session(
            actor_id="human-reviewer",
            workspace_id="workspace-001",
            desktop_id="desktop-001",
            purpose="future-action-validation",
        )
        result = self.context_service.build_snapshot(
            ExecutionContextBuildRequest(
                session=session,
                desktop=DesktopContext("desktop-001", "Windows", True),
                window=WindowContext("window-001", "application-001", "NARVIS", True, 0, 0, 800, 600),
                application=ApplicationContext("application-001", "NARVIS", "1.0", True),
                display=DisplayContext("display-001", "desktop-001", 1920, 1080),
                mouse=MouseContext("display-001", 100, 100),
                keyboard=KeyboardContext("en-US"),
                workspace=WorkspaceContext("workspace-001", "NARVIS", "workspace://narvis", True),
            )
        )
        assert result.snapshot is not None
        return result.snapshot

    def _request(self, **overrides: object) -> ExecutionValidationRequest:
        values = {
            "action": self.validator.action_registry.get_action("filesystem.write_file"),
            "context_snapshot": self._context_snapshot(),
            "mutation_approval": self.approval,
            "mutation_approval_reference": self.approval.mutation_approval_id,
            "recovery_outcome": self.recovery_outcome,
            "mutation_targets": (self.target,),
            "execution_mode": "apply",
            "evaluated_at": self.evaluated_at,
        }
        values.update(overrides)
        return ExecutionValidationRequest(**values)

    def test_allows_only_the_complete_registered_approved_ready_request(self) -> None:
        result = self.validator.validate(self._request())

        self.assertTrue(result.allowed)
        self.assertEqual(result.decision, "ALLOW")
        self.assertEqual(result.reason, ExecutionValidationReason.ALLOWED)
        self.assertEqual(result.reason_code, "allowed")
        self.assertEqual(result.action_id, "filesystem.write_file")
        self.assertEqual(result.mutation_target_ids, ("target-001",))

    def test_rejects_unknown_actions_and_unsupported_registered_categories(self) -> None:
        unknown = self.validator.validate(self._request(action="desktop.delete_everything"))
        desktop_only = ExecutionValidatorService(
            context_service=self.context_service,
            workspace_root=self.workspace_root,
            supported_action_categories=(ActionCategory.DESKTOP,),
        )
        unsupported = desktop_only.validate(self._request())

        self.assertFalse(unknown.allowed)
        self.assertEqual(unknown.reason, ExecutionValidationReason.ACTION_UNREGISTERED)
        self.assertFalse(unsupported.allowed)
        self.assertEqual(unsupported.reason, ExecutionValidationReason.UNSUPPORTED_ACTION_CATEGORY)

    def test_rejects_invalid_or_unrecognized_context_snapshots(self) -> None:
        snapshot = self._context_snapshot()
        tampered = replace(snapshot, snapshot_id="execution_context_snapshot-tampered")
        fresh_context_service = ExecutionContextService()
        unrecognized_validator = ExecutionValidatorService(
            context_service=fresh_context_service,
            workspace_root=self.workspace_root,
        )

        invalid = self.validator.validate(self._request(context_snapshot=tampered))
        unrecognized = unrecognized_validator.validate(self._request(context_snapshot=snapshot))

        self.assertEqual(invalid.reason, ExecutionValidationReason.CONTEXT_INVALID)
        self.assertEqual(unrecognized.reason, ExecutionValidationReason.CONTEXT_SNAPSHOT_UNRECOGNIZED)

    def test_rejects_missing_mismatched_or_expired_human_approval(self) -> None:
        missing = self.validator.validate(self._request(mutation_approval=None))
        mismatched = self.validator.validate(self._request(mutation_approval_reference="mutation-approval-other"))
        expired = self.validator.validate(
            self._request(mutation_approval=replace(self.approval, expires_at=self.evaluated_at))
        )

        self.assertEqual(missing.reason, ExecutionValidationReason.HUMAN_APPROVAL_REQUIRED)
        self.assertEqual(mismatched.reason, ExecutionValidationReason.MUTATION_APPROVAL_REFERENCE_MISMATCH)
        self.assertEqual(expired.reason, ExecutionValidationReason.MUTATION_APPROVAL_EXPIRED)

    def test_rejects_mode_and_exact_target_approval_mismatches(self) -> None:
        mode_mismatch = self.validator.validate(self._request(execution_mode="rollback"))
        other_target = replace(self.target, mutation_target_id="target-002")
        target_mismatch = self.validator.validate(self._request(mutation_targets=(other_target,)))

        self.assertEqual(mode_mismatch.reason, ExecutionValidationReason.MUTATION_APPROVAL_MODE_MISMATCH)
        self.assertEqual(target_mismatch.reason, ExecutionValidationReason.MUTATION_TARGET_APPROVAL_MISMATCH)

    def test_rejects_missing_non_ready_or_unbound_recovery_outcomes(self) -> None:
        missing = self.validator.validate(self._request(recovery_outcome=None))
        not_ready = self.validator.validate(self._request(recovery_outcome=replace(self.recovery_outcome, status="blocked")))
        unbound = self.validator.validate(
            self._request(recovery_outcome=replace(self.recovery_outcome, outcome_fingerprint="different-fingerprint"))
        )

        self.assertEqual(missing.reason, ExecutionValidationReason.RECOVERY_OUTCOME_REQUIRED)
        self.assertEqual(not_ready.reason, ExecutionValidationReason.RECOVERY_NOT_READY)
        self.assertEqual(unbound.reason, ExecutionValidationReason.RECOVERY_APPROVAL_BINDING_MISMATCH)

    def test_rejects_protected_or_unsupported_mutation_targets(self) -> None:
        protected_target = replace(self.target, locator="Docs/AI_DEVELOPMENT_RULES.md")
        unknown_surface_target = replace(self.target, executor_category="git_operation", target_kind="local_repository")

        protected = self.validator.validate(self._request(mutation_targets=(protected_target,)))
        unsupported = self.validator.validate(self._request(mutation_targets=(unknown_surface_target,)))

        self.assertEqual(protected.reason, ExecutionValidationReason.PROTECTED_TARGET_RESTRICTED)
        self.assertEqual(unsupported.reason, ExecutionValidationReason.MUTATION_TARGET_DENIED)

    def test_service_exposes_no_runtime_or_executor_integration(self) -> None:
        result = self.validator.validate(self._request())

        self.assertTrue(result.allowed)
        self.assertFalse(hasattr(self.validator, "runtime"))
        self.assertFalse(hasattr(self.validator, "executor"))
        self.assertFalse(hasattr(self.validator, "planner"))
        self.assertFalse(hasattr(self.validator, "execution_allowed"))


if __name__ == "__main__":
    unittest.main()
