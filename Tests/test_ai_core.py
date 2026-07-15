"""Comprehensive tests for Phase 13 AI Orchestrator Sprint 1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from AI import BrainEngine, ConversationManager
from AI.core import (
    AIManager,
    AIProvider,
    AIRequest,
    AIResponse,
    AIValidationError,
    NoEligibleProviderError,
    PriorityProviderSelector,
    ProviderAlreadyRegisteredError,
    ProviderCapability,
    ProviderHealth,
    ProviderHealthError,
    ProviderMetadata,
    ProviderNotFoundError,
    ProviderPriority,
    ProviderRegistry,
    ProviderSnapshotFactory,
    ProviderStatus,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _Clock:
    """Mutable aware clock used for deterministic provider snapshots."""

    def __init__(self) -> None:
        self.now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)

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


class _Descriptor:
    """Data-only structural provider descriptor used for DI tests."""

    def __init__(self, metadata: ProviderMetadata, health: ProviderHealth) -> None:
        self.metadata = metadata
        self.health = health


class _TrackingSelector:
    """Injected selector that records the immutable candidate snapshot."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                tuple[AIProvider, ...],
                AIRequest | None,
                tuple[ProviderCapability, ...],
                str | None,
            ]
        ] = []

    def select(
        self,
        providers: tuple[AIProvider, ...],
        request: AIRequest | None = None,
        *,
        required_capabilities: tuple[ProviderCapability, ...] = (),
        preferred_provider_id: str | None = None,
    ) -> AIProvider:
        candidates = tuple(providers)
        required = tuple(required_capabilities)
        self.calls.append((candidates, request, required, preferred_provider_id))
        return candidates[-1]


def _metadata(
    name: str = "provider-a",
    *,
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    priority: ProviderPriority = ProviderPriority.NORMAL,
    enabled: bool = True,
    attributes: dict[str, object] | None = None,
) -> ProviderMetadata:
    return ProviderMetadata(
        name=name,
        display_name=name.title(),
        capabilities=capabilities,
        priority=priority,
        supported_models=("model-1",),
        tags=("local",),
        attributes=attributes or {},
        enabled=enabled,
    )


def _provider(
    name: str = "provider-a",
    *,
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.CHAT,),
    priority: ProviderPriority = ProviderPriority.NORMAL,
    status: ProviderStatus = ProviderStatus.AVAILABLE,
    enabled: bool = True,
    checked_at: datetime | None = None,
) -> AIProvider:
    timestamp = checked_at or datetime(2026, 7, 15, tzinfo=timezone.utc)
    return AIProvider(
        metadata=_metadata(
            name,
            capabilities=capabilities,
            priority=priority,
            enabled=enabled,
        ),
        health=ProviderHealth(
            provider_id=name,
            status=status,
            checked_at=timestamp,
        ),
        registered_at=timestamp,
    )


