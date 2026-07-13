"""Focused tests for the Phase 7 mutation run service."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from Evolution.models import MutationTarget
from Evolution.mutation_approval import MutationApprovalRequest, MutationApprovalService
from Evolution.mutation_runner import MutationRunRequest, MutationRunService


class MutationRunServiceTests(unittest.TestCase):
    """Verify simulated mutation-run execution with validated approvals only."""

    def setUp(self) -> None:
        self.approval_service = MutationApprovalService()
        self.run_service = MutationRunService()
        self.now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
        self.expires_at = self.now + timedelta(hours=2)

    def _approval_request(
        self,
        *,
        mode: str = "apply",
        target_ids: tuple[str, ...] = ("target-001", "target-002"),
        mutation_run_id: str = "mutation-run-001",
        expires_at: datetime | None = None,
    ) -> MutationApprovalRequest:
        return MutationApprovalRequest(
            proposal_id="proposal-001",
            mutation_run_id=mutation_run_id,
            approval_decision_id="approval-decision-001",
            mutation_target_ids=target_ids,
            expires_at=expires_at or self.expires_at,
            actor="Narottam",
            recovery_outcome_id="recovery-outcome-001",
            recovery_outcome_fingerprint="recovery-outcome-fp-001",
            recovery_run_id="recovery-run-001",
            recovery_run_fingerprint="recovery-run-fp-001",
            execution_request_id="execution-request-001",
            request_fingerprint="execution-request-fp-001",
            plan_id="plan-001",
            plan_fingerprint="plan-fp-001",
            proposal_fingerprint="proposal-fp-001",
            proposal_version=1,
            execution_step_request_ids=tuple(f"step-request-{index:03d}" for index in range(1, len(target_ids) + 1)),
            mode=mode,
            note="Approved for narrow mutation execution.",
        )

    def _validated_approval(
        self,
        *,
        mode: str = "apply",
        target_ids: tuple[str, ...] = ("target-001", "target-002"),
        mutation_run_id: str = "mutation-run-001",
        expires_at: datetime | None = None,
    ):
        request = self._approval_request(
            mode=mode,
            target_ids=target_ids,
            mutation_run_id=mutation_run_id,
            expires_at=expires_at,
        )
        recorded = self.approval_service.record_approval(request, now=self.now)
        return self.approval_service.validate_approval(recorded.mutation_approval, request, now=self.now)

    def _targets(
        self,
        *,
        target_ids: tuple[str, ...] = ("target-001", "target-002"),
    ) -> tuple[MutationTarget, ...]:
        targets: list[MutationTarget] = []
        for index, target_id in enumerate(target_ids, start=1):
            targets.append(
                MutationTarget(
                    mutation_target_id=target_id,
                    plan_step_id=f"plan-step-{index:03d}",
                    execution_step_request_id=f"step-request-{index:03d}",
                    executor_category="approved_source_file",
                    action_kind="patch_file",
                    target_kind="source_file",
                    locator=f"Sandbox/example_{index}.py",
                    risk_classification="medium",
                )
            )
        return tuple(targets)

    def test_apply_run_executes_all_steps_sequentially(self) -> None:
        validated = self._validated_approval(mode="apply")
        targets = self._targets()

        result = self.run_service.execute(
            MutationRunRequest(
                approval_decision=validated,
                mutation_targets=targets,
            ),
            now=self.now,
        )

        self.assertEqual(result.decision, "executed")
        self.assertTrue(result.successful)
        self.assertEqual(result.reason_code, "mutation_run_completed")
        self.assertEqual(result.mutation_run.mode, "apply")
        self.assertEqual(result.mutation_run.status, "applied")
        self.assertEqual(len(result.step_runs), 2)
        self.assertEqual(len(result.observations), 2)
        self.assertEqual(result.outcome.status, "applied")
        self.assertEqual([step.sequence for step in result.step_runs], [1, 2])
        self.assertEqual([step.status for step in result.step_runs], ["applied", "applied"])
        self.assertTrue(all(observation.evidence["simulated"] for observation in result.observations))
        self.assertEqual(result.rollback_artifacts, ())

    def test_rollback_run_executes_in_rollback_mode(self) -> None:
        validated = self._validated_approval(mode="rollback")
        targets = self._targets()

        result = self.run_service.execute(
            MutationRunRequest(
                approval_decision=validated,
                mutation_targets=targets,
            ),
            now=self.now,
        )

        self.assertEqual(result.decision, "executed")
        self.assertTrue(result.successful)
        self.assertEqual(result.mutation_run.mode, "rollback")
        self.assertEqual(result.mutation_run.status, "rolled_back")
        self.assertEqual(result.outcome.status, "rolled_back")
        self.assertEqual([step.status for step in result.step_runs], ["rolled_back", "rolled_back"])
        self.assertTrue(all(observation.observation_kind.startswith("simulated_rollback") for observation in result.observations))

    def test_rejects_record_only_approval_that_was_not_validated(self) -> None:
        request = self._approval_request()
        recorded = self.approval_service.record_approval(request, now=self.now)

        result = self.run_service.execute(
            MutationRunRequest(
                approval_decision=recorded,
                mutation_targets=self._targets(),
            ),
            now=self.now,
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "approval_not_validated")
        self.assertIsNone(result.mutation_run)
        self.assertIsNone(result.outcome)

    def test_rejects_target_mismatch_against_validated_approval(self) -> None:
        validated = self._validated_approval()
        reversed_targets = tuple(reversed(self._targets()))

        result = self.run_service.execute(
            MutationRunRequest(
                approval_decision=validated,
                mutation_targets=reversed_targets,
            ),
            now=self.now,
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "target_mismatch")
        self.assertEqual(result.step_runs, ())

    def test_stops_immediately_on_first_failed_step(self) -> None:
        validated = self._validated_approval(target_ids=("target-001", "target-002", "target-003"))
        targets = list(self._targets(target_ids=("target-001", "target-002", "target-003")))
        targets[1] = replace(
            targets[1],
            metadata={
                "simulate_failure": True,
                "simulate_reason_code": "simulated_target_failure",
                "simulate_reason": "The second target failed in placeholder execution.",
            },
        )

        result = self.run_service.execute(
            MutationRunRequest(
                approval_decision=validated,
                mutation_targets=tuple(targets),
            ),
            now=self.now,
        )

        self.assertEqual(result.decision, "executed")
        self.assertFalse(result.successful)
        self.assertEqual(result.reason_code, "simulated_target_failure")
        self.assertEqual(result.mutation_run.status, "failed")
        self.assertEqual(result.outcome.status, "failed")
        self.assertEqual(len(result.step_runs), 2)
        self.assertEqual(len(result.observations), 2)
        self.assertEqual([step.status for step in result.step_runs], ["applied", "failed"])

    def test_rejects_expired_validated_approval_at_execution_time(self) -> None:
        validated = self._validated_approval(expires_at=self.now + timedelta(minutes=5))

        result = self.run_service.execute(
            MutationRunRequest(
                approval_decision=validated,
                mutation_targets=self._targets(),
            ),
            now=self.now + timedelta(hours=1),
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(result.reason_code, "approval_expired")
        self.assertIsNone(result.mutation_run)


if __name__ == "__main__":
    unittest.main()
