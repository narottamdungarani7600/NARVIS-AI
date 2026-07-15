"""Comprehensive tests for Phase 13 AI Orchestrator Sprint 3."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from threading import Lock
import unittest

from AI import (
    AIManager,
    AIProvider,
    AIRequest,
    CapabilityNegotiation,
    CapabilityNegotiator,
    ContextSizeMetadata,
    CostMetadata,
    DuplicatePlanError,
    LatencyMetadata,
    ModelOption,
    ModelPreferencePolicy,
    ModelPreferenceResolver,
    OrchestrationEvents,
    OrchestrationLifecycleManager,
    OrchestrationPlanStatus,
    OrchestrationPlanStep,
    OrchestrationPlanner,
    OrchestrationSessionStatus,
    OrchestrationSessionStore,
    OrchestrationStepType,
    PreferenceResolutionError,
    ProviderCapability,
    ProviderHealth,
    ProviderMetadata,
    ProviderModelCatalog,
    ProviderNegotiationError,
    ProviderNegotiator,
    ProviderPriority,
    ProviderStatus,
    RequestRouter,
    RoutingPolicy,
    SessionAlreadyExistsError,
    SessionExpiredError,
    SessionInactiveError,
    SessionNotFoundError,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _Clock:
    """Mutable aware clock for deterministic orchestration tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _Ids:
    """Thread-safe deterministic identifier factory."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.count = 0
        self.lock = Lock()

    def __call__(self) -> str:
        with self.lock:
            self.count += 1
            return f"{self.prefix}-{self.count:03d}"


class _CapturingLogger:
    """Core-compatible structured logger double."""

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []
        self.fail = fail

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        if self.fail:
            raise RuntimeError("logger unavailable")
        self.entries.append((level, message, context))


def _option(
    provider_id: str,
    model: str | None = "model-a",
    *,
    cost: float | None = 0.02,
    latency: float | None = 100,
    context: int | None = 16_000,
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    currency: str = "USD",
) -> ModelOption:
    return ModelOption(
        provider_id=provider_id,
        model_name=model,
        capabilities=capabilities,
        cost=CostMetadata(
            currency=currency,
            estimated_request_cost=cost,
            input_cost_per_1000_tokens=None if cost is None else cost / 10,
            output_cost_per_1000_tokens=None if cost is None else cost / 5,
        ),
        latency=LatencyMetadata(estimated_latency_ms=latency),
        context_size=ContextSizeMetadata(
            max_context_tokens=context,
            max_output_tokens=None if context is None else min(2_000, context),
        ),
        metadata={"declared": {"source": ["test"]}},
    )


def _provider(
    name: str,
    *,
    priority: ProviderPriority = ProviderPriority.NORMAL,
    status: ProviderStatus = ProviderStatus.AVAILABLE,
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    options: tuple[ModelOption, ...] | None = None,
    models: tuple[str, ...] = ("model-a",),
    enabled: bool = True,
) -> AIProvider:
    now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)
    resolved_options = options or (
        _option(name, models[0] if models else None, capabilities=capabilities),
    )
    return AIProvider(
        metadata=ProviderMetadata(
            name=name,
            capabilities=capabilities,
            priority=priority,
            supported_models=models,
            enabled=enabled,
            attributes={"model_options": resolved_options},
        ),
        health=ProviderHealth(name, status, checked_at=now),
        registered_at=now,
    )


def _request(
    request_id: str = "request-001",
    *,
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    model: str | None = None,
    prompt: str = "Coordinate this request",
) -> AIRequest:
    return AIRequest(
        prompt=prompt,
        required_capabilities=capabilities,
        model_hint=model,
        request_id=request_id,
        created_at=datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc),
    )


def _components(
    clock: _Clock,
    *,
    bus: EventBus | None = None,
    logger: _CapturingLogger | None = None,
) -> tuple[
    OrchestrationEvents,
    RequestRouter,
    ModelPreferenceResolver,
    ProviderNegotiator,
    OrchestrationPlanner,
    OrchestrationLifecycleManager,
]:
    events = OrchestrationEvents(bus, logger=logger)
    router = RequestRouter(
        event_bus=bus,
        logger=logger,
        clock=clock,
        id_factory=_Ids("routing"),
    )
    preferences = ModelPreferenceResolver(
        events=events,
        logger=logger,
        clock=clock,
    )
    capabilities = CapabilityNegotiator(clock=clock)
    negotiator = ProviderNegotiator(
        router,
        preferences,
        capabilities,
        events,
        logger=logger,
        clock=clock,
        id_factory=_Ids("negotiation"),
    )
    planner = OrchestrationPlanner(
        negotiator,
        events,
        logger=logger,
        clock=clock,
        id_factory=_Ids("plan"),
    )
    lifecycle = OrchestrationLifecycleManager(
        events=events,
        logger=logger,
        clock=clock,
        id_factory=_Ids("session"),
    )
    return events, router, preferences, negotiator, planner, lifecycle


class OrchestrationModelTests(unittest.TestCase):
    """Verify immutable cost, latency, context, plan, and session models."""

    def test_cost_metadata_is_immutable_and_validated(self) -> None:
        cost = CostMetadata(
            estimated_request_cost=0.05,
            input_cost_per_1000_tokens=0.001,
        )
        self.assertTrue(cost.known)
        with self.assertRaises(FrozenInstanceError):
            cost.currency = "EUR"  # type: ignore[misc]
        with self.assertRaises(ValueError):
            CostMetadata(currency="usd")
        with self.assertRaises(ValueError):
            CostMetadata(estimated_request_cost=-1)

    def test_latency_metadata_validates_estimate_and_p95(self) -> None:
        latency = LatencyMetadata(estimated_latency_ms=100, p95_latency_ms=180)
        self.assertTrue(latency.known)
        self.assertEqual(latency.estimated_latency_ms, 100.0)
        with self.assertRaises(ValueError):
            LatencyMetadata(estimated_latency_ms=200, p95_latency_ms=100)

    def test_context_metadata_validates_output_bound(self) -> None:
        context = ContextSizeMetadata(
            max_context_tokens=16_000,
            max_output_tokens=2_000,
        )
        self.assertTrue(context.known)
        with self.assertRaises(ValueError):
            ContextSizeMetadata(max_context_tokens=1_000, max_output_tokens=2_000)

    def test_model_option_is_deeply_immutable(self) -> None:
        option = _option("provider-a")
        self.assertEqual(option.option_id, "provider-a:model-a")
        self.assertEqual(option.metadata["declared"]["source"], ("test",))
        with self.assertRaises(TypeError):
            option.metadata["new"] = True  # type: ignore[index]
        with self.assertRaises(TypeError):
            replace(option, capabilities=("chat",))  # type: ignore[arg-type]

    def test_model_preference_policy_is_immutable_and_consistent(self) -> None:
        policy = ModelPreferencePolicy(
            preferred_models=("model-a", "model-b"),
            excluded_models=("model-c",),
            maximum_estimated_cost=0.1,
            minimum_context_tokens=8_000,
            metadata={"nested": [1]},
        )
        self.assertEqual(policy.metadata["nested"], (1,))
        with self.assertRaises(ValueError):
            ModelPreferencePolicy(
                preferred_models=("same",),
                excluded_models=("same",),
            )
        with self.assertRaises(ValueError):
            ModelPreferencePolicy(
                required_model="model-a", excluded_models=("model-a",)
            )

    def test_capability_negotiation_enforces_exact_partition(self) -> None:
        negotiation = CapabilityNegotiation(
            request_id="request-001",
            provider_id="provider-a",
            required=(ProviderCapability.CHAT, ProviderCapability.REASONING),
            matched=(ProviderCapability.CHAT,),
            missing=(ProviderCapability.REASONING,),
            successful=False,
        )
        self.assertFalse(negotiation.successful)
        with self.assertRaises(ValueError):
            replace(negotiation, successful=True)

    def test_plan_steps_cannot_claim_execution(self) -> None:
        step = OrchestrationPlanStep(
            order=1,
            step_type=OrchestrationStepType.PREPARE_PLAN,
            description="Prepare only",
        )
        self.assertTrue(step.planned)
        self.assertFalse(step.executed)
        with self.assertRaises(ValueError):
            replace(step, executed=True)

    def test_generated_plan_is_frozen_non_executable_and_bound(self) -> None:
        clock = _Clock()
        _, _, _, _, planner, lifecycle = _components(clock)
        session = lifecycle.create_session("owner", session_id="session-001")
        plan = planner.plan(session, _request(), (_provider("provider-a"),))

        self.assertEqual(plan.status, OrchestrationPlanStatus.READY)
        self.assertTrue(plan.architecture_only)
        self.assertFalse(plan.executable)
        self.assertFalse(plan.executed)
        self.assertEqual(
            tuple(step.order for step in plan.steps),
            (1, 2, 3, 4, 5),
        )
        with self.assertRaises(FrozenInstanceError):
            plan.executed = True  # type: ignore[misc]
        with self.assertRaises(ValueError):
            replace(plan, executable=True)

    def test_session_history_invariants_are_immutable(self) -> None:
        clock = _Clock()
        _, _, _, _, planner, lifecycle = _components(clock)
        session = lifecycle.create_session("owner", session_id="session-001")
        plan = planner.plan(session, _request(), (_provider("provider-a"),))
        updated = lifecycle.record_plan(session.session_id, plan)

        self.assertEqual(updated.request_ids, ("request-001",))
        self.assertEqual(updated.plan_ids, (plan.plan_id,))
        self.assertEqual(updated.selection_history[0].provider_id, "provider-a")
        with self.assertRaises(FrozenInstanceError):
            updated.status = OrchestrationSessionStatus.COMPLETED  # type: ignore[misc]
        with self.assertRaises(ValueError):
            replace(updated, plan_ids=())

    def test_empty_orchestration_summary_is_structured(self) -> None:
        clock = _Clock()
        *_, lifecycle = _components(clock)
        session = lifecycle.create_session("owner", session_id="session-001")
        summary = lifecycle.summary(session.session_id)

        self.assertEqual(summary.request_count, 0)
        self.assertEqual(dict(summary.provider_selection_counts), {})
        self.assertIsNone(summary.total_estimated_cost)
        self.assertTrue(summary.architecture_only)


class PreferenceResolutionTests(unittest.TestCase):
    """Verify model catalogs and cost/latency/context preference policies."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        self.bus.subscribe("ai.preferences_resolved", self.events.append)
        self.orchestration_events = OrchestrationEvents(
            self.bus,
            logger=self.logger,
        )
        self.resolver = ModelPreferenceResolver(
            events=self.orchestration_events,
            logger=self.logger,
            clock=self.clock,
        )

    def test_catalog_uses_declared_typed_model_options(self) -> None:
        options = (
            _option("provider-a", "model-a"),
            _option("provider-a", "model-b", cost=0.01),
        )
        provider = _provider(
            "provider-a",
            options=options,
            models=("model-a", "model-b"),
        )
        self.assertEqual(ProviderModelCatalog().options_for(provider), options)

    def test_catalog_builds_options_from_provider_level_metadata(self) -> None:
        now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)
        provider = AIProvider(
            ProviderMetadata(
                name="provider-a",
                capabilities=(ProviderCapability.CHAT,),
                supported_models=("model-a", "model-b"),
                attributes={
                    "cost_metadata": CostMetadata(estimated_request_cost=0.03),
                    "latency_metadata": LatencyMetadata(estimated_latency_ms=90),
                    "context_size_metadata": ContextSizeMetadata(
                        max_context_tokens=8_000
                    ),
                },
            ),
            registered_at=now,
        )
        options = ProviderModelCatalog().options_for(provider)
        self.assertEqual(
            tuple(item.model_name for item in options), ("model-a", "model-b")
        )
        self.assertEqual(options[0].cost.estimated_request_cost, 0.03)

    def test_catalog_rejects_cross_provider_and_duplicate_options(self) -> None:
        cross_provider = _provider(
            "provider-a",
            options=(_option("provider-b"),),
        )
        with self.assertRaises(ValueError):
            ProviderModelCatalog().options_for(cross_provider)
        provider = _provider(
            "provider-a",
            options=(_option("provider-a"), _option("provider-a")),
        )
        with self.assertRaises(ValueError):
            ProviderModelCatalog().options_for(provider)

    def test_preferred_model_order_is_resolved_deterministically(self) -> None:
        resolution = self.resolver.resolve(
            _request(),
            (
                _option("provider-a", "model-a"),
                _option("provider-a", "model-b"),
            ),
            ModelPreferencePolicy(preferred_models=("model-b", "model-a")),
        )
        self.assertEqual(resolution.model_name, "model-b")
        self.assertEqual(resolution.provider_id, "provider-a")

    def test_lower_cost_preference_selects_declared_cheapest_option(self) -> None:
        resolution = self.resolver.resolve(
            _request(),
            (
                _option("expensive", cost=0.10),
                _option("cheap", cost=0.01),
            ),
            ModelPreferencePolicy(prefer_lower_cost=True),
        )
        self.assertEqual(resolution.provider_id, "cheap")

    def test_latency_and_context_preferences_are_deterministic(self) -> None:
        options = (
            _option("fast", latency=50, context=8_000),
            _option("large", latency=100, context=64_000),
        )
        fast = self.resolver.resolve(
            _request(),
            options,
            ModelPreferencePolicy(prefer_lower_latency=True),
        )
        large = self.resolver.resolve(
            _request(),
            options,
            ModelPreferencePolicy(prefer_larger_context=True),
        )
        self.assertEqual(fast.provider_id, "fast")
        self.assertEqual(large.provider_id, "large")

    def test_hard_cost_latency_and_context_constraints_reject_options(self) -> None:
        with self.assertRaises(PreferenceResolutionError):
            self.resolver.resolve(
                _request(),
                (_option("provider-a", cost=1.0, latency=500, context=2_000),),
                ModelPreferencePolicy(
                    maximum_estimated_cost=0.5,
                    maximum_latency_ms=100,
                    minimum_context_tokens=8_000,
                ),
            )

    def test_unknown_metadata_policies_are_enforced(self) -> None:
        unknown = _option("provider-a", cost=None, latency=None, context=None)
        with self.assertRaises(PreferenceResolutionError):
            self.resolver.resolve(
                _request(),
                (unknown,),
                ModelPreferencePolicy(
                    allow_unknown_cost=False,
                    allow_unknown_latency=False,
                    allow_unknown_context=False,
                ),
            )

    def test_request_model_hint_and_exclusions_are_enforced(self) -> None:
        options = (
            _option("provider-a", "model-a"),
            _option("provider-a", "model-b"),
        )
        resolution = self.resolver.resolve(_request(model="model-b"), options)
        self.assertEqual(resolution.model_name, "model-b")
        with self.assertRaises(PreferenceResolutionError):
            self.resolver.resolve(
                _request(model="model-b"),
                options,
                ModelPreferencePolicy(excluded_models=("model-b",)),
            )

    def test_preference_event_and_log_do_not_expose_request_content(self) -> None:
        request = AIRequest(
            prompt="sensitive prompt",
            metadata={"api_key": "must-not-leak"},
            request_id="request-sensitive",
        )
        self.resolver.resolve(request, (_option("provider-a"),))
        self.assertEqual(self.events[-1].name, "ai.preferences_resolved")
        self.assertNotIn("sensitive prompt", repr(self.events))
        self.assertNotIn("api_key", repr(self.events))
        self.assertNotIn("must-not-leak", repr(self.logger.entries))