class AIModelTests(unittest.TestCase):
    """Verify typed, immutable, deeply detached orchestration models."""

    def test_provider_metadata_is_deeply_immutable(self) -> None:
        source = {"limits": {"regions": ["local"]}}
        metadata = _metadata(attributes=source)
        source["limits"]["regions"].append("remote")  # type: ignore[index,union-attr]

        self.assertEqual(metadata.provider_id, "provider-a")
        self.assertEqual(metadata.attributes["limits"]["regions"], ("local",))
        self.assertTrue(metadata.supports(ProviderCapability.CHAT))
        with self.assertRaises(TypeError):
            metadata.attributes["new"] = True  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            metadata.name = "changed"  # type: ignore[misc]

    def test_provider_metadata_validates_typed_fields(self) -> None:
        with self.assertRaises(ValueError):
            ProviderMetadata(name=" provider ")
        with self.assertRaises(TypeError):
            ProviderMetadata(name="provider", capabilities=("chat",))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ProviderMetadata(
                name="provider",
                capabilities=(ProviderCapability.CHAT, ProviderCapability.CHAT),
            )
        with self.assertRaises(TypeError):
            ProviderMetadata(name="provider", priority=1)  # type: ignore[arg-type]

    def test_provider_status_and_priority_aliases_are_stable(self) -> None:
        self.assertIs(ProviderStatus.HEALTHY, ProviderStatus.AVAILABLE)
        self.assertIs(ProviderStatus.OFFLINE, ProviderStatus.UNAVAILABLE)
        self.assertIs(ProviderPriority.DEFAULT, ProviderPriority.NORMAL)
        self.assertLess(ProviderPriority.HIGH, ProviderPriority.LOW)

    def test_provider_health_reports_selection_facts(self) -> None:
        available = ProviderHealth("provider-a", ProviderStatus.AVAILABLE)
        degraded = ProviderHealth("provider-a", ProviderStatus.DEGRADED)
        unknown = ProviderHealth("provider-a")

        self.assertTrue(available.healthy)
        self.assertTrue(degraded.selectable)
        self.assertFalse(unknown.selectable)
        with self.assertRaises(ValueError):
            ProviderHealth("provider-a", consecutive_failures=-1)

    def test_provider_enforces_metadata_health_binding(self) -> None:
        with self.assertRaises(ValueError):
            AIProvider(
                metadata=_metadata("provider-a"),
                health=ProviderHealth("provider-b"),
            )
        with self.assertRaises(ValueError):
            _provider("disabled", enabled=False, status=ProviderStatus.AVAILABLE)

        disabled = AIProvider(metadata=_metadata("disabled", enabled=False))
        self.assertEqual(disabled.status, ProviderStatus.DISABLED)
        self.assertFalse(disabled.selectable)

    def test_provider_default_health_is_declared_available(self) -> None:
        provider = AIProvider(metadata=_metadata())

        self.assertEqual(provider.status, ProviderStatus.AVAILABLE)
        self.assertTrue(provider.selectable)

    def test_ai_request_is_immutable_and_detached(self) -> None:
        parameters = {"sampling": {"stops": ["END"]}}
        request = AIRequest(
            prompt="Plan a response",
            required_capabilities=(ProviderCapability.REASONING,),
            preferred_provider_id="provider-a",
            parameters=parameters,
            metadata={"trace": [1]},
        )
        parameters["sampling"]["stops"].append("STOP")  # type: ignore[index,union-attr]

        self.assertEqual(request.parameters["sampling"]["stops"], ("END",))
        with self.assertRaises(TypeError):
            request.parameters["new"] = True  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            request.prompt = "changed"  # type: ignore[misc]

    def test_ai_request_rejects_invalid_content_and_capabilities(self) -> None:
        with self.assertRaises(ValueError):
            AIRequest(prompt="  ")
        with self.assertRaises(TypeError):
            AIRequest(prompt="text", required_capabilities=("chat",))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            AIRequest(
                prompt="text",
                created_at=datetime(2026, 7, 15),
            )

    def test_ai_response_is_typed_and_deeply_immutable(self) -> None:
        response = AIResponse(
            request_id="request-1",
            provider_id="provider-a",
            content="future normalized output",
            metadata={"usage": {"units": [1, 2]}},
        )

        self.assertEqual(response.metadata["usage"]["units"], (1, 2))
        with self.assertRaises(TypeError):
            response.metadata["usage"] = {}  # type: ignore[index]
        with self.assertRaises(TypeError):
            AIResponse("request-1", "provider-a", content=1)  # type: ignore[arg-type]


