"""Comprehensive tests for Phase 9 Skill Framework Sprint 2."""

from __future__ import annotations

import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Skills.core import (
    CapabilityMatcher,
    CapabilityMatchResult,
    SkillCapability,
    SkillCategory,
    SkillDefinition,
    SkillDiscovery,
    SkillDiscoveryResult,
    SkillInterface,
    SkillManager,
    SkillMetadata,
    SkillRegistry,
    SkillResolutionResult,
    SkillResolver,
)


class _TestSkill(SkillInterface[object, object]):
    """Minimal lifecycle implementation for typed test definitions."""

    def initialize(self) -> None:
        return None

    def execute(self, request: object) -> object:
        return request

    def shutdown(self) -> None:
        return None


class _CapturingLogger:
    """Core-compatible structured logger used for stage assertions."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


def _definition(
    name: str,
    *capabilities: str,
    category: SkillCategory = SkillCategory.GENERAL,
    priority: int = 0,
    available: bool = True,
    preferred: bool = False,
    version: str = "1.0.0",
) -> SkillDefinition:
    """Build one deterministic typed definition."""

    return SkillDefinition(
        metadata=SkillMetadata(
            name=name,
            version=version,
            category=category,
            capabilities=tuple(SkillCapability(value) for value in capabilities),
            priority=priority,
            available=available,
            preferred=preferred,
        ),
        implementation=_TestSkill(),
    )


def _match(
    definition: SkillDefinition,
    *,
    requested: tuple[str, ...] = ("data.read",),
    matched: tuple[str, ...] = ("data.read",),
    score: float = 1.0,
) -> CapabilityMatchResult:
    """Build one complete precomputed match."""

    return CapabilityMatchResult(
        definition=definition,
        requested_capabilities=requested,
        matched_capabilities=matched,
        unmatched_capabilities=tuple(
            capability
            for capability in requested
            if capability not in matched
        ),
        capability_score=score,
    )


class Sprint2ModelTests(unittest.TestCase):
    """Verify the extended metadata and immutable result models."""

    def test_metadata_supports_priority_availability_and_preferred_flag(self) -> None:
        metadata = SkillMetadata(
            name="data.reader",
            priority=7,
            available=False,
            preferred=True,
        )
        definition = SkillDefinition(metadata=metadata, implementation=_TestSkill())

        self.assertEqual(metadata.priority, 7)
        self.assertFalse(metadata.available)
        self.assertFalse(metadata.availability)
        self.assertTrue(metadata.preferred)
        self.assertEqual(definition.priority, 7)
        self.assertFalse(definition.available)
        self.assertTrue(definition.preferred)

    def test_metadata_rejects_invalid_resolution_fields(self) -> None:
        with self.assertRaises(TypeError):
            SkillMetadata(name="invalid", priority=True)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            SkillMetadata(name="invalid", available=1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            SkillMetadata(name="invalid", preferred="yes")  # type: ignore[arg-type]

    def test_match_and_resolution_results_expose_typed_aliases(self) -> None:
        definition = _definition("reader", "data.read")
        match = _match(definition)
        result = SkillResolutionResult(
            decision="resolved",
            reason_code="skill_selected",
            reason="Selected.",
            requested_capabilities=("data.read",),
            selected=match,
            candidates=(match,),
        )

        self.assertEqual(match.capability_score, 1.0)
        self.assertEqual(match.score, 1.0)
        self.assertTrue(match.exact_match)
        self.assertFalse(match.partial_match)
        self.assertTrue(result.resolved)
        self.assertIs(result.selected_match, match)
        self.assertIs(result.skill, definition)
        self.assertIs(result.selected_skill, definition)


class SkillDiscoveryTests(unittest.TestCase):
    """Verify registered-skill filtering, events, logging, and failures."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        self.event_bus.subscribe("skill.discovered", self.events.append)
        self.logger = _CapturingLogger()
        self.registry = SkillRegistry()
        self.discovery = SkillDiscovery(
            self.registry,
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_discovers_registered_skills_in_deterministic_typed_order(self) -> None:
        second = _definition("zulu.reader", "data.read")
        first = _definition("alpha.reader", "data.read")
        self.registry.register(second)
        self.registry.register(first)

        results = self.discovery.discover()

        self.assertTrue(all(isinstance(item, SkillDiscoveryResult) for item in results))
        self.assertEqual([item.name for item in results], ["alpha.reader", "zulu.reader"])
        self.assertEqual(
            [event.payload["name"] for event in self.events],
            ["alpha.reader", "zulu.reader"],
        )
        self.assertTrue(
            any(
                message == "Skill discovery started"
                for _, message, _ in self.logger.entries
            )
        )
        self.assertTrue(
            any(
                message == "Skill discovery completed"
                for _, message, _ in self.logger.entries
            )
        )

    def test_filters_by_category_and_all_requested_capabilities(self) -> None:
        complete = _definition(
            "data.complete",
            "data.read",
            "data.write",
            category=SkillCategory.INFORMATION,
        )
        partial = _definition(
            "data.partial",
            "data.read",
            category=SkillCategory.INFORMATION,
        )
        other = _definition(
            "system.complete",
            "data.read",
            "data.write",
            category=SkillCategory.SYSTEM,
        )
        for definition in (partial, other, complete):
            self.registry.register(definition)

        results = self.discovery.discover(
            category=SkillCategory.INFORMATION,
            capabilities=("data.read", "data.write"),
        )

        self.assertEqual([item.name for item in results], ["data.complete"])
        self.assertEqual(
            results[0].matched_capabilities,
            ("data.read", "data.write"),
        )

    def test_supports_partial_capability_and_availability_filters(self) -> None:
        available = _definition("available", "data.read")
        unavailable = _definition("unavailable", "data.write", available=False)
        self.registry.register(unavailable)
        self.registry.register(available)

        partial = self.discovery.discover(
            capabilities=("data.read", "data.write"),
            require_all_capabilities=False,
        )
        available_only = self.discovery.discover(available_only=True)
        unavailable_only = self.discovery.discover(availability=False)

        self.assertEqual([item.name for item in partial], ["available", "unavailable"])
        self.assertEqual([item.name for item in available_only], ["available"])
        self.assertEqual([item.name for item in unavailable_only], ["unavailable"])

    def test_rejects_invalid_filters(self) -> None:
        with self.assertRaises(TypeError):
            self.discovery.discover(category="system")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.discovery.discover(capabilities=(" data.read",))
        with self.assertRaises(ValueError):
            self.discovery.discover(
                available=False,
                available_only=True,
            )
        with self.assertRaises(ValueError):
            self.discovery.discover(available=True, availability=False)

    def test_event_subscriber_failure_does_not_change_discovery_result(self) -> None:
        event_bus = EventBus()
        event_bus.subscribe(
            "skill.discovered",
            lambda event: (_ for _ in ()).throw(RuntimeError("failed")),
        )
        logger = _CapturingLogger()
        registry = SkillRegistry()
        registry.register(_definition("resilient", "data.read"))
        discovery = SkillDiscovery(registry, logger=logger, event_bus=event_bus)

        results = discovery.discover()

        self.assertEqual([item.name for item in results], ["resilient"])
        self.assertTrue(any(level is LogLevel.WARNING for level, _, _ in logger.entries))


class CapabilityMatcherTests(unittest.TestCase):
    """Verify scoring, partial matching, ranking, and match failures."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        self.event_bus.subscribe("skill.matched", self.events.append)
        self.logger = _CapturingLogger()
        self.matcher = CapabilityMatcher(
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_scores_exact_and_partial_matches_and_ranks_deterministically(self) -> None:
        exact_zulu = _definition("zulu", "data.read", "data.write")
        partial = _definition("middle", "data.read")
        exact_alpha = _definition("alpha", "data.read", "data.write")

        matches = self.matcher.match(
            ("data.read", "data.write"),
            (exact_zulu, partial, exact_alpha),
        )

        self.assertEqual([match.name for match in matches], ["alpha", "zulu", "middle"])
        self.assertEqual([match.capability_score for match in matches], [1.0, 1.0, 0.5])
        self.assertTrue(matches[0].exact_match)
        self.assertTrue(matches[-1].partial_match)
        self.assertEqual([event.payload["rank"] for event in self.events], [1, 2, 3])

    def test_ranking_is_independent_of_candidate_input_order(self) -> None:
        alpha = _definition("alpha", "data.read")
        zulu = _definition("zulu", "data.read")

        forward = self.matcher.match("data.read", (alpha, zulu))
        reverse = self.matcher.match("data.read", (zulu, alpha))

        self.assertEqual([item.name for item in forward], ["alpha", "zulu"])
        self.assertEqual([item.name for item in reverse], ["alpha", "zulu"])

    def test_can_require_exact_matches_or_a_minimum_partial_score(self) -> None:
        exact = _definition("exact", "a", "b", "c")
        partial_high = _definition("partial.high", "a", "b")
        partial_low = _definition("partial.low", "a")

        exact_only = self.matcher.match(
            ("a", "b", "c"),
            (partial_high, exact),
            allow_partial=False,
        )
        threshold = self.matcher.match(
            ("a", "b", "c"),
            (partial_low, partial_high),
            minimum_score=0.6,
        )

        self.assertEqual([item.name for item in exact_only], ["exact"])
        self.assertEqual([item.name for item in threshold], ["partial.high"])

    def test_excludes_unavailable_skills_by_default_but_can_score_them(self) -> None:
        unavailable = _definition("offline", "data.read", available=False)

        default = self.matcher.match("data.read", (unavailable,))
        included = self.matcher.match(
            "data.read",
            (unavailable,),
            available_only=False,
        )

        self.assertEqual(default, ())
        self.assertEqual([match.name for match in included], ["offline"])
        self.assertFalse(included[0].availability)

    def test_normalizes_duplicate_requested_capabilities_case_insensitively(self) -> None:
        definition = _definition("reader", "Data.Read")

        matches = self.matcher.match(
            ("data.read", "DATA.READ"),
            (definition,),
        )

        self.assertEqual(matches[0].requested_capabilities, ("data.read",))
        self.assertEqual(matches[0].capability_score, 1.0)

    def test_discovery_injection_supplies_registered_candidates(self) -> None:
        registry = SkillRegistry()
        registry.register(_definition("reader", "data.read"))
        event_bus = EventBus()
        discovered_events: list[SystemEvent] = []
        matched_events: list[SystemEvent] = []
        event_bus.subscribe("skill.discovered", discovered_events.append)
        event_bus.subscribe("skill.matched", matched_events.append)
        discovery = SkillDiscovery(registry, event_bus=event_bus)
        matcher = CapabilityMatcher(discovery, event_bus=event_bus)

        matches = matcher.match("data.read")

        self.assertEqual([match.name for match in matches], ["reader"])
        self.assertEqual(len(discovered_events), 1)
        self.assertEqual(len(matched_events), 1)

    def test_rejects_invalid_requests_candidates_and_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            self.matcher.match(())
        with self.assertRaises(ValueError):
            self.matcher.match((" ",))
        with self.assertRaises(TypeError):
            self.matcher.match("data.read", (object(),))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.matcher.match("data.read", (), minimum_score=1.1)

    def test_rank_removes_exact_duplicate_match_records(self) -> None:
        match = _match(_definition("reader", "data.read"))

        ranked = self.matcher.rank((match, match))

        self.assertEqual(ranked, (match,))


class SkillResolverTests(unittest.TestCase):
    """Verify selection, priority, preference, duplicates, and failures."""

    def setUp(self) -> None:
        self.event_bus = EventBus()
        self.events: list[SystemEvent] = []
        self.event_bus.subscribe("skill.resolved", self.events.append)
        self.logger = _CapturingLogger()
        self.matcher = CapabilityMatcher()
        self.resolver = SkillResolver(
            self.matcher,
            logger=self.logger,
            event_bus=self.event_bus,
        )

    def test_selects_highest_capability_score_before_other_tie_breakers(self) -> None:
        exact = _definition("exact", "a", "b", priority=0)
        partial = _definition("partial", "a", priority=100, preferred=True)

        result = self.resolver.resolve(("a", "b"), (partial, exact))

        self.assertTrue(result.resolved)
        self.assertEqual(result.selected_skill.name, "exact")  # type: ignore[union-attr]

    def test_priority_resolves_equal_capability_candidates(self) -> None:
        lower = _definition("lower", "data.read", priority=1)
        higher = _definition("higher", "data.read", priority=10)

        result = self.resolver.resolve("data.read", (lower, higher))

        self.assertEqual(result.selected_skill.name, "higher")  # type: ignore[union-attr]
        self.assertEqual([candidate.name for candidate in result.candidates], ["higher", "lower"])

    def test_metadata_preferred_flag_resolves_equal_score_before_priority(self) -> None:
        priority = _definition("priority", "data.read", priority=100)
        preferred = _definition("preferred", "data.read", preferred=True)

        result = self.resolver.resolve("data.read", (priority, preferred))

        self.assertEqual(result.selected_skill.name, "preferred")  # type: ignore[union-attr]

    def test_explicit_preferred_skill_order_resolves_equal_candidates(self) -> None:
        alpha = _definition("alpha", "data.read", preferred=True, priority=100)
        beta = _definition("beta", "data.read")
        gamma = _definition("gamma", "data.read")

        result = self.resolver.resolve(
            "data.read",
            (alpha, beta, gamma),
            preferred_skills=("gamma", "beta"),
        )

        self.assertEqual(result.selected_skill.name, "gamma")  # type: ignore[union-attr]
        self.assertTrue(self.events[-1].payload["preferred"])

    def test_name_is_stable_final_tie_breaker(self) -> None:
        zulu = _definition("zulu", "data.read")
        alpha = _definition("alpha", "data.read")

        first = self.resolver.resolve("data.read", (zulu, alpha))
        second = self.resolver.resolve("data.read", (alpha, zulu))

        self.assertEqual(first.selected_skill.name, "alpha")  # type: ignore[union-attr]
        self.assertEqual(second.selected_skill.name, "alpha")  # type: ignore[union-attr]

    def test_duplicate_skill_candidates_are_collapsed_after_best_variant_wins(self) -> None:
        lower = _definition("duplicate", "data.read", priority=1)
        higher = _definition("duplicate", "data.read", priority=5)
        other = _definition("other", "data.read", priority=0)

        result = self.resolver.resolve("data.read", (lower, other, higher))

        self.assertEqual(result.selected_skill.priority, 5)  # type: ignore[union-attr]
        self.assertEqual(
            [candidate.name for candidate in result.candidates],
            ["duplicate", "other"],
        )
        self.assertTrue(
            any(
                message == "Duplicate skill resolution candidate removed"
                for _, message, _ in self.logger.entries
            )
        )

    def test_unavailable_only_candidates_return_structured_failure(self) -> None:
        unavailable = _definition("offline", "data.read", available=False)
        match = _match(unavailable)

        result = self.resolver.resolve_matches((match,))

        self.assertFalse(result.resolved)
        self.assertEqual(result.decision, "unresolved")
        self.assertEqual(result.reason_code, "no_available_skill")
        self.assertIsNone(result.selected)
        self.assertEqual(self.events[-1].payload["decision"], "unresolved")

    def test_no_matching_skill_returns_structured_failure(self) -> None:
        result = self.resolver.resolve("data.write", (_definition("reader", "data.read"),))

        self.assertFalse(result.resolved)
        self.assertEqual(result.reason_code, "no_matching_skill")
        self.assertEqual(result.candidates, ())

    def test_category_filter_is_applied_before_matching(self) -> None:
        system = _definition(
            "system.reader",
            "data.read",
            category=SkillCategory.SYSTEM,
            priority=100,
        )
        information = _definition(
            "information.reader",
            "data.read",
            category=SkillCategory.INFORMATION,
        )

        result = self.resolver.resolve(
            "data.read",
            (system, information),
            category=SkillCategory.INFORMATION,
        )

        self.assertEqual(
            result.selected_skill.name,  # type: ignore[union-attr]
            "information.reader",
        )

    def test_can_resolve_precomputed_matches_directly(self) -> None:
        lower = _match(_definition("lower", "data.read", priority=1))
        higher = _match(_definition("higher", "data.read", priority=5))

        result = self.resolver.resolve((lower, higher))

        self.assertEqual(result.selected_skill.name, "higher")  # type: ignore[union-attr]

    def test_rejects_mixed_requests_and_invalid_preference_values(self) -> None:
        first = _match(_definition("first", "a"), requested=("a",), matched=("a",))
        second = _match(_definition("second", "b"), requested=("b",), matched=("b",))

        with self.assertRaises(ValueError):
            self.resolver.resolve_matches((first, second))
        with self.assertRaises(ValueError):
            self.resolver.resolve_matches((first,), preferred_skills=(" bad",))

    def test_event_failure_does_not_change_resolution_and_logs_warning(self) -> None:
        event_bus = EventBus()
        event_bus.subscribe(
            "skill.resolved",
            lambda event: (_ for _ in ()).throw(RuntimeError("failed")),
        )
        logger = _CapturingLogger()
        resolver = SkillResolver(
            CapabilityMatcher(),
            logger=logger,
            event_bus=event_bus,
        )

        result = resolver.resolve(
            "data.read",
            (_definition("reader", "data.read"),),
        )

        self.assertTrue(result.resolved)
        self.assertTrue(any(level is LogLevel.WARNING for level, _, _ in logger.entries))


class SkillManagerSprint2Tests(unittest.TestCase):
    """Verify manager composition while retaining Sprint 1 behavior."""

    def test_manager_composes_discovery_matching_and_resolution_services(self) -> None:
        event_bus = EventBus()
        manager = SkillManager(event_bus=event_bus)
        definition = _definition("managed.reader", "data.read", priority=3)
        manager.register(definition)

        legacy = manager.discover()
        discovered = manager.discover_skills(capabilities="data.read")
        matches = manager.match("data.read")
        resolution = manager.resolve("data.read")

        self.assertEqual(legacy, (definition,))
        self.assertEqual([item.name for item in discovered], ["managed.reader"])
        self.assertEqual([item.name for item in matches], ["managed.reader"])
        self.assertIs(resolution.selected_skill, definition)
        self.assertIs(manager.matcher.discovery, manager.discovery_service)
        self.assertIs(manager.resolver.matcher, manager.matcher)

    def test_manager_rejects_mismatched_intelligent_services(self) -> None:
        registry = SkillRegistry()
        other_registry = SkillRegistry()
        discovery = SkillDiscovery(other_registry)
        matcher = CapabilityMatcher(discovery)
        resolver = SkillResolver(matcher)

        with self.assertRaises(ValueError):
            SkillManager(registry=registry, discovery=discovery)
        with self.assertRaises(ValueError):
            SkillManager(
                registry=registry,
                discovery=SkillDiscovery(registry),
                matcher=matcher,
            )
        with self.assertRaises(ValueError):
            SkillManager(
                registry=registry,
                discovery=SkillDiscovery(registry),
                matcher=CapabilityMatcher(SkillDiscovery(registry)),
                resolver=resolver,
            )


if __name__ == "__main__":
    unittest.main()
