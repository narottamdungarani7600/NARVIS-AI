"""Focused tests for the Phase 11 trusted execution gateway."""

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
    ExecutionValidationResult,
    ExecutionValidatorService,
)
from Evolution.models import MutationApproval, MutationTarget, RecoveryOutcome
from Evolution.trusted_execution_gateway import (
    TrustedExecutionDecision,
    TrustedExecutionDecisionType,
    TrustedExecutionGateway,
)


class TrustedExecutionGatewayTests(unittest.TestCase):
    """Verify the gateway remains exact, fail closed, typed, and non-executing."""

    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[1]
        self.context_service = ExecutionContextService()
        self.validator = ExecutionValidatorService(
            context_service=self.context_service,
            workspace_root=self.workspace_root,
        )
        self.gateway = TrustedExecutionGateway(validator=self.validator)
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
            purpose="trusted-execution-validation",
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
            "action": "filesystem.write_file",
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

    def test_returns_typed_allow_only_after_all_prerequisites_pass(self) -> None:
        decision = self.gateway.authorize(self._request())

        self.assertIsInstance(decision, TrustedExecutionDecision)
        self.assertIsInstance(decision.validation_result, ExecutionValidationResult)
        self.assertTrue(decision.allowed)
        self.assertIs(decision.decision, TrustedExecutionDecisionType.ALLOW)
        self.assertIs(decision.reason, ExecutionValidationReason.ALLOWED)
        self.assertEqual(decision.action_id, "filesystem.write_file")
        self.assertEqual(decision.mutation_target_ids, ("target-001",))

    def test_rejects_missing_approval(self) -> None:
        decision = self.gateway.authorize(self._request(mutation_approval=None))

        self.assertFalse(decision.allowed)
        self.assertIs(decision.decision, TrustedExecutionDecisionType.DENY)
        self.assertIs(decision.reason, ExecutionValidationReason.HUMAN_APPROVAL_REQUIRED)

    def test_rejects_invalid_execution_context(self) -> None:
        snapshot = replace(self._context_snapshot(), snapshot_id="execution-context-tampered")

        decision = self.gateway.authorize(self._request(context_snapshot=snapshot))

        self.assertIs(decision.reason, ExecutionValidationReason.CONTEXT_INVALID)

    def test_rejects_failed_recovery_readiness(self) -> None:
        not_ready = replace(self.recovery_outcome, status="blocked")

        decision = self.gateway.authorize(self._request(recovery_outcome=not_ready))

        self.assertIs(decision.reason, ExecutionValidationReason.RECOVERY_NOT_READY)

    def test_rejects_unsupported_action_category(self) -> None:
        desktop_only_validator = ExecutionValidatorService(
            context_service=self.context_service,
            workspace_root=self.workspace_root,
            supported_action_categories=(ActionCategory.DESKTOP,),
        )
        gateway = TrustedExecutionGateway(validator=desktop_only_validator)

        decision = gateway.authorize(self._request())

        self.assertIs(decision.reason, ExecutionValidationReason.UNSUPPORTED_ACTION_CATEGORY)
        self.assertEqual(gateway.list_supported_action_categories(), (ActionCategory.DESKTOP,))

    def test_rejects_expired_approval(self) -> None:
        expired = replace(self.approval, expires_at=self.evaluated_at)

        decision = self.gateway.authorize(self._request(mutation_approval=expired))

        self.assertIs(decision.reason, ExecutionValidationReason.MUTATION_APPROVAL_EXPIRED)

    def test_rejects_protected_target(self) -> None:
        protected = replace(self.target, locator="Docs/AI_DEVELOPMENT_RULES.md")

        decision = self.gateway.authorize(self._request(mutation_targets=(protected,)))

        self.assertIs(decision.reason, ExecutionValidationReason.PROTECTED_TARGET_RESTRICTED)

    def test_invalid_input_returns_typed_deny(self) -> None:
        decision = self.gateway.authorize(object())

        self.assertIsInstance(decision, TrustedExecutionDecision)
        self.assertFalse(decision.allowed)
        self.assertIs(decision.reason, ExecutionValidationReason.INVALID_REQUEST)

    def test_service_has_no_runtime_or_execution_integration(self) -> None:
        decision = self.gateway.authorize(self._request())

        self.assertTrue(decision.allowed)
        self.assertFalse(hasattr(self.gateway, "runtime"))
        self.assertFalse(hasattr(self.gateway, "executor"))
        self.assertFalse(hasattr(self.gateway, "desktop"))
        self.assertFalse(hasattr(self.gateway, "browser"))
        self.assertFalse(hasattr(self.gateway, "filesystem"))


if __name__ == "__main__":
    unittest.main()