class ProviderSelectorTests(unittest.TestCase):
    """Verify pure provider snapshot creation and deterministic selection."""

    def test_snapshot_factory_detaches_structural_descriptor(self) -> None:
        clock = _Clock()
        descriptor = _Descriptor(
            _metadata(),
            ProviderHealth("provider-a", checked_at=clock.now),
        )
        snapshot = ProviderSnapshotFactory(clock).create(descriptor)

        self.assertIsInstance(snapshot, AIProvider)
        self.assertEqual(snapshot.registered_at, clock.now)
        self.assertIs(snapshot.metadata, descriptor.metadata)

    def test_snapshot_factory_accepts_metadata_and_validates_clock(self) -> None:
        clock = _Clock()
        snapshot = ProviderSnapshotFactory(clock).create(_metadata())
        self.assertEqual(snapshot.registered_at, clock.now)
        with self.assertRaises(AIValidationError):
            ProviderSnapshotFactory(lambda: datetime(2026, 7, 15)).create(_metadata())
        with self.assertRaises(TypeError):
            ProviderSnapshotFactory(clock).create(object())  # type: ignore[arg-type]

    def test_selector_uses_priority_then_stable_identifier(self) -> None:
        selector = PriorityProviderSelector()
        selected = selector.select(
            (
                _provider("zeta", priority=ProviderPriority.NORMAL),
                _provider("beta", priority=ProviderPriority.HIGH),
                _provider("alpha", priority=ProviderPriority.HIGH),
            )
        )

        self.assertEqual(selected.provider_id, "alpha")

    def test_selector_respects_required_capabilities(self) -> None:
        selector = PriorityProviderSelector()
        selected = selector.select(
            (
                _provider("chat", priority=ProviderPriority.HIGHEST),
                _provider(
                    "reasoner",
                    capabilities=(
                        ProviderCapability.CHAT,
                        ProviderCapability.REASONING,
                    ),
                ),
            ),
            AIRequest(
                prompt="reason",
                required_capabilities=(ProviderCapability.REASONING,),
            ),
        )

        self.assertEqual(selected.provider_id, "reasoner")

    def test_selector_honors_eligible_preference(self) -> None:
        selected = PriorityProviderSelector().select(
            (
                _provider("high", priority=ProviderPriority.HIGH),
                _provider("preferred", priority=ProviderPriority.LOW),
            ),
            preferred_provider_id="preferred",
        )
        self.assertEqual(selected.provider_id, "preferred")

    def test_selector_falls_back_from_ineligible_preference(self) -> None:
        selected = PriorityProviderSelector().select(
            (
                _provider("healthy"),
                _provider("offline", status=ProviderStatus.UNAVAILABLE),
            ),
            preferred_provider_id="offline",
        )
        self.assertEqual(selected.provider_id, "healthy")

    def test_selector_can_exclude_degraded_providers(self) -> None:
        providers = (_provider("degraded", status=ProviderStatus.DEGRADED),)
        self.assertEqual(
            PriorityProviderSelector().select(providers).provider_id,
            "degraded",
        )
        with self.assertRaises(NoEligibleProviderError):
            PriorityProviderSelector(allow_degraded=False).select(providers)

    def test_selector_rejects_invalid_or_ineligible_candidates(self) -> None:
        with self.assertRaises(NoEligibleProviderError):
            PriorityProviderSelector().select(
                (_provider("offline", status=ProviderStatus.UNAVAILABLE),)
            )
        with self.assertRaises(AIValidationError):
            PriorityProviderSelector().select(
                (_provider("duplicate"), _provider("duplicate"))
            )
        with self.assertRaises(TypeError):
            PriorityProviderSelector().select((_provider(),), required_capabilities=("chat",))  # type: ignore[arg-type]

    def test_provider_services_expose_no_execution_operation(self) -> None:
        provider = _provider()
        selector = PriorityProviderSelector()
        manager = AIManager()
        for value in (provider, selector, manager):
            for method in ("execute", "generate", "complete", "invoke", "run"):
                self.assertFalse(hasattr(value, method))


