"""Comprehensive tests for Phase 13 AI Orchestrator Sprint 2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from AI import (
    AIManager,
    AIProvider,
    AIRequest,
    CapabilityMatch,
    CapabilityMatcher,
    CompatibilityReport,
    CompatibilityValidator,
    FallbackPlan,
    FallbackPlanner,
    FallbackUnavailableError,
    NoCompatibleProviderError,
    ProviderCapability,
    ProviderCompatibilityError,
    ProviderHealth,
    ProviderMetadata,
    ProviderNotFoundError,
    ProviderPriority,
    ProviderScore,
    ProviderScorer,
    ProviderScoringError,
    ProviderStatus,
    RequestPolicy,
    RequestPolicyValidator,
    RequestRouter,
    RequestValidationError,
    RoutingExplanation,
    RoutingPolicy,
    RoutingSummary,
    ScoringWeights,
    SelectionPolicy,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _Clock:
    """Mutable aware clock for deterministic routing tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _CapturingLogger:
    """Core-compatible structured logger double."""

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []
        self.fail = fail

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        if self.fail:
            raise RuntimeError("logger unavailable")
        self.entries.append((level, message, context))


def _provider(
    name: str,
    *,
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    priority: ProviderPriority = ProviderPriority.NORMAL,
    status: ProviderStatus = ProviderStatus.AVAILABLE,
    enabled: bool = True,
    models: tuple[str, ...] = ("model-a",),
    attributes: dict[str, object] | None = None,
) -> AIProvider:
    now = datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc)
    return AIProvider(
        metadata=ProviderMetadata(
            name=name,
            display_name=name.title(),
            capabilities=capabilities,
            priority=priority,
            supported_models=models,
            attributes=attributes or {},
            enabled=enabled,
        ),
        health=ProviderHealth(
            provider_id=name,
            status=status,
            checked_at=now,
        ),
        registered_at=now,
    )


def _request(
    *,
    request_id: str = "request-001",
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    preferred: str | None = None,
    model: str | None = None,
    prompt: str = "Route this request",
) -> AIRequest:
    return AIRequest(
        prompt=prompt,
        required_capabilities=capabilities,
        preferred_provider_id=preferred,
        model_hint=model,
        request_id=request_id,
        created_at=datetime(2026, 7, 15, 11, 30, tzinfo=timezone.utc),
    )


def _score(
    provider_id: str,
    *,
    request_id: str = "request-001",
    total: float = 80,
    compatible: bool = True,
) -> ProviderScore:
    return ProviderScore(
        provider_id=provider_id,
        request_id=request_id,
        total=total,
        capability_score=100,
        health_score=100,
        priority_score=50,
        preference_score=50,
        model_score=100,
        compatible=compatible,
        scored_at=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
    )


