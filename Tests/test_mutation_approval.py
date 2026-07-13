"""Focused tests for the Phase 7 mutation approval service."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from Evolution.mutation_approval import (
    MutationApprovalRequest,
    MutationApprovalService,
)


class MutationApprovalServiceTests(unittest.TestCase):
    """Verify exact human approval recording and revalidation."""

    def setUp(self) -> None:
        self.service = MutationApprovalService()
        self.now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
        self.expires_at = self.now + timedelta(hours=2)

    def _request(self, **overrides: object) -> MutationApprovalRequest:
        values = {
            "proposal_id": "proposal-001",
            "mutation_run_id": "mutation-run-001",
            "approval_decision_id": "approval-decision-001",
            "mutation_target_ids": ("target-001", "target-002"),
            "expires_at": self.expires_at,
            "actor": "Narottam",
            "recovery_outcome_id": "recovery-outcome-001",
            "recovery_outcome_fingerprint": "recovery-outcome-fp-001",
            "recovery_run_id": "recovery-run-001",
            "recovery_run_fingerprint": "recovery-run-fp-001",
            "execution_request_id": "execution-request-001",
            "request_fingerprint": "execution-request-fp-001",
            "plan_id": "plan-001",
            "plan_fingerprint": "plan-fp-001",
            "proposal_fingerprint": "proposal-fp-001",
            "proposal_version": 1,
            "execution_step_request_ids": ("step-request-001", "step-request-002"),
            "mode": "apply",
            "note": "Approved for narrow mutation.",
        }
        values.update(overrides)
        return MutationApprovalRequest(**values)

    def test_records_exact_human_mutation_approval(self) -> None:
        decision = self.service.record_approval(self._request(), now=self.now)

        self.assertTrue(decision.approved)
        self.assertEqual(decision.reason_code, "approval_valid")
        self.assertEqual(decision.mutation_run_id, "mutation-run-001")
        self.assertIsNotNone(decision.mutation_approval)
        self.assertEqual(decision.mutation_approval.proposal_id, "proposal-001")
        self.assertEqual(decision.mutation_approval.mode, "apply")
        self.assertEqual(decision.mutation_approval.decision, "approved")
        self.assertEqual(decision.mutation_approval.mutation_target_ids, ("target-001", "target-002"))
        self.assertEqual(decision.mutation_approval.metadata["mutation_run_id"], "mutation-run-001")

    def test_validate_approval_allows_exact_matching_binding(self) -> None:
        request = self._request()
        approval = self.service.record_approval(request, now=self.now).mutation_approval

        decision = self.service.validate_approval(approval, request, now=self.now)

        self.assertTrue(decision.approved)
        self.assertEqual(decision.reason_code, "approval_valid")
        self.assertEqual(decision.mutation_approval.mutation_approval_id, approval.mutation_approval_id)

    def test_record_rejects_expired_approval_request(self) -> None:
        decision = self.service.record_approval(
            self._request(expires_at=self.now - timedelta(minutes=1)),
            now=self.now,
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.decision, "expired")
        self.assertEqual(decision.reason_code, "approval_expired")
        self.assertIsNone(decision.mutation_approval)

    def test_validate_rejects_target_mismatch(self) -> None:
        approval = self.service.record_approval(self._request(), now=self.now).mutation_approval

        decision = self.service.validate_approval(
            approval,
            self._request(mutation_target_ids=("target-002", "target-001")),
            now=self.now,
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason_code, "target_mismatch")

    def test_validate_rejects_mode_mismatch(self) -> None:
        approval = self.service.record_approval(self._request(), now=self.now).mutation_approval

        decision = self.service.validate_approval(
            approval,
            self._request(mode="rollback"),
            now=self.now,
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason_code, "mode_mismatch")

    def test_validate_rejects_mutation_run_mismatch(self) -> None:
        approval = self.service.record_approval(self._request(), now=self.now).mutation_approval

        decision = self.service.validate_approval(
            approval,
            self._request(mutation_run_id="mutation-run-999"),
            now=self.now,
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason_code, "mutation_run_mismatch")

    def test_validate_rejects_expired_stored_approval(self) -> None:
        request = self._request()
        approval = self.service.record_approval(request, now=self.now).mutation_approval
        expired_approval = replace(approval, expires_at=self.now - timedelta(seconds=1))

        decision = self.service.validate_approval(expired_approval, request, now=self.now)

        self.assertFalse(decision.approved)
        self.assertEqual(decision.decision, "expired")
        self.assertEqual(decision.reason_code, "approval_expired")

    def test_validate_rejects_expiry_mismatch(self) -> None:
        approval = self.service.record_approval(self._request(), now=self.now).mutation_approval

        decision = self.service.validate_approval(
            approval,
            self._request(expires_at=self.expires_at + timedelta(minutes=5)),
            now=self.now,
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason_code, "expiry_mismatch")


if __name__ == "__main__":
    unittest.main()