class ProviderRegistryTests(unittest.TestCase):
    """Verify atomic registry operations, filtering, and health replacement."""

    def test_register_get_list_and_unregister(self) -> None:
        registry = ProviderRegistry()
        low = registry.register(_provider("low", priority=ProviderPriority.LOW))
        high = registry.register(_provider("high", priority=ProviderPriority.HIGH))

        self.assertIs(registry.get("low"), low)
        self.assertEqual(registry.list(), (high, low))
        self.assertEqual(len(registry), 2)
        self.assertIn("high", registry)
        self.assertIs(registry.unregister("high"), high)
        self.assertNotIn("high", registry)

    def test_registry_rejects_duplicate_and_missing_providers(self) -> None:
        registry = ProviderRegistry()
        registry.register(_provider())
        with self.assertRaises(ProviderAlreadyRegisteredError):
            registry.register(_provider())
        with self.assertRaises(ProviderNotFoundError):
            registry.get("missing")
        with self.assertRaises(ProviderNotFoundError):
            registry.unregister("missing")
        with self.assertRaises(AIValidationError):
            registry.get(" invalid ")

    def test_registry_filters_capability_status_and_enabled_state(self) -> None:
        registry = ProviderRegistry()
        chat = registry.register(_provider("chat"))
        reasoner = registry.register(
            _provider(
                "reasoner",
                capabilities=(ProviderCapability.REASONING,),
                status=ProviderStatus.DEGRADED,
            )
        )
        disabled = registry.register(
            _provider("disabled", enabled=False, status=ProviderStatus.DISABLED)
        )

        self.assertEqual(
            registry.list(capability=ProviderCapability.CHAT),
            (chat, disabled),
        )
        self.assertEqual(
            registry.list(status=ProviderStatus.DEGRADED),
            (reasoner,),
        )
        self.assertNotIn(disabled, registry.list(include_disabled=False))

    def test_registry_replaces_health_without_mutating_old_snapshot(self) -> None:
        registry = ProviderRegistry()
        original = registry.register(_provider())
        health = ProviderHealth(
            "provider-a",
            ProviderStatus.DEGRADED,
            checked_at=original.registered_at + timedelta(minutes=1),
            message="declared degraded",
        )
        updated = registry.update_health(health)

        self.assertEqual(original.status, ProviderStatus.AVAILABLE)
        self.assertEqual(updated.status, ProviderStatus.DEGRADED)
        self.assertIs(registry.health("provider-a"), health)
        self.assertIs(registry.metadata("provider-a"), updated.metadata)

    def test_registry_rejects_invalid_disabled_health_update(self) -> None:
        registry = ProviderRegistry()
        registry.register(
            _provider("disabled", enabled=False, status=ProviderStatus.DISABLED)
        )
        with self.assertRaises(ProviderHealthError):
            registry.update_health(ProviderHealth("disabled", ProviderStatus.AVAILABLE))

    def test_registry_clear_returns_deterministic_snapshot(self) -> None:
        registry = ProviderRegistry()
        first = registry.register(_provider("first", priority=ProviderPriority.HIGH))
        second = registry.register(_provider("second", priority=ProviderPriority.LOW))
        self.assertEqual(registry.clear(), (first, second))
        self.assertEqual(registry.list(), ())

    def test_registry_registration_is_thread_safe(self) -> None:
        registry = ProviderRegistry()

        def register(index: int) -> str:
            return registry.register(_provider(f"provider-{index:03d}")).provider_id

        with ThreadPoolExecutor(max_workers=8) as pool:
            identifiers = tuple(pool.map(register, range(64)))

        self.assertEqual(len(identifiers), 64)
        self.assertEqual(len(set(identifiers)), 64)
        self.assertEqual(len(registry), 64)


