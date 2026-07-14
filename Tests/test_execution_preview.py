"""Comprehensive tests for Phase 11 Safe Execution Layer Sprint 2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from Core.execution import ExecutionRequest
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Execution.preview import (
    ActionPreview,
    DefaultDurationEstimator,
    DuplicatePreviewError,
    ExecutionPreviewManager,
    ExecutionReadiness,
    PermissionLevel,
    PreviewCancelledError,
    PreviewNotFoundError,
    PreviewPlanner,
    PreviewRiskAnalysis,
    PreviewStatus,
    PreviewValidationError,
    RiskAnalysisError,
    RiskAnalyzer,
    RiskFactor,
    RiskLevel,
    SummaryGenerator,
    SummaryValidationError,
)
from Execution.session import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalToken,
    ExecutionSession,
    SessionStatus,
)


class _Clock:
    """Mutable aware clock for deterministic preview tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _CapturingLogger:
    """Core-compatible structured logger double."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _FixedEstimator:
    """Duration estimator injected to verify planner composition."""

    def __init__(self, duration: timedelta) -> None:
        self.duration = duration
        self.requests: list[ExecutionRequest] = []

    def estimate(self, request: ExecutionRequest) -> timedelta:
        self.requests.append(request)
        return self.duration


def _action(
    *,
    action: str = "system.inspect_status",
    order: int = 1,
    duration: float = 1,
    permission: PermissionLevel = PermissionLevel.STANDARD,
    rollback: bool = False,
    action_id: str | None = None,
) -> ActionPreview:
    return ActionPreview(
        action=action,
        order=order,
        estimated_duration=timedelta(seconds=duration),
        required_permission=permission,
        rollback_available=rollback,
        action_id=action_id or f"action-{order}",
        parameters={"nested": {"values": [1, 2]}},
    )


def _session(
    clock: _Clock, *, status: SessionStatus = SessionStatus.ACTIVE
) -> ExecutionSession:
    return ExecutionSession(
        session_id="session-001",
        owner_id="operator",
        created_at=clock.now,
        expires_at=clock.now + timedelta(minutes=10),
        status=status,
    )


def _risk(
    clock: _Clock,
    *,
    level: RiskLevel = RiskLevel.LOW,
    score: float = 10,
) -> PreviewRiskAnalysis:
    return PreviewRiskAnalysis(
        preview_id="preview-001",
        request_id="request-001",
        score=score,
        level=level,
        analyzed_at=clock.now,
    )


class PreviewModelTests(unittest.TestCase):
    """Verify immutable action, risk, summary, and preview contracts."""

    def setUp(self) -> None:
        self.clock = _Clock()

    def test_action_preview_is_deeply_immutable_and_typed(self) -> None:
        parameters = {"nested": {"values": [1]}}
        action = ActionPreview(
            action="system.inspect_status",
            order=1,
            parameters=parameters,
            estimated_duration=timedelta(seconds=2.5),
        )
        parameters["nested"]["values"].append(2)

        self.assertEqual(action.parameters["nested"]["values"], (1,))
        self.assertEqual(action.estimated_duration_seconds, 2.5)
        with self.assertRaises(TypeError):
            action.parameters["new"] = True  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            action.order = 2  # type: ignore[misc]

    def test_action_preview_rejects_invalid_order_duration_and_permission(self) -> None:
        with self.assertRaises(ValueError):
            _action(order=0)
        with self.assertRaises(ValueError):
            _action(duration=-1)
        with self.assertRaises(TypeError):
            _action(permission="standard")  # type: ignore[arg-type]

    def test_risk_analysis_rejects_level_score_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            _risk(self.clock, level=RiskLevel.CRITICAL, score=10)
        with self.assertRaises(ValueError):
            _risk(self.clock, level=RiskLevel.LOW, score=101)

    def test_preview_rejects_non_dry_run_and_inconsistent_summary(self) -> None:
        preview = PreviewPlanner(clock=self.clock).generate(
            ExecutionRequest(action="system.inspect_status")
        )

        with self.assertRaises(ValueError):
            replace(preview, dry_run=False)
        with self.assertRaises(ValueError):
            replace(
                preview,
                summary=replace(preview.summary, action_count=2),
            )
        with self.assertRaises(ValueError):
            replace(preview, executed=True)


class RiskAnalysisTests(unittest.TestCase):
    """Verify all four deterministic risk levels, validation, events, and logs."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        self.bus.subscribe("execution.risk.analyzed", self.events.append)
        self.analyzer = RiskAnalyzer(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )

    def test_score_thresholds_cover_all_supported_levels(self) -> None:
        expected = {
            0: RiskLevel.LOW,
            24.99: RiskLevel.LOW,
            25: RiskLevel.MEDIUM,
            49.99: RiskLevel.MEDIUM,
            50: RiskLevel.HIGH,
            74.99: RiskLevel.HIGH,
            75: RiskLevel.CRITICAL,
            100: RiskLevel.CRITICAL,
        }

        for score, level in expected.items():
            with self.subTest(score=score):
                self.assertIs(self.analyzer.level_for_score(score), level)

    def test_low_risk_read_only_rollback_plan(self) -> None:
        request = ExecutionRequest(
            action="system.inspect_status",
            permission_level=PermissionLevel.READ_ONLY,
        )

        result = self.analyzer.analyze(
            request,
            [_action(permission=PermissionLevel.READ_ONLY, rollback=True)],
            preview_id="preview-low",
        )

        self.assertIs(result.level, RiskLevel.LOW)
        self.assertLess(result.score, 25)

    def test_medium_risk_standard_plan_without_rollback(self) -> None:
        result = self.analyzer.analyze(
            ExecutionRequest(action="application.open"),
            [_action(action="application.open")],
            preview_id="preview-medium",
        )

        self.assertIs(result.level, RiskLevel.MEDIUM)
        self.assertEqual(result.score, 25)

    def test_high_risk_elevated_plan(self) -> None:
        result = self.analyzer.analyze(
            ExecutionRequest(
                action="application.open",
                permission_level=PermissionLevel.ELEVATED,
            ),
            [_action(permission=PermissionLevel.ELEVATED)],
            preview_id="preview-high",
        )

        self.assertIs(result.level, RiskLevel.HIGH)

    def test_critical_risk_term_is_scoring_only(self) -> None:
        result = self.analyzer.analyze(
            ExecutionRequest(action="system.shutdown"),
            [_action(action="system.shutdown")],
            preview_id="preview-critical",
        )

        self.assertIs(result.level, RiskLevel.CRITICAL)
        self.assertTrue(result.scoring_only)
        self.assertIn(
            "critical_action_term",
            [factor.code for factor in result.factors],
        )

    def test_analysis_publishes_safe_event_and_structured_log(self) -> None:
        secret = "do-not-publish"
        request = ExecutionRequest(
            action="application.open",
            parameters={"secret": secret},
        )

        result = self.analyzer.analyze(
            request,
            [_action(action="application.open")],
            preview_id="preview-001",
        )

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].payload["risk_score"], result.score)
        self.assertFalse(self.events[0].payload["executed"])
        self.assertNotIn(secret, repr(self.events[0].payload))
        self.assertTrue(
            any(
                message == "Execution preview risk analyzed"
                for _, message, _ in self.logger.entries
            )
        )

    def test_invalid_analysis_inputs_fail_closed(self) -> None:
        with self.assertRaises(RiskAnalysisError):
            self.analyzer.analyze(  # type: ignore[arg-type]
                object(),
                [_action()],
            )
        with self.assertRaises(RiskAnalysisError):
            self.analyzer.analyze(
                ExecutionRequest(action="system.inspect_status"),
                [],
            )
        with self.assertRaises(RiskAnalysisError):
            self.analyzer.level_for_score(float("nan"))