class RoutingModelTests(unittest.TestCase):
    """Verify immutable policy, matching, scoring, fallback, and summary models."""

    def test_scoring_weights_are_immutable_and_normalized(self) -> None:
        weights = ScoringWeights()
        self.assertAlmostEqual(
            weights.capability
            + weights.health
            + weights.priority
            + weights.preference
            + weights.model,
            1.0,
        )
        with self.assertRaises(FrozenInstanceError):
            weights.health = 0.5  # type: ignore[misc]
        with self.assertRaises(ValueError):
            ScoringWeights(capability=1.0)

    def test_routing_policy_is_deeply_immutable_and_validated(self) -> None:
        metadata = {"constraints": {"regions": ["local"]}}
        policy = RoutingPolicy(
            required_capabilities=(ProviderCapability.CHAT,),
            allowed_capabilities=(
                ProviderCapability.CHAT,
                ProviderCapability.REASONING,
            ),
            excluded_provider_ids=("blocked",),
            metadata=metadata,
        )
        metadata["constraints"]["regions"].append("remote")  # type: ignore[index,union-attr]

        self.assertEqual(policy.metadata["constraints"]["regions"], ("local",))
        self.assertIs(policy.selection_policy, SelectionPolicy.BALANCED)
        self.assertIs(RequestPolicy, RoutingPolicy)
        with self.assertRaises(TypeError):
            policy.metadata["new"] = True  # type: ignore[index]
        with self.assertRaises(ValueError):
            RoutingPolicy(
                required_capabilities=(ProviderCapability.VISION,),
                allowed_capabilities=(ProviderCapability.CHAT,),
            )

    def test_routing_policy_rejects_invalid_limits_and_types(self) -> None:
        with self.assertRaises(TypeError):
            RoutingPolicy(selection="balanced")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            RoutingPolicy(minimum_score=101)
        with self.assertRaises(ValueError):
            RoutingPolicy(max_fallbacks=-1)
        with self.assertRaises(ValueError):
            RoutingPolicy(excluded_provider_ids=(" duplicate ",))

    def test_capability_match_enforces_partition_and_score(self) -> None:
        match = CapabilityMatch(
            provider_id="provider-a",
            required=(ProviderCapability.CHAT, ProviderCapability.REASONING),
            advertised=(ProviderCapability.CHAT,),
            matched=(ProviderCapability.CHAT,),
            missing=(ProviderCapability.REASONING,),
            score=50,
        )
        self.assertFalse(match.compatible)
        with self.assertRaises(ValueError):
            replace(match, score=75)
        with self.assertRaises(ValueError):
            replace(match, missing=())

    def test_compatibility_report_requires_consistent_facts(self) -> None:
        match = CapabilityMatch(
            provider_id="provider-a",
            required=(),
            advertised=(),
            matched=(),
            missing=(),
            score=100,
        )
        report = CompatibilityReport(
            provider_id="provider-a",
            request_id="request-001",
            compatible=True,
            capability_match=match,
            enabled=True,
            health_compatible=True,
            model_compatible=True,
        )
        self.assertTrue(report.compatible)
        with self.assertRaises(ValueError):
            replace(report, compatible=False, reasons=("arbitrary",))
        with self.assertRaises(ValueError):
            replace(report, compatible=True, health_compatible=False)

    def test_provider_score_validates_bounds_and_is_frozen(self) -> None:
        score = _score("provider-a", total=87.5)
        self.assertEqual(score.total_score, 87.5)
        with self.assertRaises(FrozenInstanceError):
            score.total = 10  # type: ignore[misc]
        with self.assertRaises(ValueError):
            replace(score, health_score=-1)

    def test_fallback_plan_is_ordered_and_validated(self) -> None:
        plan = FallbackPlan(
            request_id="request-001",
            primary_provider_id="primary",
            provider_ids=("fallback-a", "fallback-b"),
        )
        self.assertTrue(plan.has_fallback)
        self.assertEqual(plan.chain, ("fallback-a", "fallback-b"))
        self.assertEqual(plan.after(), ("fallback-a", "fallback-b"))
        self.assertEqual(plan.after("fallback-a"), ("fallback-b",))
        with self.assertRaises(ValueError):
            plan.after("unknown")
        with self.assertRaises(ValueError):
            replace(plan, provider_ids=("primary",))

    def test_routing_explanation_requires_safe_factors(self) -> None:
        explanation = RoutingExplanation(
            request_id="request-001",
            selected_provider_id="provider-a",
            summary="Selected provider-a deterministically.",
            factors=("health available",),
        )
        self.assertEqual(explanation.factors, ("health available",))
        with self.assertRaises(ValueError):
            replace(explanation, factors=())

    def test_routing_summary_validates_counts(self) -> None:
        summary = RoutingSummary(
            request_id="request-001",
            selected_provider_id="provider-a",
            candidate_count=3,
            compatible_count=2,
            fallback_count=1,
            selected_score=90,
            selection_policy=SelectionPolicy.BALANCED,
            explanation="Selected provider-a.",
        )
        self.assertEqual(summary.fallback_count, 1)
        with self.assertRaises(ValueError):
            replace(summary, compatible_count=4)

    def test_routing_decision_rejects_invalid_score_and_fallback_bindings(self) -> None:
        decision = RequestRouter(id_factory=lambda: "decision-001").route(
            _request(),
            (
                _provider("primary", priority=ProviderPriority.HIGH),
                _provider("fallback", priority=ProviderPriority.NORMAL),
            ),
        )
        with self.assertRaises(ValueError):
            replace(decision, provider_scores=tuple(reversed(decision.provider_scores)))
        with self.assertRaises(ValueError):
            replace(
                decision,
                fallback_plan=replace(
                    decision.fallback_plan,
                    provider_ids=("not-ranked",),
                ),
            )


