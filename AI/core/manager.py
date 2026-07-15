"""Provider-agnostic AI orchestration manager with no execution capability."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, overload

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
        self._registry = resolved_registry
        self._selector = resolved_selector
        self._snapshot_factory = resolved_factory
        self._request_router = resolved_router
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