class SummaryAndDurationTests(unittest.TestCase):
    """Verify aggregation, duration estimation, approvals, and readiness."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.generator = SummaryGenerator(clock=self.clock)

    def test_summary_aggregates_count_duration_permissions_and_rollback(self) -> None:
        actions = (
            _action(
                order=1,
                duration=2,
                permission=PermissionLevel.READ_ONLY,
                rollback=True,
            ),
            _action(
                action="application.open",
                order=2,
                duration=3.5,
                permission=PermissionLevel.STANDARD,
                rollback=True,
            ),
        )
        risk = _risk(self.clock)

        summary = self.generator.generate(actions, risk)

        self.assertEqual(summary.action_count, 2)
        self.assertEqual(summary.estimated_duration_seconds, 5.5)
        self.assertEqual(
            summary.required_permissions,
            (PermissionLevel.READ_ONLY, PermissionLevel.STANDARD),
        )
        self.assertTrue(summary.rollback_available)
        self.assertTrue(summary.execution_ready)

    def test_pending_medium_risk_requires_approval(self) -> None:
        summary = self.generator.generate(
            [_action()],
            _risk(self.clock, level=RiskLevel.MEDIUM, score=25),
            approval=ApprovalStatus.PENDING,
        )

        self.assertTrue(summary.approval_required)
        self.assertIs(
            summary.execution_readiness,
            ExecutionReadiness.APPROVAL_REQUIRED,
        )

    def test_approved_medium_risk_is_ready(self) -> None:
        response = ApprovalResponse(
            request_id="approval-001",
            decision=ApprovalDecision.APPROVE,
            responded_by="operator",
            responded_at=self.clock.now,
        )

        summary = self.generator.generate(
            [_action()],
            _risk(self.clock, level=RiskLevel.MEDIUM, score=25),
            approval=response,
        )

        self.assertFalse(summary.approval_required)
        self.assertIs(summary.readiness, ExecutionReadiness.READY)

    def test_denied_or_critical_preview_is_blocked(self) -> None:
        denied = self.generator.generate(
            [_action()],
            _risk(self.clock, level=RiskLevel.MEDIUM, score=25),
            approval=ApprovalStatus.DENIED,
        )
        critical = self.generator.generate(
            [_action()],
            _risk(self.clock, level=RiskLevel.CRITICAL, score=75),
            approval=ApprovalStatus.APPROVED,
        )

        self.assertIs(denied.readiness, ExecutionReadiness.BLOCKED)
        self.assertIs(critical.readiness, ExecutionReadiness.BLOCKED)

    def test_expired_token_is_blocked(self) -> None:
        token = ApprovalToken(
            request_id="approval-001",
            session_id="session-001",
            issued_to="operator",
            issued_at=self.clock.now - timedelta(minutes=2),
            expires_at=self.clock.now - timedelta(minutes=1),
        )

        summary = self.generator.generate(
            [_action()],
            _risk(self.clock, level=RiskLevel.MEDIUM, score=25),
            approval=token,
        )

        self.assertIs(summary.readiness, ExecutionReadiness.BLOCKED)

    def test_cancelled_summary_is_not_execution_ready(self) -> None:
        summary = self.generator.generate(
            [_action()],
            _risk(self.clock),
            cancelled=True,
        )

        self.assertIs(summary.readiness, ExecutionReadiness.CANCELLED)
        self.assertFalse(summary.approval_required)

    def test_duration_estimator_uses_explicit_metadata_and_validates(self) -> None:
        estimator = DefaultDurationEstimator(timedelta(seconds=4))

        self.assertEqual(
            estimator.estimate(
                ExecutionRequest(
                    action="application.open",
                    metadata={"estimated_duration_seconds": 2.25},
                )
            ),
            timedelta(seconds=2.25),
        )
        self.assertEqual(
            estimator.estimate(ExecutionRequest(action="application.open")),
            timedelta(seconds=4),
        )
        with self.assertRaises(PreviewValidationError):
            estimator.estimate(
                ExecutionRequest(
                    action="application.open",
                    metadata={"estimated_duration_seconds": "soon"},
                )
            )

    def test_summary_rejects_invalid_approval_context(self) -> None:
        with self.assertRaises(SummaryValidationError):
            self.generator.generate(
                [_action()],
                _risk(self.clock),
                approval=object(),  # type: ignore[arg-type]
            )


class PreviewPlannerTests(unittest.TestCase):
    """Verify preview creation, session/approval integration, and events."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "execution.preview.created",
            "execution.preview.updated",
            "execution.preview.cancelled",
            "execution.risk.analyzed",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.planner = PreviewPlanner(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
        )

    def test_creation_generates_complete_dry_run_from_request(self) -> None:
        request = ExecutionRequest(
            action="system.inspect_status",
            permission_level=PermissionLevel.READ_ONLY,
            parameters={"scope": "runtime"},
            metadata={
                "estimated_duration_seconds": 2,
                "rollback_available": True,
                "correlation_id": "conversation-001",
            },
        )

        preview = self.planner.generate(request)

        self.assertTrue(preview.dry_run)
        self.assertFalse(preview.executed)
        self.assertFalse(preview.dispatcher_invoked)
        self.assertEqual(preview.request_id, request.request_id)
        self.assertEqual(len(preview.ordered_actions), 1)
        self.assertEqual(preview.estimated_duration, timedelta(seconds=2))
        self.assertEqual(
            preview.required_permissions,
            (PermissionLevel.READ_ONLY,),
        )
        self.assertEqual(
            preview.metadata["correlation_id"],
            "conversation-001",
        )
        self.assertIs(preview.summary.readiness, ExecutionReadiness.READY)

    def test_custom_actions_preserve_order_and_sum_duration(self) -> None:
        actions = (
            _action(order=1, duration=1, rollback=True),
            _action(
                action="application.open",
                order=2,
                duration=2.5,
                rollback=True,
            ),
        )

        preview = self.planner.plan(
            ExecutionRequest(action="workflow.preview"),
            actions=actions,
        )

        self.assertEqual(preview.actions, actions)
        self.assertEqual(preview.summary.action_count, 2)
        self.assertEqual(preview.summary.estimated_duration_seconds, 3.5)

    def test_injected_duration_estimator_is_used(self) -> None:
        estimator = _FixedEstimator(timedelta(seconds=7))
        planner = PreviewPlanner(
            duration_estimator=estimator,
            clock=self.clock,
        )
        request = ExecutionRequest(action="application.open")

        preview = planner.generate(request)

        self.assertEqual(preview.estimated_duration, timedelta(seconds=7))
        self.assertEqual(estimator.requests, [request])

    def test_active_session_and_matching_approval_are_bound(self) -> None:
        request = ExecutionRequest(action="application.open")
        session = _session(self.clock)
        approval = ApprovalRequest(
            execution_request=request,
            session_id=session.session_id,
            requested_by="planner",
            requested_at=self.clock.now,
            expires_at=self.clock.now + timedelta(minutes=5),
        )

        preview = self.planner.generate(
            request,
            session=session,
            approval=approval,
        )

        self.assertEqual(preview.session_id, session.session_id)
        self.assertIs(preview.approval_status, ApprovalStatus.PENDING)
        self.assertTrue(preview.summary.approval_required)

    def test_expired_session_or_mismatched_approval_is_rejected(self) -> None:
        request = ExecutionRequest(action="application.open")
        expired = replace(
            _session(self.clock),
            status=SessionStatus.EXPIRED,
        )
        other_request = ExecutionRequest(action="application.close")
        approval = ApprovalRequest(
            execution_request=other_request,
            session_id="session-001",
            requested_by="planner",
            requested_at=self.clock.now,
            expires_at=self.clock.now + timedelta(minutes=5),
        )

        with self.assertRaises(PreviewValidationError):
            self.planner.generate(request, session=expired)
        with self.assertRaises(PreviewValidationError):
            self.planner.generate(
                request,
                session=_session(self.clock),
                approval=approval,
            )

    def test_creation_emits_risk_then_created_and_logs_generation(self) -> None:
        preview = self.planner.create_preview(
            ExecutionRequest(action="application.open")
        )

        self.assertEqual(
            [event.name for event in self.events],
            ["execution.risk.analyzed", "execution.preview.created"],
        )
        created = self.events[-1]
        self.assertEqual(created.payload["preview_id"], preview.preview_id)
        self.assertTrue(created.payload["dry_run"])
        self.assertFalse(created.payload["executed"])
        self.assertTrue(
            any(
                message == "Execution preview generated"
                for _, message, _ in self.logger.entries
            )
        )

    def test_invalid_request_actions_and_metadata_are_rejected(self) -> None:
        with self.assertRaises(PreviewValidationError):
            self.planner.generate(object())  # type: ignore[arg-type]
        with self.assertRaises(PreviewValidationError):
            self.planner.generate(
                ExecutionRequest(action="application.open"),
                actions=[_action(order=2)],
            )
        with self.assertRaises(PreviewValidationError):
            self.planner.generate(
                ExecutionRequest(action="application.open"),
                metadata=[],  # type: ignore[arg-type]
            )

    def test_event_subscriber_failure_does_not_change_preview(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "execution.preview.created",
            lambda event: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        planner = PreviewPlanner(
            event_bus=bus,
            logger=self.logger,
            clock=self.clock,
        )

        preview = planner.generate(ExecutionRequest(action="application.open"))

        self.assertTrue(preview.dry_run)
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in self.logger.entries)
        )