class PolicyAndCompatibilityTests(unittest.TestCase):
    """Verify request policies, capability matching, and compatibility filters."""

    def test_policy_validator_combines_request_and_policy_capabilities(self) -> None:
        validator = RequestPolicyValidator()
        request = _request(capabilities=(ProviderCapability.CHAT,))
        policy = RoutingPolicy(required_capabilities=(ProviderCapability.REASONING,))
        self.assertEqual(
            validator.effective_capabilities(request, policy),
            (ProviderCapability.CHAT, ProviderCapability.REASONING),
        )
        self.assertIs(validator.validate(request, policy), request)

    def test_policy_validator_enforces_prompt_limits(self) -> None:
        with self.assertRaises(RequestValidationError):
            RequestPolicyValidator().validate(
                _request(prompt="four"),
                RoutingPolicy(maximum_prompt_characters=3),
            )

    def test_policy_validator_rejects_disallowed_capabilities(self) -> None:
        with self.assertRaises(RequestValidationError):
            RequestPolicyValidator().validate(
                _request(capabilities=(ProviderCapability.VISION,)),
                RoutingPolicy(allowed_capabilities=(ProviderCapability.CHAT,)),
            )

    def test_capability_matcher_reports_complete_and_partial_matches(self) -> None:
        matcher = CapabilityMatcher()
        request = _request(
            capabilities=(ProviderCapability.CHAT, ProviderCapability.REASONING)
        )
        full = matcher.match(
            _provider(
                "full",
                capabilities=(ProviderCapability.CHAT, ProviderCapability.REASONING),
            ),
            request,
            RoutingPolicy(),
        )
        partial = matcher.match(
            _provider("partial"),
            request,
            RoutingPolicy(),
        )
        self.assertTrue(full.compatible)
        self.assertEqual(full.score, 100)
        self.assertEqual(partial.missing, (ProviderCapability.REASONING,))
        self.assertEqual(partial.score, 50)

    def test_compatibility_validator_filters_disabled_and_excluded(self) -> None:
        validator = CompatibilityValidator()
        request = _request()
        disabled = validator.validate(
            _provider(
                "disabled",
                enabled=False,
                status=ProviderStatus.DISABLED,
            ),
            request,
            RoutingPolicy(),
        )
        excluded = validator.validate(
            _provider("excluded"),
            request,
            RoutingPolicy(excluded_provider_ids=("excluded",)),
        )
        self.assertFalse(disabled.compatible)
        self.assertIn("provider is disabled", disabled.reasons)
        self.assertFalse(excluded.compatible)
        self.assertIn("provider is excluded by routing policy", excluded.reasons)

    def test_compatibility_validator_applies_health_policy(self) -> None:
        validator = CompatibilityValidator()
        request = _request()
        degraded = _provider("degraded", status=ProviderStatus.DEGRADED)
        unknown = _provider("unknown", status=ProviderStatus.UNKNOWN)

        self.assertTrue(
            validator.validate(degraded, request, RoutingPolicy()).compatible
        )
        self.assertFalse(
            validator.validate(
                degraded,
                request,
                RoutingPolicy(allow_degraded=False),
            ).compatible
        )
        self.assertFalse(
            validator.validate(unknown, request, RoutingPolicy()).compatible
        )
        self.assertTrue(
            validator.validate(
                unknown,
                request,
                RoutingPolicy(allow_unknown=True),
            ).compatible
        )

    def test_compatibility_validator_checks_model_hint(self) -> None:
        validator = CompatibilityValidator()
        provider = _provider("provider-a", models=("model-a",))
        mismatch = validator.validate(
            provider,
            _request(model="model-b"),
            RoutingPolicy(),
        )
        ignored = validator.validate(
            provider,
            _request(model="model-b"),
            RoutingPolicy(require_model_match=False),
        )
        self.assertFalse(mismatch.compatible)
        self.assertIn("requested model is not supported", mismatch.reasons)
        self.assertTrue(ignored.compatible)

    def test_compatibility_validator_rejects_naive_clock(self) -> None:
        validator = CompatibilityValidator(clock=lambda: datetime(2026, 7, 15))
        with self.assertRaises(ProviderCompatibilityError):
            validator.validate(_provider("provider-a"), _request(), RoutingPolicy())


