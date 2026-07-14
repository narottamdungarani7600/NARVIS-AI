"""Focused tests for the Phase 9 skill framework foundation."""

from __future__ import annotations

import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Skills.core import (
    DuplicateSkillError,
    SkillAlreadyLoadedError,
    SkillCapability,
    SkillCategory,
    SkillDefinition,
    SkillInterface,
    SkillLoadError,
    SkillLoader,
    SkillManager,
    SkillMetadata,
    SkillNotFoundError,
    SkillNotLoadedError,
    SkillRegistry,
    SkillUnloadError,
)


class _TestSkill(SkillInterface[object, object]):
    """Controllable lifecycle implementation used by loader tests."""

    def __init__(
        self,
        *,
        initialization_error: Exception | None = None,
        shutdown_error: Exception | None = None,
    ) -> None:
        self.initialization_error = initialization_error
        self.shutdown_error = shutdown_error
        self.initialize_calls = 0
        self.execute_calls = 0
        self.shutdown_calls = 0

    def initialize(self) -> None:
        self.initialize_calls += 1
        if self.initialization_error is not None:
            raise self.initialization_error

    def execute(self, request: object) -> object:
        self.execute_calls += 1
        return request

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error


class _IncompleteSkill:
    """Invalid implementation that omits the execution contract."""

    def initialize(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


class _CapturingLogger:
    """Core-compatible logger used to verify dependency injection."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


def _definition(
    name: str,
    implementation: object | None = None,
    *,
    category: SkillCategory = SkillCategory.GENERAL,
) -> SkillDefinition:
    """Build one complete definition with deterministic test metadata."""

    skill = implementation if implementation is not None else _TestSkill()
    return SkillDefinition(
        metadata=SkillMetadata(
            name=name,
            description=f"{name} test skill",
            version="1.0.0",
            category=category,
            capabilities=(
                SkillCapability(name=f"{name}.run", description="Run the skill"),
            ),
            author="NARVIS",
            tags=("test",),
            attributes={"source": "unit-test"},
        ),
        implementation=skill,  # type: ignore[arg-type]
    )


class SkillModelTests(unittest.TestCase):
    """Verify metadata remains typed, detached, and immutable."""

    def test_metadata_and_definition_expose_required_skill_identity(self) -> None:
        attributes = {"source": "test"}
        metadata = SkillMetadata(
            name="system.status",
            description="Report status",
            category=SkillCategory.SYSTEM,
            capabilities=(SkillCapability("status.read"),),
            attributes=attributes,
        )
        definition = SkillDefinition(metadata=metadata, implementation=_TestSkill())
        attributes["source"] = "changed"

        self.assertEqual(metadata.skill_id, "system.status")
        self.assertEqual(definition.name, "system.status")
        self.assertEqual(metadata.attributes["source"], "test")
        with self.assertRaises(TypeError):
            metadata.attributes["new"] = True  # type: ignore[index]

    def test_models_reject_invalid_or_incomplete_definitions(self) -> None:
        with self.assertRaises(ValueError):
            SkillMetadata(name=" ")
        with self.assertRaises(TypeError):
            SkillMetadata(name="valid", category="system")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            SkillDefinition(metadata=SkillMetadata(name="valid"))
        with self.assertRaises(ValueError):
            SkillDefinition(
                metadata=SkillMetadata(name="valid"),
                factory=_TestSkill,
                implementation=_TestSkill(),
            )


class SkillRegistryTests(unittest.TestCase):
    """Verify registration, lookup, enumeration, and registry failures."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        self.event_bus.subscribe("skill.registered", self.events.append)
        self.logger = _CapturingLogger()
        self.registry = SkillRegistry(
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_register_find_list_exists_and_publish_event(self) -> None:
        second = _definition("system.second", category=SkillCategory.SYSTEM)
        first = _definition("core.first", category=SkillCategory.CORE)

        registered = self.registry.register(second)
        self.registry.register(first)

        self.assertIs(registered, second)
        self.assertIs(self.registry.find("system.second"), second)
        self.assertTrue(self.registry.exists("core.first"))
        self.assertFalse(self.registry.exists("missing"))
        self.assertEqual(
            [definition.name for definition in self.registry.list()],
            ["core.first", "system.second"],
        )
        self.assertEqual(self.registry.list(SkillCategory.SYSTEM), (second,))
        self.assertEqual(len(self.registry), 2)
        self.assertEqual(
            [event.name for event in self.events],
            ["skill.registered", "skill.registered"],
        )
        self.assertEqual(self.events[0].payload["name"], "system.second")
        self.assertTrue(
            any(message == "Skill registered" for _, message, _ in self.logger.entries)
        )

    def test_duplicate_registration_fails_without_replacing_definition(self) -> None:
        original = _definition("duplicate")
        self.registry.register(original)

        with self.assertRaises(DuplicateSkillError):
            self.registry.register(_definition("duplicate"))

        self.assertIs(self.registry.find("duplicate"), original)
        self.assertEqual(len(self.events), 1)

    def test_unregister_returns_definition_and_unknown_name_fails(self) -> None:
        definition = _definition("temporary")
        self.registry.register(definition)

        removed = self.registry.unregister("temporary")

        self.assertIs(removed, definition)
        self.assertFalse(self.registry.exists("temporary"))
        with self.assertRaises(SkillNotFoundError):
            self.registry.unregister("temporary")

    def test_registry_rejects_untyped_entries_and_invalid_queries(self) -> None:
        with self.assertRaises(TypeError):
            self.registry.register(object())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.registry.find(" skill ")
        with self.assertRaises(TypeError):
            self.registry.list("system")  # type: ignore[arg-type]

    def test_subscriber_failure_does_not_roll_back_registration(self) -> None:
        event_bus = EventBus()
        event_bus.subscribe(
            "skill.registered",
            lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")),
        )
        logger = _CapturingLogger()
        registry = SkillRegistry(logger=logger, event_bus=event_bus)

        registry.register(_definition("resilient"))

        self.assertTrue(registry.exists("resilient"))
        self.assertTrue(
            any(level is LogLevel.WARNING for level, _, _ in logger.entries)
        )


class SkillLoaderTests(unittest.TestCase):
    """Verify discovery and explicit skill lifecycle behavior."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        for event_name in ("skill.registered", "skill.loaded", "skill.unloaded"):
            self.event_bus.subscribe(event_name, self.events.append)
        self.logger = _CapturingLogger()
        self.registry = SkillRegistry(
            logger=self.logger,
            event_bus=self.event_bus,
        )
        self.loader = SkillLoader(
            self.registry,
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_discover_reads_registry_without_filesystem_scanning(self) -> None:
        definition = _definition("discoverable")
        self.registry.register(definition)

        discovered = self.loader.discover()

        self.assertEqual(discovered, (definition,))
        self.assertEqual([event.name for event in self.events], ["skill.registered"])

    def test_load_initializes_once_and_unload_shuts_down(self) -> None:
        skill = _TestSkill()
        self.registry.register(_definition("lifecycle", skill))

        loaded = self.loader.load("lifecycle")

        self.assertIs(loaded, skill)
        self.assertEqual(skill.initialize_calls, 1)
        self.assertEqual(skill.execute_calls, 0)
        self.assertTrue(self.loader.is_loaded("lifecycle"))
        self.assertIs(self.loader.find_loaded("lifecycle"), skill)
        self.assertEqual(self.loader.list_loaded(), (skill,))

        unloaded = self.loader.unload("lifecycle")

        self.assertIs(unloaded, skill)
        self.assertEqual(skill.shutdown_calls, 1)
        self.assertFalse(self.loader.is_loaded("lifecycle"))
        self.assertEqual(
            [event.name for event in self.events],
            ["skill.registered", "skill.loaded", "skill.unloaded"],
        )
        self.assertEqual(self.events[-1].payload["name"], "lifecycle")

    def test_duplicate_unknown_and_not_loaded_failures_are_explicit(self) -> None:
        self.registry.register(_definition("one"))
        self.loader.load("one")

        with self.assertRaises(SkillAlreadyLoadedError):
            self.loader.load("one")
        with self.assertRaises(SkillNotFoundError):
            self.loader.load("missing")
        with self.assertRaises(SkillNotLoadedError):
            self.loader.unload("missing")

    def test_factory_and_initialization_failures_do_not_mark_skill_loaded(self) -> None:
        def failing_factory() -> _TestSkill:
            raise RuntimeError("factory failed")

        self.registry.register(
            SkillDefinition(
                metadata=SkillMetadata(name="factory.failure"),
                factory=failing_factory,
            )
        )
        initialization_failure = _TestSkill(
            initialization_error=RuntimeError("initialize failed")
        )
        self.registry.register(
            _definition("initialization.failure", initialization_failure)
        )

        with self.assertRaises(SkillLoadError):
            self.loader.load("factory.failure")
        with self.assertRaises(SkillLoadError):
            self.loader.load("initialization.failure")

        self.assertFalse(self.loader.is_loaded("factory.failure"))
        self.assertFalse(self.loader.is_loaded("initialization.failure"))
        self.assertEqual(
            [event.name for event in self.events],
            ["skill.registered", "skill.registered"],
        )

    def test_incomplete_implementation_fails_contract_validation(self) -> None:
        self.registry.register(_definition("incomplete", _IncompleteSkill()))

        with self.assertRaises(SkillLoadError):
            self.loader.load("incomplete")

        self.assertFalse(self.loader.is_loaded("incomplete"))

    def test_shutdown_failure_preserves_loaded_state_for_retry(self) -> None:
        skill = _TestSkill(shutdown_error=RuntimeError("shutdown failed"))
        self.registry.register(_definition("shutdown.failure", skill))
        self.loader.load("shutdown.failure")

        with self.assertRaises(SkillUnloadError):
            self.loader.unload("shutdown.failure")

        self.assertTrue(self.loader.is_loaded("shutdown.failure"))
        self.assertEqual(
            [event.name for event in self.events],
            ["skill.registered", "skill.loaded"],
        )


class SkillManagerTests(unittest.TestCase):
    """Verify the manager coordinates one registry and loader cleanly."""

    def test_manager_provides_registration_discovery_and_lifecycle_api(self) -> None:
        event_bus = EventBus()
        events: list[SystemEvent] = []
        for event_name in ("skill.registered", "skill.loaded", "skill.unloaded"):
            event_bus.subscribe(event_name, events.append)
        manager = SkillManager(event_bus=event_bus)
        skill = _TestSkill()
        definition = _definition("managed", skill)

        manager.register(definition)
        loaded = manager.load("managed")

        self.assertTrue(manager.exists("managed"))
        self.assertIs(manager.find("managed"), definition)
        self.assertEqual(manager.list(), (definition,))
        self.assertEqual(manager.discover(), (definition,))
        self.assertIs(loaded, skill)
        self.assertIs(manager.find_loaded("managed"), skill)
        self.assertTrue(manager.is_loaded("managed"))
        self.assertEqual(manager.list_loaded(), (skill,))

        removed = manager.unregister("managed")

        self.assertIs(removed, definition)
        self.assertFalse(manager.exists("managed"))
        self.assertFalse(manager.is_loaded("managed"))
        self.assertEqual(skill.shutdown_calls, 1)
        self.assertEqual(
            [event.name for event in events],
            ["skill.registered", "skill.loaded", "skill.unloaded"],
        )

    def test_manager_accepts_injected_components_and_rejects_mismatch(self) -> None:
        registry = SkillRegistry()
        loader = SkillLoader(registry)

        manager = SkillManager(registry=registry, loader=loader)

        self.assertIs(manager.registry, registry)
        self.assertIs(manager.loader, loader)
        with self.assertRaises(ValueError):
            SkillManager(registry=SkillRegistry(), loader=loader)


if __name__ == "__main__":
    unittest.main()
