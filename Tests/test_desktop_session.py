"""Focused tests for the Phase 11 desktop session lifecycle."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Evolution.desktop_session import (
    DesktopSession,
    DesktopSessionBeginRequest,
    DesktopSessionDecision,
    DesktopSessionDecisionType,
    DesktopSessionEndRequest,
    DesktopSessionOwnershipRequest,
    DesktopSessionReason,
    DesktopSessionService,
    DesktopSessionStatus,
)
from Evolution.execution_validator import (
    ExecutionValidationReason,
    ExecutionValidationResult,
)
from Evolution.trusted_execution_gateway import (
    TrustedExecutionDecision,
    TrustedExecutionDecisionType,
)


class DesktopSessionServiceTests(unittest.TestCase):
    """Verify desktop sessions are gateway-bound, immutable, and non-executing."""

    def setUp(self) -> None:
        self.service = DesktopSessionService()
        self.started_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
        self.snapshot_id = "execution-context-001"
        self.authorization = self._authorization()

    def _authorization(
        self,
        *,
        action_id: str = "desktop.open_application",
        allowed: bool = True,
    ) -> TrustedExecutionDecision:
        validation = ExecutionValidationResult(
            decision="ALLOW" if allowed else "DENY",
            reason=(
                ExecutionValidationReason.ALLOWED
                if allowed
                else ExecutionValidationReason.HUMAN_APPROVAL_REQUIRED
            ),
            detail="Typed gateway validation fixture.",
            action_id=action_id,
            context_snapshot_id=self.snapshot_id,
            mutation_approval_id="mutation-approval-001",
            recovery_outcome_id="recovery-outcome-001",
            mutation_target_ids=("target-001",),
        )
        return TrustedExecutionDecision(
            decision=(
                TrustedExecutionDecisionType.ALLOW
                if allowed
                else TrustedExecutionDecisionType.DENY
            ),
            reason=validation.reason,
            detail=validation.detail,
            validation_result=validation,
            action_id=validation.action_id,
            context_snapshot_id=validation.context_snapshot_id,
            mutation_approval_id=validation.mutation_approval_id,
            recovery_outcome_id=validation.recovery_outcome_id,
            mutation_target_ids=validation.mutation_target_ids,
        )

    def _begin_request(self, **overrides: object) -> DesktopSessionBeginRequest:
        values = {
            "authorization": self.authorization,
            "owner_id": "human-reviewer",
            "snapshot_id": self.snapshot_id,
            "started_at": self.started_at,
            "timeout_seconds": 300,
        }
        values.update(overrides)
        return DesktopSessionBeginRequest(**values)

    def _begin(self) -> DesktopSession:
        decision = self.service.begin_session(self._begin_request())
        assert decision.session is not None
        return decision.session

    def test_begin_session_creates_immutable_gateway_bound_record(self) -> None:
        decision = self.service.begin_session(self._begin_request())

        self.assertIsInstance(decision, DesktopSessionDecision)
        self.assertTrue(decision.allowed)
        self.assertIs(decision.decision, DesktopSessionDecisionType.ALLOW)
        self.assertIs(decision.reason, DesktopSessionReason.SESSION_STARTED)
        assert decision.session is not None
        self.assertTrue(decision.session.active)
        self.assertEqual(decision.session.snapshot_id, self.snapshot_id)
        self.assertEqual(decision.session.action_id, "desktop.open_application")
        self.assertTrue(decision.session.session_id.startswith("desktop_session-"))
        self.assertTrue(decision.session.authorization_binding_id.startswith("trusted_execution_binding-"))
        with self.assertRaises(FrozenInstanceError):
            decision.session.owner_id = "other-owner"  # type: ignore[misc]

    def test_session_identifier_is_deterministic_and_begin_is_idempotent(self) -> None:
        first = self.service.begin_session(self._begin_request())
        second = self.service.begin_session(self._begin_request())

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertIs(second.reason, DesktopSessionReason.SESSION_ALREADY_ACTIVE)
        self.assertEqual(first.session, second.session)
        self.assertEqual(len(self.service.list_sessions()), 1)

    def test_rejects_missing_denied_or_unsupported_gateway_authorization(self) -> None:
        missing = self.service.begin_session(
            self._begin_request(authorization=None)
        )
        denied = self.service.begin_session(
            self._begin_request(authorization=self._authorization(allowed=False))
        )
        unsupported = self.service.begin_session(
            self._begin_request(authorization=self._authorization(action_id="browser.open_url"))
        )

        self.assertIs(missing.reason, DesktopSessionReason.TRUSTED_AUTHORIZATION_REQUIRED)
        self.assertIs(denied.reason, DesktopSessionReason.TRUSTED_AUTHORIZATION_DENIED)
        self.assertIs(unsupported.reason, DesktopSessionReason.UNSUPPORTED_ACTION_CATEGORY)
        self.assertEqual(self.service.list_sessions(), ())

    def test_rejects_snapshot_binding_mismatch_and_invalid_timeout(self) -> None:
        mismatched = self.service.begin_session(
            self._begin_request(snapshot_id="execution-context-other")
        )
        invalid_timeout = self.service.begin_session(
            self._begin_request(timeout_seconds=0)
        )

        self.assertIs(mismatched.reason, DesktopSessionReason.SNAPSHOT_BINDING_MISMATCH)
        self.assertIs(invalid_timeout.reason, DesktopSessionReason.INVALID_TIMEOUT)
        self.assertEqual(self.service.list_sessions(), ())

    def test_rejects_tampered_gateway_binding(self) -> None:
        tampered = replace(
            self.authorization,
            mutation_approval_id="mutation-approval-other",
        )

        decision = self.service.begin_session(
            self._begin_request(authorization=tampered)
        )

        self.assertFalse(decision.allowed)
        self.assertIs(decision.reason, DesktopSessionReason.TRUSTED_AUTHORIZATION_INVALID)
        self.assertEqual(self.service.list_sessions(), ())

    def test_lookup_and_list_return_retained_records_in_deterministic_order(self) -> None:
        first = self._begin()
        second_decision = self.service.begin_session(
            self._begin_request(owner_id="second-owner", started_at=self.started_at + timedelta(seconds=1))
        )
        assert second_decision.session is not None
        second = second_decision.session

        sessions = self.service.list_sessions()

        self.assertEqual(self.service.lookup_session(first.session_id), first)
        self.assertEqual(self.service.lookup_session("unknown-session"), None)
        self.assertEqual(sessions, tuple(sorted((first, second), key=lambda session: session.session_id)))

    def test_validates_only_exact_active_session_owner(self) -> None:
        session = self._begin()
        valid = self.service.validate_active_session_ownership(
            DesktopSessionOwnershipRequest(
                session_id=session.session_id,
                owner_id=session.owner_id,
                evaluated_at=self.started_at + timedelta(seconds=30),
            )
        )
        wrong_owner = self.service.validate_active_session_ownership(
            DesktopSessionOwnershipRequest(
                session_id=session.session_id,
                owner_id="other-owner",
                evaluated_at=self.started_at + timedelta(seconds=30),
            )
        )

        self.assertTrue(valid.allowed)
        self.assertIs(valid.reason, DesktopSessionReason.SESSION_OWNER_VALID)
        self.assertFalse(wrong_owner.allowed)
        self.assertIs(wrong_owner.reason, DesktopSessionReason.SESSION_OWNER_MISMATCH)

    def test_timeout_replaces_active_record_without_mutating_original(self) -> None:
        original = self._begin()

        timed_out = self.service.lookup_session(
            original.session_id,
            evaluated_at=original.expires_at,
        )

        assert timed_out is not None
        self.assertIs(original.status, DesktopSessionStatus.ACTIVE)
        self.assertIs(timed_out.status, DesktopSessionStatus.TIMED_OUT)
        self.assertEqual(timed_out.ended_at, original.expires_at)
        self.assertEqual(timed_out.end_reason, "timeout_elapsed")
        ownership = self.service.validate_active_session_ownership(
            DesktopSessionOwnershipRequest(
                session_id=original.session_id,
                owner_id=original.owner_id,
                evaluated_at=original.expires_at + timedelta(seconds=1),
            )
        )
        self.assertIs(ownership.reason, DesktopSessionReason.SESSION_TIMED_OUT)

    def test_end_session_requires_owner_and_creates_new_terminal_record(self) -> None:
        original = self._begin()
        wrong_owner = self.service.end_session(
            DesktopSessionEndRequest(
                session_id=original.session_id,
                owner_id="other-owner",
                ended_at=self.started_at + timedelta(seconds=30),
            )
        )
        ended = self.service.end_session(
            DesktopSessionEndRequest(
                session_id=original.session_id,
                owner_id=original.owner_id,
                ended_at=self.started_at + timedelta(seconds=30),
            )
        )

        self.assertIs(wrong_owner.reason, DesktopSessionReason.SESSION_OWNER_MISMATCH)
        self.assertTrue(ended.allowed)
        self.assertIs(ended.reason, DesktopSessionReason.SESSION_ENDED)
        assert ended.session is not None
        self.assertIs(original.status, DesktopSessionStatus.ACTIVE)
        self.assertIs(ended.session.status, DesktopSessionStatus.ENDED)
        self.assertEqual(self.service.lookup_session(original.session_id), ended.session)

    def test_end_session_fails_closed_after_timeout(self) -> None:
        session = self._begin()

        decision = self.service.end_session(
            DesktopSessionEndRequest(
                session_id=session.session_id,
                owner_id=session.owner_id,
                ended_at=session.expires_at,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertIs(decision.reason, DesktopSessionReason.SESSION_TIMED_OUT)
        assert decision.session is not None
        self.assertIs(decision.session.status, DesktopSessionStatus.TIMED_OUT)

    def test_invalid_requests_return_typed_denials(self) -> None:
        begin = self.service.begin_session(object())
        end = self.service.end_session(object())
        ownership = self.service.validate_active_session_ownership(object())

        for decision in (begin, end, ownership):
            self.assertIsInstance(decision, DesktopSessionDecision)
            self.assertFalse(decision.allowed)
            self.assertIs(decision.reason, DesktopSessionReason.INVALID_REQUEST)

    def test_service_exposes_no_action_or_runtime_integration(self) -> None:
        session = self._begin()

        self.assertTrue(session.active)
        self.assertFalse(hasattr(self.service, "runtime"))
        self.assertFalse(hasattr(self.service, "executor"))
        self.assertFalse(hasattr(self.service, "mouse"))
        self.assertFalse(hasattr(self.service, "keyboard"))
        self.assertFalse(hasattr(self.service, "window"))
        self.assertFalse(hasattr(self.service, "browser"))
        self.assertFalse(hasattr(self.service, "filesystem"))


if __name__ == "__main__":
    unittest.main()
