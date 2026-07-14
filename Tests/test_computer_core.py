"""Comprehensive tests for the Phase 10 Computer service foundation."""

from __future__ import annotations

import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Computer.core import (
    ComputerCapability,
    ComputerCapabilityDiscoveryError,
    ComputerHealth,
    ComputerManager,
    ComputerProvider,
    ComputerProviderAlreadyInitializedError,
    ComputerProviderHealthError,
    ComputerProviderInfo,
    ComputerProviderInitializationError,
    ComputerProviderNotFoundError,
    ComputerProviderNotInitializedError,
    ComputerProviderShutdownError,
    ComputerRegistry,
    ComputerStatus,
    DuplicateComputerProviderError,
)


class _TestProvider(ComputerProvider):
    """Controllable provider with no computer action operations."""

    def __init__(
        self,
        name: str,
        *,
        health_result: object | None = None,
        capability_result: object | None = None,
        initialization_error: Exception | None = None,
        shutdown_error: Exception | None = None,
        health_error: Exception | None = None,
        capability_error: Exception | None = None,
    ) -> None:
        super().__init__(
            ComputerProviderInfo(
                name=name,
                description=f"{name} test provider",
                version="1.2.0",
                vendor="NARVIS",
                attributes={"source": "unit-test"},
            )
        )
        self.health_result = health_result or ComputerHealth(
            ComputerStatus.HEALTHY,
            "ready",
            {"provider": name},
        )
        self.capability_result = capability_result or (
            ComputerCapability(
                f"{name}.inspect",
                "Inspect inert provider metadata",
            ),
        )
        self.initialization_error = initialization_error
        self.shutdown_error = shutdown_error
        self.health_error = health_error
        self.capability_error = capability_error
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.health_calls = 0
        self.capability_calls = 0

    def initialize(self) -> None:
        self.initialize_calls += 1
        if self.initialization_error is not None:
            raise self.initialization_error

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error

    def health(self) -> ComputerHealth:
        self.health_calls += 1
        if self.health_error is not None:
            raise self.health_error
        return self.health_result  # type: ignore[return-value]

    def capabilities(self) -> tuple[ComputerCapability, ...]:
        self.capability_calls += 1
        if self.capability_error is not None:
            raise self.capability_error
        return self.capability_result  # type: ignore[return-value]


class _IncompleteProvider(ComputerProvider):
    """Provider missing most of the required abstract interface."""

    def initialize(self) -> None:
        return None