class ScoringAndFallbackTests(unittest.TestCase):
    """Verify deterministic scoring components and fallback chain planning."""

    def test_default_scoring_has_reproducible_component_total(self) -> None:
        score = ProviderScorer().score(
            _provider("provider-a"),
            _request(),
            RoutingPolicy(),
        )
        self.assertEqual(score.capability_score, 100)
        self.assertEqual(score.health_score, 100)
        self.assertEqual(score.priority_score, 50)
        self.assertEqual(score.preference_score, 50)
        self.assertEqual(score.model_score, 100)
        self.assertEqual(score.total, 85)

    def test_scoring_rewards_priority_and_explicit_preference(self) -> None:
        provider = _provider("preferred", priority=ProviderPriority.HIGH)
        score = ProviderScorer().score(
            provider,
            _request(preferred="preferred"),
            RoutingPolicy(),
        )
        self.assertEqual(score.priority_score, 75)
        self.assertEqual(score.preference_score, 100)
        self.assertEqual(score.total, 95)

    def test_scoring_reflects_degraded_health(self) -> None:
        score = ProviderScorer().score(
            _provider("degraded", status=ProviderStatus.DEGRADED),
            _request(),
            RoutingPolicy(),
        )
        self.assertEqual(score.health_score, 60)
        self.assertEqual(score.total, 75)

    def test_scoring_accepts_custom_normalized_weights(self) -> None:
        weights = ScoringWeights(
            capability=1.0,
            health=0.0,
            priority=0.0,
            preference=0.0,
            model=0.0,
        )
        score = ProviderScorer(weights).score(
            _provider("provider-a"),
            _request(),
            RoutingPolicy(),
        )
        self.assertEqual(score.total, 100)

    def test_scoring_rejects_mismatched_compatibility_report(self) -> None:
        provider = _provider("provider-a")
        other_report = CompatibilityValidator().validate(
            _provider("provider-b"),
            _request(),
            RoutingPolicy(),
        )
        with self.assertRaises(ProviderScoringError):
            ProviderScorer().score(
                provider,
                _request(),
                RoutingPolicy(),
                other_report,
            )

    def test_fallback_planner_preserves_rank_and_policy_limit(self) -> None:
        plan = FallbackPlanner().plan(
            "request-001",
            (
                _score("primary", total=90),
                _score("fallback-a", total=80),
                _score("fallback-b", total=70),
            ),
            "primary",
            RoutingPolicy(max_fallbacks=1),
        )
        self.assertEqual(plan.provider_ids, ("fallback-a",))
        self.assertEqual(FallbackPlanner.next_provider_id(plan), "fallback-a")

    def test_fallback_planner_excludes_incompatible_and_low_scores(self) -> None:
        plan = FallbackPlanner().plan(
            "request-001",
            (
                _score("primary", total=90),
                _score("incompatible", total=90, compatible=False),
                _score("low", total=50),
                _score("usable", total=75),
            ),
            "primary",
            RoutingPolicy(minimum_score=70),
        )
        self.assertEqual(plan.provider_ids, ("usable",))

    def test_fallback_planner_reports_exhaustion_and_invalid_binding(self) -> None:
        plan = FallbackPlanner().plan(
            "request-001",
            (_score("primary"),),
            "primary",
            RoutingPolicy(),
        )
        with self.assertRaises(FallbackUnavailableError):
            FallbackPlanner.next_provider_id(plan)
        with self.assertRaises(ValueError):
            FallbackPlanner().plan(
                "request-001",
                (_score("primary", request_id="other"),),
                "primary",
                RoutingPolicy(),
            )


