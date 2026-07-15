"""Compatibility tests for Version 1.4 Milestone 2 Sprint 2."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import os
import unittest
from unittest import mock

from AI import (
    AIManager,
    AIRequest,
    ContextSizeMetadata,
    CostMetadata,
    LatencyMetadata,
    LegacyProviderAdapter,
    LegacyProviderAdapterFactory,
    LegacyProviderCompatibilityError,
    LegacyProviderRegistrar,
    LegacyProviderRegistrationError,
    ProviderCapability,
    ProviderPriority,
    ProviderStatus,
)
from AI.providers import (
    ClaudeProvider,
    FallbackProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    Provider,
    ProviderResponse,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent


class _UnsupportedProvider(Provider):
    """Valid legacy shape that has no approved compatibility profile."""

    name = "unsupported"

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> ProviderResponse:
        raise AssertionError("compatibility inspection must not execute providers")


class _Clock:
    """Deterministic clock for immutable adapter snapshots."""

    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _CapturingLogger:
    """Core logger double with optional failure behavior."""

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []
        self.fail = fail

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        if self.fail:
            raise RuntimeError("logger unavailable")
        self.entries.append((level, message, context))


class _SecondRegistrationFails:
    """Injected manager double used to verify atomic rollback."""

    def __init__(self) -> None:
        self.manager = AIManager()
        self.calls = 0

    def register_provider(self, provider: object):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("registry unavailable")
        return self.manager.register_provider(provider)

    def unregister_provider(self, provider_id: str):
        return self.manager.unregister_provider(provider_id)

    def list_providers(self):
        return self.manager.list_providers()


class LegacyProviderAdapterTests(unittest.TestCase):
    """Verify safe metadata conversion for every built-in provider."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.factory = LegacyProviderAdapterFactory(clock=self.clock)

    def test_all_builtin_providers_map_to_typed_immutable_metadata(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            providers = (
                OpenAIProvider(api_key="configured", timeout_seconds=11, max_retries=2),
                GeminiProvider(api_key="configured", timeout_seconds=12, max_retries=3),
                ClaudeProvider(api_key="configured", timeout_seconds=13, max_retries=4),
                OllamaProvider(timeout_seconds=14, max_retries=5),
            )
            expected = (
                ("openai", "gpt-4o-mini"),
                ("gemini", "gemini-2.0-flash"),
                ("claude", "claude-3-5-haiku-latest"),
                ("ollama", "llama3.2"),
            )

            for provider, (provider_id, model) in zip(providers, expected):
                with self.subTest(provider=provider_id):
                    adapter = self.factory.adapt(provider)
                    attributes = adapter.metadata.attributes

                    self.assertIsInstance(adapter, LegacyProviderAdapter)
                    self.assertEqual(adapter.provider_id, provider_id)
                    self.assertEqual(adapter.metadata.supported_models, (model,))
                    self.assertEqual(adapter.metadata.capabilities, (
                        ProviderCapability.CHAT,
                        ProviderCapability.TEXT_GENERATION,
                    ))
                    self.assertNotIn(
                        ProviderCapability.STREAMING,
                        adapter.metadata.capabilities,
                    )
                    self.assertIs(adapter.metadata.priority, ProviderPriority.NORMAL)
                    self.assertIs(adapter.health.status, ProviderStatus.DEGRADED)
                    self.assertEqual(adapter.health.checked_at, self.clock.now)
                    self.assertTrue(adapter.health.selectable)
                    self.assertIsInstance(attributes["cost_metadata"], CostMetadata)
                    self.assertTrue(attributes["cost_metadata"].known)
                    self.assertIsInstance(attributes["latency_metadata"], LatencyMetadata)
                    self.assertFalse(attributes["latency_metadata"].known)
                    self.assertIsInstance(
                        attributes["context_size_metadata"],
                        ContextSizeMetadata,
                    )
                    self.assertFalse(attributes["context_size_metadata"].known)
                    self.assertFalse(attributes["network_checked"])
                    self.assertTrue(attributes["local_fallback_available"])

    def test_environment_model_hints_are_snapshotted_without_network_access(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_MODEL": "configured-openai-model",
                "ANTHROPIC_MODEL": "configured-claude-model",
                "OLLAMA_MODEL": "configured-ollama-model",
            },
            clear=True,
        ):
            adapters = tuple(
                self.factory.adapt(provider)
                for provider in (
                    OpenAIProvider(api_key="configured"),
                    ClaudeProvider(api_key="configured"),
                    OllamaProvider(),
                )
            )

        self.assertEqual(
            tuple(item.metadata.supported_models[0] for item in adapters),
            (
                "configured-openai-model",
                "configured-claude-model",
                "configured-ollama-model",
            ),
        )

    def test_adapter_never_copies_credentials_or_executable_provider_state(self) -> None:
        secret = "test-secret-that-must-not-be-copied"
        adapter = self.factory.adapt(OpenAIProvider(api_key=secret))
        serialized = repr((adapter.metadata, adapter.health))

        self.assertNotIn(secret, serialized)
        self.assertFalse(hasattr(adapter, "complete_chat"))
        self.assertFalse(hasattr(adapter, "generate_response"))
        self.assertFalse(hasattr(adapter, "legacy_provider"))
        with self.assertRaises(FrozenInstanceError):
            adapter.metadata = adapter.metadata  # type: ignore[misc]
        with self.assertRaises(TypeError):
            adapter.metadata.attributes["network_checked"] = True  # type: ignore[index]

    def test_health_uses_configuration_and_prior_failure_facts_only(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = OpenAIProvider(api_key="")
        provider.last_error = "remote failure with sensitive details"
        adapter = self.factory.adapt(provider)

        self.assertEqual(adapter.health.consecutive_failures, 1)
        self.assertTrue(adapter.health.details["previous_failure_recorded"])
        self.assertFalse(adapter.health.details["credentials_configured"])
        self.assertNotIn(provider.last_error, repr(adapter.health))
        self.assertFalse(adapter.health.details["network_checked"])

    def test_cost_metadata_matches_existing_deterministic_usage_estimator(self) -> None:
        provider = ClaudeProvider(api_key="configured")
        adapter = self.factory.adapt(provider)
        cost = adapter.metadata.attributes["cost_metadata"]

        self.assertEqual(
            cost.input_cost_per_1000_tokens,
            provider._estimate_cost(1000, 0, model="claude-3-5-haiku-latest"),
        )
        self.assertEqual(
            cost.output_cost_per_1000_tokens,
            provider._estimate_cost(0, 1000, model="claude-3-5-haiku-latest"),
        )

    def test_local_fallback_response_remains_unchanged_and_network_free(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = OpenAIProvider(api_key="")
            response = asyncio.run(
                provider.complete_chat(
                    [{"role": "user", "content": "hello"}],
                    system_prompt="system",
                )
            )

        self.assertTrue(response.is_fallback)
        self.assertEqual(response.provider_name, "openai")
        self.assertEqual(response.usage.cost_usd, 0.0)
        self.assertEqual(
            response.content,
            "OpenAI API key not configured; using local fallback.\n"
            "System prompt: system\nLatest request: hello",
        )

    def test_invalid_and_unsupported_providers_fail_closed(self) -> None:
        invalid_timeout = OpenAIProvider(api_key="configured")
        invalid_timeout.timeout_seconds = 0
        invalid_identity = OpenAIProvider(api_key="configured")
        invalid_identity.name = "renamed"
        invalid_url = OpenAIProvider(api_key="configured")
        invalid_url.base_url = "not-a-url"

        for provider in (
            _UnsupportedProvider(),
            invalid_timeout,
            invalid_identity,
            invalid_url,
        ):
            with self.subTest(provider=type(provider).__name__):
                with self.assertRaises(LegacyProviderCompatibilityError):
                    self.factory.adapt_chain(provider)

    def test_fallback_wrappers_must_be_adapted_as_chains(self) -> None:
        wrapper = FallbackProvider([OpenAIProvider(api_key="configured")])
        with self.assertRaises(LegacyProviderCompatibilityError):
            self.factory.adapt(wrapper)

    def test_empty_duplicate_and_cyclic_fallback_chains_fail_closed(self) -> None:
        empty = FallbackProvider([])
        duplicate = FallbackProvider([
            OpenAIProvider(api_key="configured"),
            OpenAIProvider(api_key="configured"),
        ])
        cyclic = FallbackProvider([])
        cyclic.providers.append(cyclic)

        for wrapper in (empty, duplicate, cyclic):
            with self.subTest(case=repr(wrapper.providers)):
                with self.assertRaises(LegacyProviderCompatibilityError):
                    self.factory.adapt_chain(wrapper)

    def test_nested_fallback_chain_preserves_exact_legacy_order(self) -> None:
        nested = FallbackProvider([
            ClaudeProvider(api_key="configured"),
            FallbackProvider([
                OpenAIProvider(api_key="configured"),
                GeminiProvider(api_key="configured"),
            ]),
        ])
        adapters = self.factory.adapt_chain(nested)

        self.assertEqual(
            tuple(item.provider_id for item in adapters),
            ("claude", "openai", "gemini"),
        )
        self.assertEqual(
            tuple(item.metadata.priority for item in adapters),
            (
                ProviderPriority.HIGHEST,
                ProviderPriority.HIGH,
                ProviderPriority.NORMAL,
            ),
        )
        self.assertEqual(
            tuple(item.metadata.attributes["fallback_order"] for item in adapters),
            (0, 1, 2),
        )

    def test_invalid_clock_and_dependencies_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            LegacyProviderAdapterFactory(clock=None)  # type: ignore[arg-type]
        with self.assertRaises(LegacyProviderCompatibilityError):
            LegacyProviderAdapterFactory(clock=lambda: datetime.now()).adapt(
                OpenAIProvider(api_key="configured")
            )
        with self.assertRaises(TypeError):
            LegacyProviderRegistrar(object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            LegacyProviderRegistrar(AIManager(), adapter_factory=object())  # type: ignore[arg-type]


class LegacyProviderRegistrationTests(unittest.TestCase):
    """Verify manager, registry, routing, events, and fail-closed registration."""

    def test_registration_uses_manager_events_and_phase13_registry(self) -> None:
        bus = EventBus()
        events: list[SystemEvent] = []
        bus.subscribe("ai.provider_registered", events.append)
        manager = AIManager(event_bus=bus)
        provider = OpenAIProvider(api_key="configured")

        registered = LegacyProviderRegistrar(manager).register(provider)

        self.assertEqual(registered, manager.list_providers())
        self.assertEqual(manager.registry.get("openai"), registered[0])
        self.assertEqual([event.name for event in events], ["ai.provider_registered"])
        self.assertEqual(events[0].payload["provider_id"], "openai")
        self.assertNotIn("configured", repr(events[0]))

    def test_routing_and_fallback_chain_match_legacy_wrapper_order(self) -> None:
        legacy = FallbackProvider([
            ClaudeProvider(api_key="configured"),
            OpenAIProvider(api_key="configured"),
            GeminiProvider(api_key="configured"),
        ])
        manager = AIManager()
        LegacyProviderRegistrar(manager).register(legacy)

        decision = manager.route_request(
            AIRequest(
                prompt="route only",
                required_capabilities=(ProviderCapability.CHAT,),
                request_id="compatibility-request",
            )
        )
        first_fallback = manager.fallback_provider(decision)
        second_fallback = manager.fallback_provider(decision, "openai")

        self.assertEqual(decision.selected_provider_id, "claude")
        self.assertEqual(decision.fallback_chain, ("openai", "gemini"))
        self.assertEqual(first_fallback.provider_id, "openai")
        self.assertEqual(second_fallback.provider_id, "gemini")

    def test_orchestrator_consumes_typed_metadata_without_provider_execution(self) -> None:
        legacy = OpenAIProvider(api_key="configured")
        manager = AIManager()
        LegacyProviderRegistrar(manager).register(legacy)

        resolution = manager.resolve_preferences(
            AIRequest(prompt="metadata only", request_id="metadata-request")
        )

        self.assertEqual(resolution.selected_option.provider_id, "openai")
        self.assertTrue(resolution.selected_option.cost.known)
        self.assertFalse(resolution.selected_option.latency.known)
        self.assertFalse(resolution.selected_option.context_size.known)
        self.assertEqual(legacy.request_count, 0)

    def test_incompatible_chain_registers_nothing_in_non_strict_mode(self) -> None:
        manager = AIManager()
        logger = _CapturingLogger()
        legacy = FallbackProvider([
            OpenAIProvider(api_key="configured"),
            _UnsupportedProvider(),
        ])

        registered = LegacyProviderRegistrar(
            manager,
            logger=logger,
        ).register(legacy, strict=False)

        self.assertEqual(registered, ())
        self.assertEqual(manager.list_providers(), ())
        self.assertEqual(logger.entries[0][0], LogLevel.WARNING)
        self.assertNotIn("configured", repr(logger.entries))

    def test_strict_mode_surfaces_compatibility_failure(self) -> None:
        with self.assertRaises(LegacyProviderCompatibilityError):
            LegacyProviderRegistrar(AIManager()).register(_UnsupportedProvider())

    def test_existing_identifier_conflict_leaves_registry_unchanged(self) -> None:
        manager = AIManager()
        registrar = LegacyProviderRegistrar(manager)
        first = registrar.register(OpenAIProvider(api_key="configured"))

        with self.assertRaises(LegacyProviderRegistrationError):
            registrar.register(OpenAIProvider(api_key="configured"))

        self.assertEqual(manager.list_providers(), first)

    def test_partial_manager_failure_rolls_back_all_compatibility_entries(self) -> None:
        manager = _SecondRegistrationFails()
        legacy = FallbackProvider([
            OpenAIProvider(api_key="configured"),
            GeminiProvider(api_key="configured"),
        ])

        registered = LegacyProviderRegistrar(manager).register(
            legacy,
            strict=False,
        )

        self.assertEqual(registered, ())
        self.assertEqual(manager.list_providers(), ())

    def test_logger_failure_does_not_change_fail_closed_result(self) -> None:
        manager = AIManager()
        registered = LegacyProviderRegistrar(
            manager,
            logger=_CapturingLogger(fail=True),
        ).register(_UnsupportedProvider(), strict=False)

        self.assertEqual(registered, ())
        self.assertEqual(manager.list_providers(), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
