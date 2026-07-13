"""Unit tests for Phase 8 Sprint 2 trusted execution decisions."""

from __future__ import annotations

import unittest

from Core.execution import (
    AllowPolicy,
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalManager,
    ApprovalRequiredPolicy,
    DenyPolicy,
    ExecutionRequest,
    ExecutionStatus,
    PermissionEngine,
    PermissionLevel,
    PolicyDecision,
    PolicyDecisionType,
    RiskAnalyzer,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    TrustedExecutionGateway,
    TrustPolicyContext,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _CapturingLogger:
    """Retain structured log entries for stage assertions."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        """Capture one log entry."""

        self.entries.append((level, message, context))


class _MediumRiskRule:
    """Custom rule proving that the analyzer rule set is replaceable."""

    def evaluate(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel,
    ) -> tuple[RiskFactor, ...]:
        """Classify every request as medium risk."""

        del request, permission_level
        return (
            RiskFactor(
                source=type(self).__name__,
                risk_level=RiskLevel.MEDIUM,
                reason_code="custom_medium",
                description="Custom scorer selected medium risk.",
            ),
        )


class _RiskFailure:
    """Risk analyzer double that raises an internal error."""

    def analyze(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel | None = None,
    ) -> RiskAssessment:
        """Raise a simulated scoring failure."""

        del request, permission_level
        raise RuntimeError("risk service unavailable")


class _PolicyFailure:
    """Custom trust policy double that raises an internal error."""

    name = "failing_policy"

    def evaluate(self, context: TrustPolicyContext) -> PolicyDecision:
        """Raise a simulated policy failure."""

        del context
        raise RuntimeError("policy service unavailable")


class _CustomAllowPolicy:
    """Custom protocol-compatible policy used to verify extensibility."""

    name = "custom_allow"

    def evaluate(self, context: TrustPolicyContext) -> PolicyDecision:
        """Allow the request using only inert policy context."""

        self.last_risk = context.risk_assessment.risk_level
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            policy_name=self.name,
            reason_code="custom_policy_allowed",
            message="Custom policy allows this request.",
        )


class _ProviderSpy:
    """Future approval provider that must remain unused in Sprint 2."""

    name = "dashboard"

    def __init__(self) -> None:
        self.called = False

    def request_approval(
        self,
        request: ExecutionRequest,
        decision: ApprovalDecision,
    ) -> ApprovalDecisionType:
        """Record an unexpected provider invocation."""

        del request, decision
        self.called = True
        return ApprovalDecisionType.GRANTED


class RiskAnalyzerTests(unittest.TestCase):
    """Verify every risk level and rule extension behavior."""

    def setUp(self) -> None:
        self.analyzer = RiskAnalyzer()

    def test_classifies_low_risk_read_request(self) -> None:
        assessment = self.analyzer.analyze(
            ExecutionRequest(
                action="file.read",
                permission_level=PermissionLevel.READ_ONLY,
            )
        )

        self.assertIs(assessment.risk_level, RiskLevel.LOW)
        self.assertIs(assessment.level, RiskLevel.LOW)

    def test_classifies_medium_risk_external_action(self) -> None:
        assessment = self.analyzer.analyze(ExecutionRequest(action="file.create"))

        self.assertIs(assessment.risk_level, RiskLevel.MEDIUM)
        self.assertIn("action_has_external_side_effect", assessment.reason_codes)

    def test_classifies_high_risk_mutation_and_elevated_permission(self) -> None:
        assessment = self.analyzer.analyze(
            ExecutionRequest(
                action="file.write",
                permission_level=PermissionLevel.ELEVATED,
            )
        )

        self.assertIs(assessment.risk_level, RiskLevel.HIGH)
        self.assertIn("permission_elevated", assessment.reason_codes)

    def test_classifies_critical_risk_from_permission_and_metadata(self) -> None:
        assessment = self.analyzer.analyze(
            ExecutionRequest(
                action="system.inspect",
                permission_level=PermissionLevel.ADMINISTRATOR,
                metadata={"irreversible": True},
            )
        )

        self.assertIs(assessment.risk_level, RiskLevel.CRITICAL)
        self.assertIn("metadata_irreversible", assessment.reason_codes)

    def test_explicit_metadata_can_only_elevate_the_combined_risk(self) -> None:
        assessment = self.analyzer.analyze(
            ExecutionRequest(
                action="system.delete",
                metadata={"risk_level": "low", "trusted_source": False},
            )
        )

        self.assertIs(assessment.risk_level, RiskLevel.HIGH)
        self.assertIn("metadata_declared_risk", assessment.reason_codes)
        self.assertIn("metadata_untrusted_source", assessment.reason_codes)

    def test_custom_rule_sequence_can_replace_default_rules(self) -> None:
        analyzer = RiskAnalyzer(rules=(_MediumRiskRule(),))

        assessment = analyzer.classify(
            ExecutionRequest(
                action="system.format",
                permission_level=PermissionLevel.ADMINISTRATOR,
            )
        )

        self.assertIs(assessment.risk_level, RiskLevel.MEDIUM)
        self.assertEqual(assessment.reason_codes, ("custom_medium",))


class TrustPolicyTests(unittest.TestCase):
    """Verify built-in policies remain pure and custom policies are supported."""

    def setUp(self) -> None:
        request = ExecutionRequest(
            action="file.read",
            permission_level=PermissionLevel.READ_ONLY,
        )
        self.context = TrustPolicyContext(
            request=request,
            risk_assessment=RiskAnalyzer().analyze(request),
            permission_granted=True,
            required_permission_level=PermissionLevel.READ_ONLY,
        )

    def test_allow_policy_returns_allow(self) -> None:
        decision = AllowPolicy().evaluate(self.context)

        self.assertIs(decision.decision, PolicyDecisionType.ALLOW)
        self.assertTrue(decision.allowed)

    def test_deny_policy_returns_deny(self) -> None:
        decision = DenyPolicy().evaluate(self.context)

        self.assertIs(decision.decision, PolicyDecisionType.DENY)
        self.assertTrue(decision.denied)

    def test_approval_policy_returns_approval_required(self) -> None:
        decision = ApprovalRequiredPolicy().evaluate(self.context)

        self.assertIs(
            decision.decision,
            PolicyDecisionType.APPROVAL_REQUIRED,
        )
        self.assertTrue(decision.approval_required)

    def test_custom_policy_works_through_the_policy_protocol(self) -> None:
        policy = _CustomAllowPolicy()

        decision = policy.evaluate(self.context)

        self.assertTrue(decision.allowed)
        self.assertIs(policy.last_risk, RiskLevel.LOW)


class ApprovalManagerTests(unittest.TestCase):
    """Verify permission, risk, policy, provider, and failure decisions."""

    def test_low_is_granted_medium_requires_approval_and_critical_is_denied(
        self,
    ) -> None:
        manager = ApprovalManager(
            PermissionEngine(maximum_level=PermissionLevel.ADMINISTRATOR)
        )

        low = manager.decide(ExecutionRequest(action="file.read"))
        medium = manager.decide(ExecutionRequest(action="file.create"))
        critical = manager.decide(
            ExecutionRequest(
                action="system.inspect",
                permission_level=PermissionLevel.ADMINISTRATOR,
            )
        )

        self.assertTrue(low.granted)
        self.assertTrue(medium.approval_required)
        self.assertTrue(critical.denied)
        self.assertEqual(critical.reason_code, "critical_risk_denied")

    def test_permission_denial_precedes_an_allow_policy(self) -> None:
        manager = ApprovalManager(
            PermissionEngine(maximum_level=PermissionLevel.READ_ONLY),
            policies={RiskLevel.HIGH: AllowPolicy()},
        )

        decision = manager.decide(
            ExecutionRequest(
                action="file.write",
                permission_level=PermissionLevel.ELEVATED,
            )
        )

        self.assertTrue(decision.denied)
        self.assertFalse(decision.permission_granted)
        self.assertEqual(decision.reason_code, "permission_denied")

    def test_effective_action_permission_informs_risk(self) -> None:
        manager = ApprovalManager(
            PermissionEngine(
                maximum_level=PermissionLevel.ADMINISTRATOR,
                action_permissions={"system.inspect": PermissionLevel.ADMINISTRATOR},
            )
        )

        decision = manager.decide(ExecutionRequest(action="system.inspect"))

        self.assertTrue(decision.denied)
        assert decision.risk_assessment is not None
        self.assertIs(decision.risk_assessment.risk_level, RiskLevel.CRITICAL)

    def test_custom_policy_can_override_one_default_risk_policy(self) -> None:
        policy = _CustomAllowPolicy()
        manager = ApprovalManager(policies={RiskLevel.MEDIUM: policy})

        decision = manager.evaluate(ExecutionRequest(action="file.create"))

        self.assertTrue(decision.approved)
        self.assertEqual(decision.reason_code, "custom_policy_allowed")

    def test_provider_is_retained_but_never_invoked(self) -> None:
        provider = _ProviderSpy()
        manager = ApprovalManager(providers=(provider,))

        decision = manager.decide(ExecutionRequest(action="file.create"))

        self.assertTrue(decision.requires_approval)
        self.assertEqual(manager.providers, (provider,))
        self.assertFalse(provider.called)

    def test_risk_and_policy_failures_return_typed_denials(self) -> None:
        risk_failure = ApprovalManager(risk_analyzer=_RiskFailure()).decide(
            ExecutionRequest(action="file.read")
        )
        policy_failure = ApprovalManager(
            policies={RiskLevel.LOW: _PolicyFailure()}
        ).decide(ExecutionRequest(action="file.read"))

        self.assertTrue(risk_failure.denied)
        self.assertEqual(risk_failure.reason_code, "risk_analysis_failed")
        self.assertEqual(risk_failure.failure_stage, "risk")
        self.assertTrue(policy_failure.denied)
        self.assertEqual(policy_failure.reason_code, "policy_evaluation_failed")
        self.assertEqual(policy_failure.failure_stage, "policy")


class GatewaySprint2Tests(unittest.TestCase):
    """Verify integrated decisions, events, logs, and non-execution safety."""

    def _capturing_bus(self) -> tuple[EventBus, list[SystemEvent]]:
        event_bus = EventBus()
        events: list[SystemEvent] = []
        for event_name in (
            TrustedExecutionGateway.RISK_EVALUATED_EVENT,
            TrustedExecutionGateway.APPROVAL_REQUIRED_EVENT,
            TrustedExecutionGateway.APPROVAL_GRANTED_EVENT,
            TrustedExecutionGateway.APPROVAL_DENIED_EVENT,
        ):
            event_bus.subscribe(event_name, events.append)
        return event_bus, events

    def test_low_risk_gateway_publishes_risk_and_grant_events(self) -> None:
        event_bus, events = self._capturing_bus()
        logger = _CapturingLogger()
        gateway = TrustedExecutionGateway(event_bus=event_bus, logger=logger)

        result = gateway.execute(ExecutionRequest(action="application.open"))

        self.assertIs(result.status, ExecutionStatus.AUTHORIZED)
        self.assertIs(result.risk_level, RiskLevel.LOW)
        self.assertIs(result.approval_decision, ApprovalDecisionType.GRANTED)
        self.assertFalse(result.executed)
        self.assertFalse(result.dispatcher_invoked)
        self.assertEqual(
            [event.name for event in events],
            [
                TrustedExecutionGateway.RISK_EVALUATED_EVENT,
                TrustedExecutionGateway.APPROVAL_GRANTED_EVENT,
            ],
        )
        self.assertTrue(
            any(
                message == "Trust policy evaluated for approval"
                for _, message, _ in logger.entries
            )
        )

    def test_medium_risk_gateway_is_pending_and_requests_approval(self) -> None:
        event_bus, events = self._capturing_bus()
        gateway = TrustedExecutionGateway(event_bus=event_bus)

        result = gateway.authorize(ExecutionRequest(action="file.create"))

        self.assertIs(result.status, ExecutionStatus.PENDING)
        self.assertEqual(result.reason_code, "approval_required")
        self.assertIs(result.approval_decision, ApprovalDecisionType.REQUIRED)
        self.assertFalse(result.executed)
        self.assertEqual(
            [event.name for event in events],
            [
                TrustedExecutionGateway.RISK_EVALUATED_EVENT,
                TrustedExecutionGateway.APPROVAL_REQUIRED_EVENT,
            ],
        )

    def test_critical_gateway_denial_publishes_denied_event(self) -> None:
        event_bus, events = self._capturing_bus()
        gateway = TrustedExecutionGateway(
            PermissionEngine(maximum_level=PermissionLevel.ADMINISTRATOR),
            event_bus=event_bus,
        )

        result = gateway.authorize(
            ExecutionRequest(
                action="system.inspect",
                permission_level=PermissionLevel.ADMINISTRATOR,
            )
        )

        self.assertIs(result.status, ExecutionStatus.DENIED)
        self.assertEqual(result.reason_code, "critical_risk_denied")
        self.assertFalse(result.executed)
        self.assertEqual(
            [event.name for event in events],
            [
                TrustedExecutionGateway.RISK_EVALUATED_EVENT,
                TrustedExecutionGateway.APPROVAL_DENIED_EVENT,
            ],
        )

    def test_risk_failure_denies_without_publishing_a_false_risk_event(self) -> None:
        event_bus, events = self._capturing_bus()
        gateway = TrustedExecutionGateway(
            risk_analyzer=_RiskFailure(),
            event_bus=event_bus,
        )

        result = gateway.authorize(ExecutionRequest(action="file.read"))

        self.assertIs(result.status, ExecutionStatus.DENIED)
        self.assertEqual(result.reason_code, "risk_analysis_failed")
        self.assertEqual(
            [event.name for event in events],
            [TrustedExecutionGateway.APPROVAL_DENIED_EVENT],
        )


if __name__ == "__main__":
    unittest.main()