class AIManagerTests(unittest.TestCase):
    """Verify orchestration APIs, DI, events, logging, and no execution."""

    def setUp(self) -> None:
        self.events: list[SystemEvent] = []
        self.bus = EventBus()
        for name in (
            "ai.provider_registered",
            "ai.provider_removed",
            "ai.provider_selected",
        ):
            self.bus.subscribe(name, self.events.append)
        self.logger = _CapturingLogger()
        self.manager = AIManager(event_bus=self.bus, logger=self.logger)

    def test_manager_registration_listing_metadata_and_health(self) -> None:
        first = self.manager.register_provider(_metadata("first"))
        second = self.manager.register_provider(_provider("second"))

        self.assertEqual(self.manager.list_providers(), (first, second))
        self.assertIs(self.manager.provider_metadata("first"), first.metadata)
        self.assertIs(self.manager.provider_health("second"), second.health)
        self.assertEqual(
            self.manager.provider_health(),
            (first.health, second.health),
        )
        self.assertEqual(
            [event.name for event in self.events],
            ["ai.provider_registered", "ai.provider_registered"],
        )
        self.assertTrue(
            any(
                message == "AI provider registered"
                for _, message, _ in self.logger.entries
            )
        )

    def test_manager_unregisters_provider_and_publishes_event(self) -> None:
        registered = self.manager.register_provider(_provider())
        removed = self.manager.unregister_provider(registered.provider_id)

        self.assertIs(removed, registered)
        self.assertEqual(self.events[-1].name, "ai.provider_removed")
        with self.assertRaises(ProviderNotFoundError):
            self.manager.get_provider(registered.provider_id)

    def test_manager_selects_provider_and_publishes_safe_facts(self) -> None:
        self.manager.register_provider(
            _provider(
                "reasoner",
                capabilities=(ProviderCapability.REASONING,),
            )
        )
        request = AIRequest(
            prompt="sensitive prompt",
            required_capabilities=(ProviderCapability.REASONING,),
            metadata={"api_key": "must-not-leak"},
            request_id="request-001",
        )
        selected = self.manager.select_provider(request)
        event = self.events[-1]

        self.assertEqual(selected.provider_id, "reasoner")
        self.assertEqual(event.name, "ai.provider_selected")
        self.assertEqual(event.payload["request_id"], "request-001")
        self.assertNotIn("prompt", event.payload)
        self.assertNotIn("metadata", event.payload)
        self.assertNotIn("api_key", repr(event.payload))
        self.assertNotIn("sensitive prompt", repr(self.logger.entries))

    def test_manager_updates_retained_health(self) -> None:
        provider = self.manager.register_provider(_provider())
        health = ProviderHealth(
            provider.provider_id,
            ProviderStatus.UNAVAILABLE,
            checked_at=provider.registered_at + timedelta(minutes=1),
        )
        updated = self.manager.update_provider_health(health)

        self.assertEqual(updated.status, ProviderStatus.UNAVAILABLE)
        self.assertIs(self.manager.provider_health(provider.provider_id), health)
        with self.assertRaises(NoEligibleProviderError):
            self.manager.select_provider()

    def test_manager_uses_injected_registry_selector_and_factory(self) -> None:
        registry = ProviderRegistry()
        selector = _TrackingSelector()
        clock = _Clock()
        manager = AIManager(
            registry,
            selector,
            snapshot_factory=ProviderSnapshotFactory(clock),
        )
        first = manager.register_provider(_metadata("first"))
        second = manager.register_provider(_metadata("second"))
        request = AIRequest(prompt="select only")

        self.assertIs(manager.registry, registry)
        self.assertIs(manager.select_provider(request), second)
        self.assertEqual(selector.calls[0][0], (first, second))
        self.assertIs(selector.calls[0][1], request)

    def test_event_observer_failure_does_not_rollback_state(self) -> None:
        bus = EventBus()
        bus.subscribe(
            "ai.provider_registered",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        logger = _CapturingLogger()
        manager = AIManager(event_bus=bus, logger=logger)

        provider = manager.register_provider(_metadata())

        self.assertIs(manager.get_provider(provider.provider_id), provider)
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in logger.entries)
        )

    def test_logger_failure_does_not_change_manager_outcome(self) -> None:
        manager = AIManager(logger=_CapturingLogger(fail=True))
        provider = manager.register_provider(_metadata())
        self.assertIs(manager.select_provider(), provider)

    def test_manager_validates_injected_collaborators(self) -> None:
        with self.assertRaises(TypeError):
            AIManager(registry=object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            AIManager(selector=object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            AIManager(event_bus=object())  # type: ignore[arg-type]

    def test_legacy_ai_exports_remain_available(self) -> None:
        self.assertTrue(callable(BrainEngine))
        self.assertTrue(callable(ConversationManager))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