class _CapturingLogger:
    """Core-compatible logger used to verify dependency injection."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _FailingLogger:
    """Logger double used to verify logging is not control flow."""

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        raise RuntimeError("logger unavailable")


class ComputerModelAndProviderTests(unittest.TestCase):
    """Verify immutable models and the provider abstraction boundary."""

    def test_models_are_typed_detached_and_immutable(self) -> None:
        capability_attributes = {"mode": "metadata-only"}
        provider_attributes = {"platform": "test"}
        health_details = {"checks": 1}
        capability = ComputerCapability(
            "desktop.observe",
            attributes=capability_attributes,
        )
        info = ComputerProviderInfo(
            "test.provider",
            attributes=provider_attributes,
        )
        health = ComputerHealth(
            ComputerStatus.HEALTHY,
            details=health_details,
        )
        capability_attributes["mode"] = "changed"
        provider_attributes["platform"] = "changed"
        health_details["checks"] = 2

        self.assertEqual(capability.capability_id, "desktop.observe")
        self.assertEqual(info.provider_id, "test.provider")
        self.assertTrue(health.is_healthy)
        self.assertEqual(capability.attributes["mode"], "metadata-only")
        self.assertEqual(info.attributes["platform"], "test")
        self.assertEqual(health.details["checks"], 1)
        with self.assertRaises(TypeError):
            capability.attributes["new"] = True  # type: ignore[index]

    def test_models_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            ComputerCapability(" ")
        with self.assertRaises(ValueError):
            ComputerProviderInfo(" provider ")
        with self.assertRaises(ValueError):
            ComputerProviderInfo("provider", version="")
        with self.assertRaises(TypeError):
            ComputerHealth("healthy")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ComputerCapability(
                "valid",
                attributes={1: "invalid"},  # type: ignore[dict-item]
            )

    def test_provider_requires_complete_interface_and_exposes_info(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteProvider(ComputerProviderInfo("incomplete"))

        provider = _TestProvider("foundation")

        self.assertEqual(provider.info.name, "foundation")
        self.assertFalse(hasattr(provider, "execute"))


class ComputerRegistryTests(unittest.TestCase):
    """Verify registration, discovery, lookup, ordering, and events."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        self.event_bus.subscribe("computer.provider_registered", self.events.append)
        self.logger = _CapturingLogger()
        self.registry = ComputerRegistry(
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_register_discover_exists_list_and_publish_event(self) -> None:
        second = _TestProvider("provider.second")
        first = _TestProvider("provider.first")

        registered = self.registry.register(second)
        self.registry.register(first)

        self.assertIs(registered, second)
        self.assertIs(self.registry.find("provider.second"), second)
        self.assertIs(self.registry.get("provider.first"), first)
        self.assertTrue(self.registry.exists("provider.first"))
        self.assertFalse(self.registry.exists("missing"))
        self.assertEqual(self.registry.discover(), (first, second))
        self.assertEqual(self.registry.list(), (first, second))
        self.assertEqual(len(self.registry), 2)
        self.assertEqual(
            [event.name for event in self.events],
            ["computer.provider_registered", "computer.provider_registered"],
        )
        self.assertEqual(self.events[0].payload["name"], "provider.second")
        self.assertEqual(self.events[0].payload["version"], "1.2.0")
        self.assertTrue(
            any(
                message == "Computer provider registered"
                for _, message, _ in self.logger.entries
            )
        )

    def test_duplicate_registration_does_not_replace_provider(self) -> None:
        original = _TestProvider("duplicate")
        self.registry.register(original)

        with self.assertRaises(DuplicateComputerProviderError):
            self.registry.register(_TestProvider("duplicate"))

        self.assertIs(self.registry.get("duplicate"), original)
        self.assertEqual(len(self.events), 1)

    def test_unregister_returns_provider_and_unknown_name_fails(self) -> None:
        provider = _TestProvider("temporary")
        self.registry.register(provider)

        removed = self.registry.unregister("temporary")

        self.assertIs(removed, provider)
        self.assertFalse(self.registry.exists("temporary"))
        with self.assertRaises(ComputerProviderNotFoundError):
            self.registry.unregister("temporary")
        with self.assertRaises(ComputerProviderNotFoundError):
            self.registry.get("temporary")

    def test_registry_rejects_untyped_entries_and_invalid_names(self) -> None:
        with self.assertRaises(TypeError):
            self.registry.register(object())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.registry.find(" provider ")
        with self.assertRaises(ValueError):
            self.registry.exists("")

    def test_subscriber_failure_does_not_roll_back_registration(self) -> None:
        event_bus = EventBus()
        event_bus.subscribe(
            "computer.provider_registered",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        logger = _CapturingLogger()
        registry = ComputerRegistry(logger=logger, event_bus=event_bus)

        registry.register(_TestProvider("resilient"))

        self.assertTrue(registry.exists("resilient"))
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in logger.entries)
        )