class RequestRouterTests(unittest.TestCase):
    """Verify routing, ranking policies, explanations, failures, and events."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        for name in (
            "ai.request_routed",
            "ai.provider_scored",
            "ai.provider_fallback",
            "ai.validation_failed",
        ):
            self.bus.subscribe(name, self.events.append)
        self.router = RequestRouter(
            event_bus=self.bus,
            logger=self.logger,
            clock=self.clock,
            id_factory=lambda: "routing-001",
        )

    def test_balanced_routing_is_deterministic_and_order_independent(self) -> None:
        alpha = _provider("alpha", priority=ProviderPriority.HIGH)
        beta = _provider("beta", priority=ProviderPriority.HIGH)
        first = self.router.route(_request(), (beta, alpha))
        second = self.router.route(_request(), (alpha, beta))

        self.assertEqual(first.selected_provider_id, "alpha")
        self.assertEqual(second.selected_provider_id, "alpha")
        self.assertEqual(first.decision_id, "routing-001")
        self.assertEqual(first.explanation.selected_provider_id, "alpha")
        with self.assertRaises(FrozenInstanceError):
            first.selected_provider = beta  # type: ignore[misc]

    def test_priority_policy_ranks_priority_before_score(self) -> None:
        decision = self.router.route(
            _request(),
            (
                _provider("healthy-low", priority=ProviderPriority.LOW),
                _provider(
                    "degraded-high",
                    priority=ProviderPriority.HIGHEST,
                    status=ProviderStatus.DEGRADED,
                ),
            ),
            RoutingPolicy(selection=SelectionPolicy.PRIORITY),
        )
        self.assertEqual(decision.selected_provider_id, "degraded-high")

    def test_health_policy_ranks_availability_before_score(self) -> None:
        decision = self.router.route(
            _request(),
            (
                _provider("healthy-low", priority=ProviderPriority.LOW),
                _provider(
                    "degraded-high",
                    priority=ProviderPriority.HIGHEST,
                    status=ProviderStatus.DEGRADED,
                ),
            ),
            RoutingPolicy(selection=SelectionPolicy.HEALTH),
        )
        self.assertEqual(decision.selected_provider_id, "healthy-low")

    def test_preferred_policy_honors_compatible_preference(self) -> None:
        decision = self.router.route(
            _request(preferred="preferred"),
            (
                _provider("high", priority=ProviderPriority.HIGHEST),
                _provider("preferred", priority=ProviderPriority.LOWEST),
            ),
            RoutingPolicy(selection=SelectionPolicy.PREFERRED),
        )
        self.assertEqual(decision.selected_provider_id, "preferred")

    def test_capability_policy_prefers_broader_compatible_provider(self) -> None:
        decision = self.router.route(
            _request(),
            (
                _provider(
                    "narrow-high",
                    priority=ProviderPriority.HIGHEST,
                    capabilities=(ProviderCapability.CHAT,),
                ),
                _provider(
                    "broad-low",
                    priority=ProviderPriority.LOWEST,
                    capabilities=(
                        ProviderCapability.CHAT,
                        ProviderCapability.REASONING,
                        ProviderCapability.STRUCTURED_OUTPUT,
                    ),
                ),
            ),
            RoutingPolicy(selection=SelectionPolicy.CAPABILITY),
        )
        self.assertEqual(decision.selected_provider_id, "broad-low")

    def test_routing_filters_health_capability_model_and_exclusions(self) -> None:
        request = _request(
            capabilities=(ProviderCapability.REASONING,),
            model="model-a",
        )
        decision = self.router.route(
            request,
            (
                _provider("missing-capability"),
                _provider(
                    "offline",
                    capabilities=(ProviderCapability.REASONING,),
                    status=ProviderStatus.UNAVAILABLE,
                ),
                _provider(
                    "wrong-model",
                    capabilities=(ProviderCapability.REASONING,),
                    models=("model-b",),
                ),
                _provider(
                    "eligible",
                    capabilities=(ProviderCapability.REASONING,),
                ),
            ),
        )
        self.assertEqual(decision.selected_provider_id, "eligible")
        self.assertEqual(
            sum(report.compatible for report in decision.compatibility_reports),
            1,
        )
        self.assertEqual(decision.fallback_chain, ())

    def test_routing_builds_ordered_bounded_fallback_chain(self) -> None:
        decision = self.router.route(
            _request(),
            (
                _provider("primary", priority=ProviderPriority.HIGHEST),
                _provider("fallback-a", priority=ProviderPriority.HIGH),
                _provider("fallback-b", priority=ProviderPriority.NORMAL),
            ),
            RoutingPolicy(max_fallbacks=1),
        )
        self.assertEqual(decision.selected_provider_id, "primary")
        self.assertEqual(decision.fallback_chain, ("fallback-a",))
        self.assertIn("fallback chain: fallback-a", decision.explanation.factors)

    def test_router_returns_and_advances_fallbacks(self) -> None:
        providers = (
            _provider("primary", priority=ProviderPriority.HIGHEST),
            _provider("fallback-a", priority=ProviderPriority.HIGH),
            _provider("fallback-b", priority=ProviderPriority.NORMAL),
        )
        decision = self.router.route(_request(), providers)
        first = self.router.fallback(decision, providers)
        second = self.router.fallback(decision, providers, "fallback-a")

        self.assertEqual(first.provider_id, "fallback-a")
        self.assertEqual(second.provider_id, "fallback-b")
        self.assertEqual(self.events[-1].name, "ai.provider_fallback")
        with self.assertRaises(FallbackUnavailableError):
            self.router.fallback(decision, providers, "fallback-b")

    def test_fallback_skips_provider_that_became_unavailable(self) -> None:
        providers = (
            _provider("primary", priority=ProviderPriority.HIGHEST),
            _provider("fallback-a", priority=ProviderPriority.HIGH),
            _provider("fallback-b", priority=ProviderPriority.NORMAL),
        )
        decision = self.router.route(_request(), providers)
        unavailable = replace(
            providers[1],
            health=ProviderHealth(
                "fallback-a",
                ProviderStatus.UNAVAILABLE,
                checked_at=self.clock.now,
            ),
        )
        selected = self.router.fallback(
            decision,
            (providers[0], unavailable, providers[2]),
        )
        self.assertEqual(selected.provider_id, "fallback-b")

    def test_router_score_validate_and_summary_helpers(self) -> None:
        provider = _provider("provider-a")
        request = _request()
        report = self.router.validate_provider(provider, request)
        score = self.router.score_provider(provider, request)
        decision = self.router.route(request, (provider,))
        summary = self.router.summary(decision)

        self.assertTrue(report.compatible)
        self.assertEqual(score.provider_id, provider.provider_id)
        self.assertEqual(summary.selected_provider_id, provider.provider_id)
        self.assertEqual(summary.candidate_count, 1)
        self.assertEqual(summary.compatible_count, 1)

    def test_router_publishes_required_safe_events_and_logs(self) -> None:
        request = AIRequest(
            prompt="sensitive prompt",
            required_capabilities=(ProviderCapability.CHAT,),
            metadata={"api_key": "must-not-leak"},
            request_id="request-sensitive",
        )
        self.router.route(request, (_provider("provider-a"),))

        names = [event.name for event in self.events]
        self.assertIn("ai.provider_scored", names)
        self.assertIn("ai.request_routed", names)
        self.assertNotIn("sensitive prompt", repr(self.events))
        self.assertNotIn("api_key", repr(self.events))
        self.assertNotIn("must-not-leak", repr(self.logger.entries))

    def test_router_publishes_validation_failures(self) -> None:
        report = self.router.validate_provider(
            _provider("offline", status=ProviderStatus.UNAVAILABLE),
            _request(),
        )
        self.assertFalse(report.compatible)
        self.assertEqual(self.events[-1].name, "ai.validation_failed")
        self.assertEqual(self.events[-1].payload["provider_id"], "offline")

    def test_router_rejects_invalid_requests_empty_registry_and_minimum_score(
        self,
    ) -> None:
        with self.assertRaises(RequestValidationError):
            self.router.route(
                _request(prompt="too long"),
                (_provider("provider-a"),),
                RoutingPolicy(maximum_prompt_characters=3),
            )
        self.assertEqual(self.events[-1].name, "ai.validation_failed")
        with self.assertRaises(NoCompatibleProviderError):
            self.router.route(_request(), ())
        with self.assertRaises(NoCompatibleProviderError):
            self.router.route(
                _request(),
                (_provider("provider-a"),),
                RoutingPolicy(minimum_score=99),
            )

    def test_observer_and_logger_failures_do_not_change_routing(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "ai.provider_scored",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        logger = _CapturingLogger()
        router = RequestRouter(event_bus=bus, logger=logger)
        decision = router.route(_request(), (_provider("provider-a"),))
        self.assertEqual(decision.selected_provider_id, "provider-a")
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in logger.entries)
        )
        quiet = RequestRouter(logger=_CapturingLogger(fail=True))
        self.assertEqual(
            quiet.route(_request(), (_provider("provider-a"),)).selected_provider_id,
            "provider-a",
        )

    def test_router_validates_dependencies_and_exposes_no_execution(self) -> None:
        with self.assertRaises(TypeError):
            RequestRouter(scorer=object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            RequestRouter(fallback_planner=object())  # type: ignore[arg-type]
        for value in (
            self.router,
            self.router.matcher,
            self.router.validator,
            self.router.scorer,
            self.router.fallback_planner,
        ):
            for method in ("execute", "generate", "complete", "invoke", "run"):
                self.assertFalse(hasattr(value, method))


class RoutingManagerTests(unittest.TestCase):
    """Verify AI Manager routing delegation and compatibility with Sprint 1."""

    def setUp(self) -> None:
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        for name in (
            "ai.request_routed",
            "ai.provider_scored",
            "ai.provider_fallback",
            "ai.validation_failed",
        ):
            self.bus.subscribe(name, self.events.append)
        self.manager = AIManager(event_bus=self.bus)
        self.primary = self.manager.register_provider(
            _provider("primary", priority=ProviderPriority.HIGHEST)
        )
        self.fallback = self.manager.register_provider(
            _provider("fallback", priority=ProviderPriority.NORMAL)
        )

    def test_manager_exposes_complete_routing_lifecycle(self) -> None:
        request = _request()
        decision = self.manager.route_request(request)
        score = self.manager.score_provider("primary", request)
        validation = self.manager.validate_provider(self.primary, request)
        fallback = self.manager.fallback_provider(decision)
        summary = self.manager.routing_summary(decision)

        self.assertEqual(decision.selected_provider_id, "primary")
        self.assertEqual(score.provider_id, "primary")
        self.assertTrue(validation.compatible)
        self.assertEqual(fallback.provider_id, "fallback")
        self.assertEqual(summary.selected_provider_id, "primary")

    def test_manager_routing_uses_thread_safe_registry_snapshot(self) -> None:
        decision = self.manager.route_request(_request())
        self.manager.unregister_provider("fallback")
        with self.assertRaises(FallbackUnavailableError):
            self.manager.fallback_provider(decision)

    def test_manager_score_and_validation_require_registered_provider(self) -> None:
        with self.assertRaises(ProviderNotFoundError):
            self.manager.score_provider("missing", _request())
        with self.assertRaises(ProviderNotFoundError):
            self.manager.validate_provider(_provider("missing"), _request())

    def test_manager_accepts_injected_router(self) -> None:
        router = RequestRouter()
        manager = AIManager(request_router=router)
        self.assertIs(manager.request_router, router)
        with self.assertRaises(TypeError):
            AIManager(request_router=object())  # type: ignore[arg-type]

    def test_sprint_one_selection_remains_available(self) -> None:
        selected = self.manager.select_provider(_request())
        self.assertEqual(selected.provider_id, "primary")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
