"""Provider-agnostic AI orchestration manager with no execution capability."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, overload
from typing import Any

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .interfaces import (
    EventPublisher,
    ProviderCatalog,
    ProviderDescriptor,
    ProviderSelectionStrategy,
)
from .models import (
    AIProvider,
    AIRequest,
    ProviderCapability,
    ProviderHealth,
    ProviderMetadata,
    ProviderStatus,
)
from .provider import PriorityProviderSelector, ProviderSnapshotFactory
from .registry import ProviderRegistry

if TYPE_CHECKING:
    from AI.orchestrator.events import OrchestrationEvents
    from AI.orchestrator.lifecycle import OrchestrationLifecycleManager
    from AI.orchestrator.models import (
        ModelPreferencePolicy,
        OrchestrationPlan,
        OrchestrationSession,
        OrchestrationSummary,
        PreferenceResolution,
        ProviderNegotiation,
    )
    from AI.orchestrator.negotiation import ProviderNegotiator
    from AI.orchestrator.planner import OrchestrationPlanner
    from AI.orchestrator.preferences import ModelPreferenceResolver
    from AI.routing.models import (
        CompatibilityReport,
        ProviderScore,
        RoutingDecision,
        RoutingPolicy,
        RoutingSummary,
    )
    from AI.routing.router import RequestRouter

AI_PROVIDER_REGISTERED_EVENT = "ai.provider_registered"
AI_PROVIDER_REMOVED_EVENT = "ai.provider_removed"
AI_PROVIDER_SELECTED_EVENT = "ai.provider_selected"


class AIOrchestratorManager:
    """Coordinate immutable provider registration and pure provider selection."""

    def __init__(
        self,
        registry: ProviderCatalog | None = None,
        selector: ProviderSelectionStrategy | None = None,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        snapshot_factory: ProviderSnapshotFactory | None = None,
        request_router: RequestRouter | None = None,
        orchestration_events: OrchestrationEvents | None = None,
        preference_resolver: ModelPreferenceResolver | None = None,
        provider_negotiator: ProviderNegotiator | None = None,
        orchestration_planner: OrchestrationPlanner | None = None,
        orchestration_lifecycle: OrchestrationLifecycleManager | None = None,
    ) -> None:
        resolved_registry = registry if registry is not None else ProviderRegistry()
        if not all(
            callable(getattr(resolved_registry, method, None))
            for method in ("register", "unregister", "get", "list", "update_health")
        ):
            raise TypeError("registry does not implement the provider catalog contract")
        resolved_selector = (
            selector if selector is not None else PriorityProviderSelector()
        )
        if not callable(getattr(resolved_selector, "select", None)):
            raise TypeError("selector must provide a select method")
        resolved_factory = (
            snapshot_factory
            if snapshot_factory is not None
            else ProviderSnapshotFactory()
        )
        if not callable(getattr(resolved_factory, "create", None)):
            raise TypeError("snapshot_factory must provide a create method")
        if event_bus is not None and not callable(getattr(event_bus, "publish", None)):
            raise TypeError("event_bus must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        resolved_logger = logger if logger is not None else NullLogger("narvis.ai.core")
        if request_router is None:
            from AI.routing.router import RequestRouter

            resolved_router = RequestRouter(
                event_bus=event_bus,
                logger=resolved_logger,
            )
        else:
            resolved_router = request_router
        if not all(
            callable(getattr(resolved_router, method, None))
            for method in (
                "route",
                "score_provider",
                "validate_provider",
                "fallback",
                "summary",
            )
        ):
            raise TypeError("request_router does not implement the routing contract")
        from AI.orchestrator.events import OrchestrationEvents
        from AI.orchestrator.lifecycle import OrchestrationLifecycleManager
        from AI.orchestrator.negotiation import ProviderNegotiator
        from AI.orchestrator.planner import OrchestrationPlanner
        from AI.orchestrator.preferences import ModelPreferenceResolver

        resolved_orchestration_events = (
            orchestration_events
            if orchestration_events is not None
            else OrchestrationEvents(event_bus, logger=resolved_logger)
        )
        if not callable(getattr(resolved_orchestration_events, "publish", None)):
            raise TypeError("orchestration_events must provide a publish method")
        resolved_preferences = (
            preference_resolver
            if preference_resolver is not None
            else ModelPreferenceResolver(
                events=resolved_orchestration_events,
                logger=resolved_logger,
            )
        )
        if not all(
            callable(getattr(resolved_preferences, method, None))
            for method in ("resolve", "resolve_for_providers")
        ):
            raise TypeError("preference_resolver does not implement its contract")
        resolved_negotiator = (
            provider_negotiator
            if provider_negotiator is not None
            else ProviderNegotiator(
                resolved_router,
                resolved_preferences,
                events=resolved_orchestration_events,
                logger=resolved_logger,
            )
        )
        if not callable(getattr(resolved_negotiator, "negotiate", None)):
            raise TypeError("provider_negotiator must provide a negotiate method")
        resolved_planner = (
            orchestration_planner
            if orchestration_planner is not None
            else OrchestrationPlanner(
                resolved_negotiator,
                resolved_orchestration_events,
                logger=resolved_logger,
            )
        )
        if not callable(getattr(resolved_planner, "plan", None)):
            raise TypeError("orchestration_planner must provide a plan method")
        resolved_lifecycle = (
            orchestration_lifecycle
            if orchestration_lifecycle is not None
            else OrchestrationLifecycleManager(
                events=resolved_orchestration_events,
                logger=resolved_logger,
            )
        )
        if not all(
            callable(getattr(resolved_lifecycle, method, None))
            for method in (
                "create_session",
                "get_session",
                "record_plan",
                "complete_session",
                "summary",
            )
        ):
            raise TypeError("orchestration_lifecycle does not implement its contract")
        self._registry = resolved_registry
        self._selector = resolved_selector
        self._snapshot_factory = resolved_factory
        self._request_router = resolved_router
        self._orchestration_events = resolved_orchestration_events
        self._preference_resolver = resolved_preferences
        self._provider_negotiator = resolved_negotiator
        self._orchestration_planner = resolved_planner
        self._orchestration_lifecycle = resolved_lifecycle
        self._event_bus = event_bus
        self._logger = resolved_logger

    @property
    def registry(self) -> ProviderCatalog:
        """Return the injected provider catalog."""

        return self._registry

    @property
    def request_router(self) -> RequestRouter:
        """Return the injected deterministic request router."""

        return self._request_router

    @property
    def orchestration_lifecycle(self) -> OrchestrationLifecycleManager:
        """Return the injected orchestration lifecycle service."""

        return self._orchestration_lifecycle

    @property
    def orchestration_planner(self) -> OrchestrationPlanner:
        """Return the injected architecture-only planner."""

        return self._orchestration_planner

    @property
    def provider_negotiator(self) -> ProviderNegotiator:
        """Return the injected provider negotiation service."""

        return self._provider_negotiator

    @property
    def preference_resolver(self) -> ModelPreferenceResolver:
        """Return the injected model preference resolver."""

        return self._preference_resolver

    def register_provider(
        self,
        provider: AIProvider | ProviderMetadata | ProviderDescriptor,
    ) -> AIProvider:
        """Register immutable provider data and publish a safe lifecycle event."""

        snapshot = self._snapshot_factory.create(provider)
        registered = self._registry.register(snapshot)
        self._log(
            LogLevel.INFO,
            "AI provider registered",
            provider_id=registered.provider_id,
            status=registered.status.value,
            priority=int(registered.priority),
        )
        self._publish(
            AI_PROVIDER_REGISTERED_EVENT,
            registered,
        )
        return registered

    register = register_provider

    def unregister_provider(self, provider_id: str) -> AIProvider:
        """Remove one provider and publish a safe lifecycle event."""

        removed = self._registry.unregister(provider_id)
        self._log(
            LogLevel.INFO,
            "AI provider removed",
            provider_id=removed.provider_id,
        )
        self._publish(AI_PROVIDER_REMOVED_EVENT, removed)
        return removed

    unregister = unregister_provider

    def list_providers(
        self,
        *,
        capability: ProviderCapability | None = None,
        status: ProviderStatus | None = None,
        include_disabled: bool = True,
    ) -> tuple[AIProvider, ...]:
        """Return a deterministic immutable provider snapshot."""

        return self._registry.list(
            capability=capability,
            status=status,
            include_disabled=include_disabled,
        )

    @overload
    def provider_health(self, provider_id: str) -> ProviderHealth: ...

    @overload
    def provider_health(
        self, provider_id: None = None
    ) -> tuple[ProviderHealth, ...]: ...

    def provider_health(
        self,
        provider_id: str | None = None,
    ) -> ProviderHealth | tuple[ProviderHealth, ...]:
        """Return one or all retained health snapshots without active probing."""

        if provider_id is not None:
            health = self._registry.get(provider_id).health
            assert health is not None
            return health
        values: list[ProviderHealth] = []
        for provider in self._registry.list(include_disabled=True):
            assert provider.health is not None
            values.append(provider.health)
        return tuple(values)

    def update_provider_health(self, health: ProviderHealth) -> AIProvider:
        """Replace externally supplied provider health without probing it."""

        updated = self._registry.update_health(health)
        self._log(
            LogLevel.INFO,
            "AI provider health updated",
            provider_id=updated.provider_id,
            status=updated.status.value,
        )
        return updated

    def select_provider(
        self,
        request: AIRequest | None = None,
        *,
        required_capabilities: Iterable[ProviderCapability] = (),
        preferred_provider_id: str | None = None,
    ) -> AIProvider:
        """Select provider metadata only; no provider operation is available."""

        required = tuple(required_capabilities)
        selected = self._selector.select(
            self._registry.list(include_disabled=True),
            request,
            required_capabilities=required,
            preferred_provider_id=preferred_provider_id,
        )
        self._log(
            LogLevel.INFO,
            "AI provider selected",
            provider_id=selected.provider_id,
            request_id=None if request is None else request.request_id,
            status=selected.status.value,
        )
        self._publish(
            AI_PROVIDER_SELECTED_EVENT,
            selected,
            request_id=None if request is None else request.request_id,
            required_capabilities=tuple(
                item.value
                for item in (
                    *(() if request is None else request.required_capabilities),
                    *required,
                )
                if isinstance(item, ProviderCapability)
            ),
        )
        return selected

    select = select_provider

    def provider_metadata(self, provider_id: str) -> ProviderMetadata:
        """Return immutable provider metadata."""

        return self._registry.get(provider_id).metadata

    def get_provider(self, provider_id: str) -> AIProvider:
        """Return one registered immutable provider snapshot."""

        return self._registry.get(provider_id)

    def route_request(
        self,
        request: AIRequest,
        policy: RoutingPolicy | None = None,
    ) -> RoutingDecision:
        """Create a deterministic routing decision without provider execution."""

        return self._request_router.route(
            request,
            self._registry.list(include_disabled=True),
            policy,
        )

    def score_provider(
        self,
        provider: str | AIProvider,
        request: AIRequest,
        policy: RoutingPolicy | None = None,
    ) -> ProviderScore:
        """Score one registered provider for an immutable request."""

        return self._request_router.score_provider(
            self._registered_provider(provider),
            request,
            policy,
        )

    def validate_provider(
        self,
        provider: str | AIProvider,
        request: AIRequest,
        policy: RoutingPolicy | None = None,
    ) -> CompatibilityReport:
        """Return compatibility facts for one registered provider and request."""

        return self._request_router.validate_provider(
            self._registered_provider(provider),
            request,
            policy,
        )

    def fallback_provider(
        self,
        decision: RoutingDecision,
        current_provider_id: str | None = None,
    ) -> AIProvider:
        """Return the next compatible provider from an immutable fallback plan."""

        return self._request_router.fallback(
            decision,
            self._registry.list(include_disabled=True),
            current_provider_id,
        )

    def routing_summary(self, decision: RoutingDecision) -> RoutingSummary:
        """Return compact immutable facts for a routing decision."""

        return self._request_router.summary(decision)

    def create_session(
        self,
        owner_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        ttl: timedelta | None = None,
        expires_at: datetime | None = None,
        session_id: str | None = None,
    ) -> OrchestrationSession:
        """Create a thread-safe deterministic orchestration session."""

        return self._orchestration_lifecycle.create_session(
            owner_id,
            metadata=metadata,
            ttl=ttl,
            expires_at=expires_at,
            session_id=session_id,
        )

    def plan_request(
        self,
        session_id: str,
        request: AIRequest,
        routing_policy: RoutingPolicy | None = None,
        preference_policy: ModelPreferencePolicy | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> OrchestrationPlan:
        """Generate and record a non-executable plan for an active session."""

        session = self._orchestration_lifecycle.get_session(session_id)
        plan = self._orchestration_planner.plan(
            session,
            request,
            self._registry.list(include_disabled=True),
            routing_policy,
            preference_policy,
            metadata=metadata,
        )
        self._orchestration_lifecycle.record_plan(session_id, plan)
        return plan

    def negotiate_provider(
        self,
        request: AIRequest,
        routing_policy: RoutingPolicy | None = None,
        preference_policy: ModelPreferencePolicy | None = None,
    ) -> ProviderNegotiation:
        """Negotiate provider, model, and capabilities without execution."""

        return self._provider_negotiator.negotiate(
            request,
            self._registry.list(include_disabled=True),
            routing_policy,
            preference_policy,
        )

    def resolve_preferences(
        self,
        request: AIRequest,
        preference_policy: ModelPreferencePolicy | None = None,
    ) -> PreferenceResolution:
        """Resolve model and metadata preferences over registered providers."""

        return self._preference_resolver.resolve_for_providers(
            request,
            tuple(
                provider
                for provider in self._registry.list(include_disabled=False)
                if provider.selectable
            ),
            preference_policy,
        )

    def orchestration_summary(self, session_id: str) -> OrchestrationSummary:
        """Return structured orchestration lifecycle and metadata facts."""

        return self._orchestration_lifecycle.summary(session_id)

    def complete_session(self, session_id: str) -> OrchestrationSession:
        """Complete an orchestration session without executing retained plans."""

        return self._orchestration_lifecycle.complete_session(session_id)

    def get_orchestration_session(self, session_id: str) -> OrchestrationSession:
        """Return one immutable orchestration session snapshot."""

        return self._orchestration_lifecycle.get_session(session_id)

    def _registered_provider(self, provider: str | AIProvider) -> AIProvider:
        if isinstance(provider, str):
            return self._registry.get(provider)
        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be a provider identifier or AIProvider")
        return self._registry.get(provider.provider_id)

    def _publish(
        self,
        event_name: str,
        provider: AIProvider,
        **extra: object,
    ) -> None:
        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "provider_id": provider.provider_id,
            "display_name": provider.metadata.label,
            "status": provider.status.value,
            "priority": int(provider.priority),
            "capabilities": tuple(item.value for item in provider.capabilities),
            **extra,
        }
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish AI provider event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


AIManager = AIOrchestratorManager
ProviderManager = AIOrchestratorManager


__all__ = [
    "AIManager",
    "AIOrchestratorManager",
    "AI_PROVIDER_REGISTERED_EVENT",
    "AI_PROVIDER_REMOVED_EVENT",
    "AI_PROVIDER_SELECTED_EVENT",
    "ProviderManager",
]