class ComputerManagerTests(unittest.TestCase):
    """Verify lifecycle, health, discovery, DI, and failure handling."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in (
            "computer.provider_registered",
            "computer.provider_initialized",
            "computer.health_checked",
        ):
            self.event_bus.subscribe(event_name, self.events.append)
        self.logger = _CapturingLogger()
        self.manager = ComputerManager(
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_manager_coordinates_registration_lifecycle_health_and_events(self) -> None:
        provider = _TestProvider("managed")

        self.manager.register(provider)
        initialized = self.manager.initialize_provider("managed")
        health = self.manager.check_health("managed")

        self.assertIs(initialized, provider)
        self.assertIs(health, provider.health_result)
        self.assertEqual(provider.initialize_calls, 1)
        self.assertEqual(provider.health_calls, 1)
        self.assertEqual(provider.shutdown_calls, 0)
        self.assertTrue(self.manager.is_initialized("managed"))
        self.assertEqual(
            [event.name for event in self.events],
            [
                "computer.provider_registered",
                "computer.provider_initialized",
                "computer.health_checked",
            ],
        )
        self.assertEqual(self.events[-1].payload["status"], "healthy")
        self.assertTrue(self.events[-1].payload["healthy"])

        shut_down = self.manager.shutdown("managed")

        self.assertIs(shut_down, provider)
        self.assertEqual(provider.shutdown_calls, 1)
        self.assertFalse(self.manager.is_initialized("managed"))

    def test_manager_facade_exposes_registry_without_provider_calls(self) -> None:
        provider = _TestProvider("facade")
        self.manager.register(provider)

        self.assertTrue(self.manager.exists("facade"))
        self.assertIs(self.manager.find("facade"), provider)
        self.assertEqual(self.manager.list(), (provider,))
        self.assertEqual(self.manager.discover(), (provider,))
        self.assertEqual(self.manager.provider_info("facade"), provider.info)
        self.assertEqual(provider.initialize_calls, 0)
        self.assertEqual(provider.health_calls, 0)
        self.assertEqual(provider.capability_calls, 0)

    def test_duplicate_initialization_and_inactive_shutdown_are_explicit(self) -> None:
        provider = _TestProvider("lifecycle")
        self.manager.register(provider)
        self.manager.initialize("lifecycle")

        with self.assertRaises(ComputerProviderAlreadyInitializedError):
            self.manager.initialize("lifecycle")
        self.manager.shutdown_provider("lifecycle")
        with self.assertRaises(ComputerProviderNotInitializedError):
            self.manager.shutdown_provider("lifecycle")

        self.assertEqual(provider.initialize_calls, 1)
        self.assertEqual(provider.shutdown_calls, 1)

    def test_initialization_failure_does_not_mark_provider_initialized(self) -> None:
        provider = _TestProvider(
            "initialization.failure",
            initialization_error=RuntimeError("initialize failed"),
        )
        self.manager.register(provider)

        with self.assertRaises(ComputerProviderInitializationError):
            self.manager.initialize_provider("initialization.failure")

        self.assertFalse(self.manager.is_initialized("initialization.failure"))
        self.assertEqual(
            [event.name for event in self.events],
            ["computer.provider_registered"],
        )

    def test_shutdown_failure_preserves_initialized_state_for_retry(self) -> None:
        provider = _TestProvider(
            "shutdown.failure",
            shutdown_error=RuntimeError("shutdown failed"),
        )
        self.manager.register(provider)
        self.manager.initialize_provider("shutdown.failure")

        with self.assertRaises(ComputerProviderShutdownError):
            self.manager.shutdown_provider("shutdown.failure")

        self.assertTrue(self.manager.is_initialized("shutdown.failure"))
        self.assertEqual(provider.shutdown_calls, 1)

    def test_health_checks_validate_results_and_wrap_provider_failures(self) -> None:
        invalid = _TestProvider("health.invalid", health_result="healthy")
        failing = _TestProvider(
            "health.failure",
            health_error=RuntimeError("health failed"),
        )
        self.manager.register(invalid)
        self.manager.register(failing)

        with self.assertRaises(ComputerProviderHealthError):
            self.manager.health("health.invalid")
        with self.assertRaises(ComputerProviderHealthError):
            self.manager.health("health.failure")

        self.assertNotIn(
            "computer.health_checked",
            [event.name for event in self.events],
        )

    def test_capability_discovery_is_typed_provider_keyed_and_read_only(self) -> None:
        second = _TestProvider("provider.second")
        first = _TestProvider("provider.first")
        self.manager.register(second)
        self.manager.register(first)

        first_capabilities = self.manager.capabilities("provider.first")
        discovered = self.manager.discover_capabilities()

        self.assertEqual(first_capabilities, first.capability_result)
        self.assertEqual(
            tuple(discovered),
            ("provider.first", "provider.second"),
        )
        self.assertEqual(discovered["provider.second"], second.capability_result)
        with self.assertRaises(TypeError):
            discovered["new"] = ()  # type: ignore[index]
        self.assertEqual(first.initialize_calls, 0)
        self.assertEqual(first.health_calls, 0)

    def test_capability_discovery_rejects_invalid_results_and_wraps_failures(
        self,
    ) -> None:
        invalid_container = _TestProvider(
            "capability.list",
            capability_result=[ComputerCapability("invalid.list")],
        )
        invalid_member = _TestProvider(
            "capability.member",
            capability_result=("invalid",),
        )
        failing = _TestProvider(
            "capability.failure",
            capability_error=RuntimeError("capability failed"),
        )
        for provider in (invalid_container, invalid_member, failing):
            self.manager.register(provider)

        for name in (
            "capability.list",
            "capability.member",
            "capability.failure",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ComputerCapabilityDiscoveryError):
                    self.manager.capabilities(name)

    def test_bulk_coordination_is_deterministic_and_does_not_execute_actions(
        self,
    ) -> None:
        second = _TestProvider("provider.second")
        first = _TestProvider("provider.first")
        self.manager.register(second)
        self.manager.register(first)

        initialized = self.manager.initialize_all()
        health = self.manager.health_all()
        shut_down = self.manager.shutdown_all()

        self.assertEqual(initialized, (first, second))
        self.assertEqual(tuple(health), ("provider.first", "provider.second"))
        self.assertEqual(shut_down, (second, first))
        self.assertEqual(first.initialize_calls, 1)
        self.assertEqual(first.health_calls, 1)
        self.assertEqual(first.capability_calls, 0)
        self.assertEqual(first.shutdown_calls, 1)
        with self.assertRaises(TypeError):
            health["new"] = ComputerHealth()  # type: ignore[index]

    def test_unregister_shuts_down_active_provider_before_removal(self) -> None:
        provider = _TestProvider("temporary")
        self.manager.register(provider)
        self.manager.initialize_provider("temporary")

        removed = self.manager.unregister("temporary")

        self.assertIs(removed, provider)
        self.assertEqual(provider.shutdown_calls, 1)
        self.assertFalse(self.manager.exists("temporary"))

    def test_injected_registry_is_reused_and_invalid_injection_fails(self) -> None:
        registry = ComputerRegistry()
        manager = ComputerManager(registry=registry)

        self.assertIs(manager.registry, registry)
        with self.assertRaises(TypeError):
            ComputerManager(registry=object())  # type: ignore[arg-type]

    def test_event_and_logging_failures_do_not_change_successful_state(self) -> None:
        event_bus = EventBus()
        for event_name in (
            "computer.provider_registered",
            "computer.provider_initialized",
            "computer.health_checked",
        ):
            event_bus.subscribe(
                event_name,
                lambda event: (_ for _ in ()).throw(
                    RuntimeError("subscriber unavailable")
                ),
            )
        manager = ComputerManager(logger=_FailingLogger(), event_bus=event_bus)
        provider = _TestProvider("resilient")

        manager.register(provider)
        manager.initialize_provider("resilient")
        health = manager.health("resilient")

        self.assertTrue(manager.is_initialized("resilient"))
        self.assertEqual(health.status, ComputerStatus.HEALTHY)


if __name__ == "__main__":
    unittest.main()