class NegotiationAndPlannerTests(unittest.TestCase):
    """Verify provider/capability negotiation and architecture-only planning."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        for name in (
            "ai.provider_negotiated",
            "ai.preferences_resolved",
            "ai.plan_generated",
        ):
            self.bus.subscribe(name, self.events.append)
        (
            self.orchestration_events,
            self.router,
            self.preferences,
            self.negotiator,
            self.planner,
            self.lifecycle,
        ) = _components(self.clock, bus=self.bus)

    def test_capability_negotiator_combines_request_and_routing_requirements(
        self,
    ) -> None:
        result = CapabilityNegotiator(clock=self.clock).negotiate(
            _request(capabilities=(ProviderCapability.CHAT,)),
            _provider(
                "provider-a",
                capabilities=(
                    ProviderCapability.CHAT,
                    ProviderCapability.REASONING,
                ),
                options=(
                    _option(
                        "provider-a",
                        capabilities=(
                            ProviderCapability.CHAT,
                            ProviderCapability.REASONING,
                        ),
                    ),
                ),
            ),
            RoutingPolicy(required_capabilities=(ProviderCapability.REASONING,)),
            _option(
                "provider-a",
                capabilities=(
                    ProviderCapability.CHAT,
                    ProviderCapability.REASONING,
                ),
            ),
        )
        self.assertTrue(result.successful)
        self.assertEqual(
            result.required,
            (ProviderCapability.CHAT, ProviderCapability.REASONING),
        )

    def test_provider_negotiation_uses_routing_order_by_default(self) -> None:
        negotiation = self.negotiator.negotiate(
            _request(),
            (
                _provider("low", priority=ProviderPriority.LOW),
                _provider("high", priority=ProviderPriority.HIGH),
            ),
        )
        self.assertEqual(negotiation.provider_id, "high")
        self.assertEqual(negotiation.routing_decision.selected_provider_id, "high")
        self.assertTrue(negotiation.capability_negotiation.successful)

    def test_cost_preference_can_negotiate_different_routing_provider(self) -> None:
        high = _provider(
            "high",
            priority=ProviderPriority.HIGH,
            options=(_option("high", cost=0.20),),
        )
        cheap = _provider(
            "cheap",
            priority=ProviderPriority.NORMAL,
            options=(_option("cheap", cost=0.01),),
        )
        negotiation = self.negotiator.negotiate(
            _request(),
            (high, cheap),
            preference_policy=ModelPreferencePolicy(prefer_lower_cost=True),
        )
        self.assertEqual(negotiation.routing_decision.selected_provider_id, "high")
        self.assertEqual(negotiation.provider_id, "cheap")
        self.assertEqual(negotiation.cost.estimated_request_cost, 0.01)

    def test_negotiation_publishes_safe_event(self) -> None:
        negotiation = self.negotiator.negotiate(
            _request(),
            (_provider("provider-a"),),
        )
        event = next(
            item for item in self.events if item.name == "ai.provider_negotiated"
        )
        self.assertEqual(event.payload["provider_id"], negotiation.provider_id)
        self.assertEqual(event.payload["capabilities"], ("chat",))

    def test_model_level_capability_failure_is_typed(self) -> None:
        provider = _provider(
            "provider-a",
            capabilities=(ProviderCapability.CHAT, ProviderCapability.REASONING),
            options=(
                _option(
                    "provider-a",
                    capabilities=(ProviderCapability.CHAT,),
                ),
            ),
        )
        with self.assertRaises(PreferenceResolutionError):
            self.negotiator.negotiate(
                _request(
                    capabilities=(
                        ProviderCapability.CHAT,
                        ProviderCapability.REASONING,
                    )
                ),
                (provider,),
            )

    def test_planner_generates_required_ordered_steps_and_event(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        plan = self.planner.plan(
            session,
            _request(),
            (_provider("provider-a"),),
        )
        self.assertEqual(
            tuple(step.step_type for step in plan.steps),
            (
                OrchestrationStepType.VALIDATE_REQUEST,
                OrchestrationStepType.ROUTE_PROVIDER,
                OrchestrationStepType.RESOLVE_PREFERENCES,
                OrchestrationStepType.NEGOTIATE_PROVIDER,
                OrchestrationStepType.PREPARE_PLAN,
            ),
        )
        self.assertEqual(self.events[-1].name, "ai.plan_generated")
        self.assertFalse(self.events[-1].payload["executable"])

    def test_planner_rejects_inactive_or_expired_session(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        completed = self.lifecycle.complete_session(session.session_id)
        with self.assertRaises(SessionInactiveError):
            self.planner.plan(
                completed,
                _request(),
                (_provider("provider-a"),),
            )

    def test_negotiation_and_planner_validate_dependencies(self) -> None:
        with self.assertRaises(TypeError):
            ProviderNegotiator(object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            OrchestrationPlanner(object())  # type: ignore[arg-type]

    def test_orchestration_services_expose_no_execution_or_inference(self) -> None:
        plan_session = self.lifecycle.create_session(
            "owner",
            session_id="session-no-execution",
        )
        plan = self.planner.plan(
            plan_session,
            _request("request-no-execution"),
            (_provider("provider-a"),),
        )
        for value in (self.negotiator, self.planner, plan):
            for method in (
                "execute",
                "invoke",
                "infer",
                "run_model",
                "send_request",
            ):
                self.assertFalse(hasattr(value, method))


class OrchestrationLifecycleTests(unittest.TestCase):
    """Verify thread-safe sessions, history, expiration, completion, and summaries."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        self.bus.subscribe("ai.session_created", self.events.append)
        self.bus.subscribe("ai.session_completed", self.events.append)
        (
            self.orchestration_events,
            self.router,
            self.preferences,
            self.negotiator,
            self.planner,
            self.lifecycle,
        ) = _components(self.clock, bus=self.bus, logger=self.logger)

    def test_session_store_add_get_replace_list_and_clear(self) -> None:
        store = OrchestrationSessionStore()
        session = self.lifecycle.create_session("owner", session_id="session-001")
        store.add(session)
        self.assertIs(store.get(session.session_id), session)
        replaced = replace(session, metadata={"updated": True})
        self.assertIs(store.replace(replaced), replaced)
        self.assertEqual(store.list(), (replaced,))
        self.assertEqual(store.clear(), (replaced,))
        self.assertEqual(len(store), 0)

    def test_session_store_reports_duplicate_and_missing_sessions(self) -> None:
        store = OrchestrationSessionStore()
        session = self.lifecycle.create_session("owner", session_id="session-001")
        store.add(session)
        with self.assertRaises(SessionAlreadyExistsError):
            store.add(session)
        with self.assertRaises(SessionNotFoundError):
            store.get("missing")

    def test_create_session_detaches_metadata_and_publishes_event(self) -> None:
        metadata = {"context": {"references": ["memory-1"]}}
        session = self.lifecycle.create_session(
            "owner",
            session_id="session-001",
            metadata=metadata,
        )
        metadata["context"]["references"].append("memory-2")  # type: ignore[index,union-attr]

        self.assertEqual(session.metadata["context"]["references"], ("memory-1",))
        self.assertEqual(self.events[-1].name, "ai.session_created")
        self.assertEqual(self.events[-1].payload["session_id"], "session-001")

    def test_session_expiration_is_materialized_and_blocks_plans(self) -> None:
        session = self.lifecycle.create_session(
            "owner",
            session_id="session-001",
            ttl=timedelta(minutes=1),
        )
        plan = self.planner.plan(
            session,
            _request(),
            (_provider("provider-a"),),
        )
        self.clock.advance(minutes=2)
        expired = self.lifecycle.get_session(session.session_id)
        self.assertEqual(expired.status, OrchestrationSessionStatus.EXPIRED)
        with self.assertRaises(SessionExpiredError):
            self.lifecycle.record_plan(session.session_id, plan)

    def test_record_plan_appends_provider_selection_history(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        plan = self.planner.plan(
            session,
            _request(),
            (_provider("provider-a"),),
        )
        updated = self.lifecycle.record_plan(session.session_id, plan)
        record = updated.selection_history[0]

        self.assertEqual(record.provider_id, plan.provider_id)
        self.assertEqual(record.model_name, plan.model_name)
        self.assertEqual(record.cost.estimated_request_cost, 0.02)
        self.assertEqual(record.latency.estimated_latency_ms, 100)
        self.assertEqual(record.context_size.max_context_tokens, 16_000)

    def test_record_plan_rejects_duplicate_plan_and_request(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        plan = self.planner.plan(
            session,
            _request(),
            (_provider("provider-a"),),
        )
        self.lifecycle.record_plan(session.session_id, plan)
        with self.assertRaises(DuplicatePlanError):
            self.lifecycle.record_plan(session.session_id, plan)

    def test_complete_session_is_terminal_and_publishes_event(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        completed = self.lifecycle.complete_session(session.session_id)
        self.assertEqual(completed.status, OrchestrationSessionStatus.COMPLETED)
        self.assertEqual(self.events[-1].name, "ai.session_completed")
        self.assertFalse(self.events[-1].payload["executed"])
        with self.assertRaises(SessionInactiveError):
            self.lifecycle.complete_session(session.session_id)

    def test_cancelled_session_is_terminal(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        cancelled = self.lifecycle.cancel_session(session.session_id)
        self.assertEqual(cancelled.status, OrchestrationSessionStatus.CANCELLED)
        with self.assertRaises(SessionInactiveError):
            self.lifecycle.complete_session(session.session_id)

    def test_summary_aggregates_cost_latency_context_and_provider_history(self) -> None:
        session = self.lifecycle.create_session("owner", session_id="session-001")
        provider = _provider("provider-a")
        for index in range(2):
            current = self.lifecycle.get_session(session.session_id)
            plan = self.planner.plan(
                current,
                _request(f"request-{index}"),
                (provider,),
            )
            self.lifecycle.record_plan(session.session_id, plan)
        summary = self.lifecycle.summary(session.session_id)

        self.assertEqual(summary.request_count, 2)
        self.assertEqual(dict(summary.provider_selection_counts), {"provider-a": 2})
        self.assertEqual(summary.total_estimated_cost, 0.04)
        self.assertEqual(summary.cost_currency, "USD")
        self.assertEqual(summary.average_estimated_latency_ms, 100)
        self.assertEqual(summary.maximum_context_tokens, 16_000)
        self.assertEqual(summary.last_provider_id, "provider-a")

    def test_session_creation_is_thread_safe(self) -> None:
        lifecycle = OrchestrationLifecycleManager(clock=self.clock)

        def create(index: int) -> str:
            return lifecycle.create_session(
                "owner",
                session_id=f"session-{index:03d}",
            ).session_id

        with ThreadPoolExecutor(max_workers=8) as pool:
            identifiers = tuple(pool.map(create, range(64)))
        self.assertEqual(len(set(identifiers)), 64)
        self.assertEqual(len(lifecycle.list_sessions()), 64)

    def test_event_observer_failure_does_not_rollback_session_creation(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "ai.session_created",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        logger = _CapturingLogger()
        events = OrchestrationEvents(bus, logger=logger)
        lifecycle = OrchestrationLifecycleManager(
            events=events,
            logger=logger,
            clock=self.clock,
        )
        session = lifecycle.create_session("owner", session_id="session-safe")

        self.assertIs(lifecycle.get_session(session.session_id), session)
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in logger.entries)
        )

    def test_logger_failure_does_not_change_lifecycle_outcomes(self) -> None:
        logger = _CapturingLogger(fail=True)
        lifecycle = OrchestrationLifecycleManager(
            logger=logger,
            clock=self.clock,
        )
        session = lifecycle.create_session("owner", session_id="session-quiet")
        completed = lifecycle.complete_session(session.session_id)
        self.assertEqual(completed.status, OrchestrationSessionStatus.COMPLETED)


class OrchestrationManagerTests(unittest.TestCase):
    """Verify AI Manager orchestration APIs, DI, events, and prior compatibility."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        for name in (
            "ai.session_created",
            "ai.plan_generated",
            "ai.provider_negotiated",
            "ai.preferences_resolved",
            "ai.session_completed",
        ):
            self.bus.subscribe(name, self.events.append)
        (
            orchestration_events,
            router,
            preferences,
            negotiator,
            planner,
            lifecycle,
        ) = _components(self.clock, bus=self.bus)
        self.manager = AIManager(
            event_bus=self.bus,
            request_router=router,
            orchestration_events=orchestration_events,
            preference_resolver=preferences,
            provider_negotiator=negotiator,
            orchestration_planner=planner,
            orchestration_lifecycle=lifecycle,
        )
        self.manager.register_provider(_provider("provider-a"))

    def test_manager_runs_complete_non_executing_orchestration_lifecycle(self) -> None:
        session = self.manager.create_session(
            "owner",
            session_id="session-001",
        )
        plan = self.manager.plan_request(session.session_id, _request())
        summary = self.manager.orchestration_summary(session.session_id)
        completed = self.manager.complete_session(session.session_id)

        self.assertEqual(plan.provider_id, "provider-a")
        self.assertFalse(plan.executable)
        self.assertEqual(summary.plan_count, 1)
        self.assertEqual(completed.status, OrchestrationSessionStatus.COMPLETED)
        names = [event.name for event in self.events]
        for required in (
            "ai.session_created",
            "ai.plan_generated",
            "ai.provider_negotiated",
            "ai.preferences_resolved",
            "ai.session_completed",
        ):
            self.assertIn(required, names)

    def test_manager_negotiates_provider_with_cost_preferences(self) -> None:
        self.manager.register_provider(
            _provider(
                "cheap",
                priority=ProviderPriority.LOW,
                options=(_option("cheap", cost=0.001),),
            )
        )
        negotiation = self.manager.negotiate_provider(
            _request(),
            preference_policy=ModelPreferencePolicy(prefer_lower_cost=True),
        )
        self.assertEqual(negotiation.provider_id, "cheap")

    def test_manager_resolves_preferences_over_selectable_providers(self) -> None:
        self.manager.register_provider(
            _provider(
                "offline-cheap",
                status=ProviderStatus.UNAVAILABLE,
                options=(_option("offline-cheap", cost=0.0),),
            )
        )
        resolution = self.manager.resolve_preferences(
            _request(),
            ModelPreferencePolicy(prefer_lower_cost=True),
        )
        self.assertEqual(resolution.provider_id, "provider-a")

    def test_manager_exposes_injected_orchestration_services(self) -> None:
        self.assertIs(
            self.manager.provider_negotiator.preference_resolver,
            self.manager.preference_resolver,
        )
        self.assertIs(
            self.manager.orchestration_planner.negotiator,
            self.manager.provider_negotiator,
        )
        self.assertIsNotNone(self.manager.orchestration_lifecycle.session_store)
        with self.assertRaises(TypeError):
            AIManager(orchestration_planner=object())  # type: ignore[arg-type]

    def test_sprint_one_and_two_manager_apis_remain_available(self) -> None:
        request = _request()
        self.assertEqual(
            self.manager.select_provider(request).provider_id, "provider-a"
        )
        decision = self.manager.route_request(request)
        self.assertEqual(decision.selected_provider_id, "provider-a")
        self.assertEqual(
            self.manager.routing_summary(decision).selected_provider_id,
            "provider-a",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