class PreviewLifecycleTests(unittest.TestCase):
    """Verify retained preview updates, cancellation, and lookup validation."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "execution.preview.created",
            "execution.preview.updated",
            "execution.preview.cancelled",
            "execution.risk.analyzed",
        ):
            self.bus.subscribe(event_name, self.events.append)
        self.manager = ExecutionPreviewManager(
            event_bus=self.bus,
            clock=self.clock,
        )

    def test_update_recomputes_summary_and_preserves_old_snapshot(self) -> None:
        original = self.manager.create_preview(
            ExecutionRequest(action="application.open"),
            preview_id="preview-001",
        )
        self.clock.advance(seconds=1)
        actions = (
            _action(order=1, duration=2, rollback=True),
            _action(
                action="application.open",
                order=2,
                duration=3,
                rollback=True,
            ),
        )

        updated = self.manager.update_preview(
            original.preview_id,
            actions=actions,
            approval=ApprovalStatus.APPROVED,
            metadata={"revision": 2},
        )

        self.assertIs(original.status, PreviewStatus.READY)
        self.assertEqual(original.summary.action_count, 1)
        self.assertIs(updated.status, PreviewStatus.UPDATED)
        self.assertEqual(updated.summary.action_count, 2)
        self.assertEqual(updated.summary.estimated_duration_seconds, 5)
        self.assertEqual(updated.metadata["revision"], 2)
        self.assertGreater(updated.updated_at, updated.created_at)
        self.assertIn(
            "execution.preview.updated", [event.name for event in self.events]
        )

    def test_cancel_marks_readiness_and_prevents_updates(self) -> None:
        preview = self.manager.create_preview(
            ExecutionRequest(action="application.open"),
            preview_id="preview-001",
        )
        self.clock.advance(seconds=1)

        cancelled = self.manager.cancel_preview(
            preview.preview_id,
            reason="operator withdrew the plan",
        )

        self.assertTrue(cancelled.cancelled)
        self.assertIs(cancelled.summary.readiness, ExecutionReadiness.CANCELLED)
        self.assertEqual(
            cancelled.metadata["cancellation_reason"],
            "operator withdrew the plan",
        )
        event = next(
            event
            for event in self.events
            if event.name == "execution.preview.cancelled"
        )
        self.assertFalse(event.payload["executed"])
        with self.assertRaises(PreviewCancelledError):
            self.manager.update_preview(preview.preview_id)
        with self.assertRaises(PreviewCancelledError):
            self.manager.cancel_preview(preview.preview_id)

    def test_lookup_list_duplicate_and_missing_preview(self) -> None:
        preview = self.manager.create_preview(
            ExecutionRequest(action="application.open"),
            preview_id="preview-001",
        )

        self.assertEqual(self.manager.get_preview(preview.preview_id), preview)
        self.assertEqual(self.manager.list_previews(), (preview,))
        with self.assertRaises(DuplicatePreviewError):
            self.manager.create_preview(
                ExecutionRequest(action="application.close"),
                preview_id="preview-001",
            )
        with self.assertRaises(PreviewNotFoundError):
            self.manager.get_preview("missing")


if __name__ == "__main__":
    unittest.main()
