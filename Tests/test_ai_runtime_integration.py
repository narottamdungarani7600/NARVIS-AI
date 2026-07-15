"""Integration tests for Version 1.4 Milestone 2 Sprint 3."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest import mock
from uuid import uuid4

from AI import (
    AIManager,
    AIProvider,
    AI_RUNTIME_METADATA_KEY,
    AI_RUNTIME_METADATA_SCHEMA,
    AIRuntimeAdapterStateError,
    AIRuntimeLifecycleAdapter,
    AIRuntimeMetadata,
    AIRuntimeProviderMetadata,
    AIRuntimeSessionBindingError,
    ConversationAIRuntimeAdapter,
    ProviderHealth,
    ProviderMetadata,
    ProviderPriority,
    ProviderStatus,
)
from Conversation import ConversationManager
from Core.system import ComponentState, EventBus, SystemEvent
from narvis import NARVISApplication, NARVISConfig


class _CapturingLogger:
    """Small Core logger double used to keep focused tests quiet."""

    def __init__(self) -> None:
        self.entries: list[tuple[object, str, dict[str, object]]] = []

    def log(self, level: object, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


def _provider(
    provider_id: str,
    *,
    status: ProviderStatus,
    priority: ProviderPriority,
) -> AIProvider:
    checked_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    return AIProvider(
        metadata=ProviderMetadata(
            name=provider_id,
            priority=priority,
        ),
        health=ProviderHealth(
            provider_id=provider_id,
            status=status,
            checked_at=checked_at,
        ),
        registered_at=checked_at,
    )


class ConversationAIRuntimeAdapterTests(unittest.TestCase):
    """Verify typed metadata and one-way lifecycle coordination."""

    def setUp(self) -> None:
        self.bus = EventBus()
        self.logger = _CapturingLogger()
        self.manager = AIManager(event_bus=self.bus, logger=self.logger)
        self.conversations = ConversationManager(
            event_bus=self.bus,
            logger=self.logger,
        )
        self.adapter = ConversationAIRuntimeAdapter(
            self.manager,
            self.conversations,
            logger=self.logger,
        )

    def test_binding_requires_explicit_lifecycle_start(self) -> None:
        with self.assertRaises(AIRuntimeAdapterStateError):
            self.adapter.bind_session("conversation-1", "owner-1")

        self.adapter.start()
        session = self.adapter.bind_session("conversation-1", "owner-1")

        self.assertEqual(session.session_id, "conversation-1")
        self.assertEqual(self.adapter.binding_count, 1)

    def test_conversation_exposes_detached_typed_runtime_metadata(self) -> None:
        self.manager.register_provider(
            _provider(
                "secondary",
                status=ProviderStatus.UNAVAILABLE,
                priority=ProviderPriority.LOW,
            )
        )
        self.manager.register_provider(
            _provider(
                "primary",
                status=ProviderStatus.AVAILABLE,
                priority=ProviderPriority.HIGH,
            )
        )
        self.adapter.start()

        session = self.adapter.bind_session("conversation-1", "owner-1")
        metadata = self.adapter.runtime_metadata("conversation-1")
        stored = session.metadata[AI_RUNTIME_METADATA_KEY]

        self.assertIsInstance(metadata, AIRuntimeMetadata)
        self.assertEqual(metadata.schema, AI_RUNTIME_METADATA_SCHEMA)
        self.assertEqual(metadata.provider_ids, ("primary", "secondary"))
        self.assertEqual(metadata.selectable_provider_ids, ("primary",))
        self.assertTrue(metadata.routing_ready)
        self.assertTrue(metadata.architecture_only)
        self.assertFalse(metadata.provider_execution_enabled)
        self.assertEqual(stored["orchestration_session_id"], "conversation-1")
        self.assertEqual(stored["owner_id"], "owner-1")
        self.assertEqual(stored["provider_ids"], ("primary", "secondary"))
        self.assertFalse(stored["provider_execution_enabled"])
        self.assertFalse(hasattr(metadata.providers[0], "complete_chat"))
        with self.assertRaises(TypeError):
            stored["provider_execution_enabled"] = True  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            metadata.owner_id = "changed"  # type: ignore[misc]

    def test_binding_publishes_each_domain_event_through_one_existing_path(self) -> None:
        events: list[SystemEvent] = []
        for name in (
            "ai.session_created",
            "ai.session_completed",
            "conversation.created",
            "conversation.updated",
        ):
            self.bus.subscribe(name, events.append)
        self.adapter.start()

        first = self.adapter.bind_session("conversation-1", "owner-1")
        second = self.adapter.bind_session("conversation-1", "owner-1")
        completed = self.adapter.complete_session("conversation-1")
        repeated = self.adapter.complete_session("conversation-1")

        self.assertEqual(first, second)
        self.assertEqual(completed, repeated)
        self.assertEqual(
            [event.name for event in events],
            [
                "ai.session_created",
                "conversation.created",
                "ai.session_completed",
                "conversation.updated",
            ],
        )
        self.assertNotIn(AI_RUNTIME_METADATA_KEY, repr(events))
        self.assertNotIn("provider_execution_enabled", repr(events))

    def test_unavailable_providers_remain_fail_closed_and_unexecuted(self) -> None:
        self.manager.register_provider(
            _provider(
                "offline",
                status=ProviderStatus.UNAVAILABLE,
                priority=ProviderPriority.HIGHEST,
            )
        )
        self.adapter.start()

        with mock.patch.object(
            self.manager,
            "route_request",
            side_effect=AssertionError("runtime binding must not route"),
        ), mock.patch.object(
            self.manager,
            "plan_request",
            side_effect=AssertionError("runtime binding must not plan"),
        ), mock.patch.object(
            self.manager,
            "select_provider",
            side_effect=AssertionError("runtime binding must not select"),
        ):
            self.adapter.bind_session("conversation-1", "owner-1")
            metadata = self.adapter.runtime_metadata("conversation-1")

        self.assertEqual(metadata.provider_ids, ("offline",))
        self.assertEqual(metadata.selectable_provider_ids, ())
        self.assertFalse(metadata.routing_ready)
        self.assertFalse(metadata.provider_execution_enabled)

    def test_existing_conversation_is_updated_without_replacing_its_state(self) -> None:
        original = self.conversations.create_conversation(
            session_id="conversation-1",
            metadata={"existing": {"value": 1}},
            context_metadata={"topic": "runtime"},
            system_message="system",
        )
        self.adapter.start()

        updated = self.adapter.bind_session("conversation-1", "owner-1")

        self.assertEqual(updated.history, original.history)
        self.assertEqual(updated.context, original.context)
        self.assertEqual(updated.metadata["existing"]["value"], 1)
        self.assertIn(AI_RUNTIME_METADATA_KEY, updated.metadata)

    def test_conflicting_owner_and_inactive_conversation_fail_closed(self) -> None:
        self.adapter.start()
        self.adapter.bind_session("conversation-1", "owner-1")

        with self.assertRaises(AIRuntimeSessionBindingError):
            self.adapter.bind_session("conversation-1", "owner-2")

        self.conversations.create_conversation(session_id="conversation-2")
        self.conversations.close_conversation("conversation-2")
        with self.assertRaises(AIRuntimeSessionBindingError):
            self.adapter.bind_session("conversation-2", "owner-2")

        self.assertEqual(len(self.manager.list_orchestration_sessions()), 1)

    def test_preexisting_untrusted_orchestration_binding_is_rejected(self) -> None:
        self.manager.create_session(
            "owner-1",
            session_id="conversation-1",
            metadata={
                "conversation_id": "conversation-1",
                "provider_execution_enabled": True,
            },
        )
        self.adapter.start()

        with self.assertRaises(AIRuntimeSessionBindingError):
            self.adapter.bind_session("conversation-1", "owner-1")

        self.assertEqual(self.conversations.list_conversations(), ())

    def test_shutdown_completes_sessions_in_binding_order(self) -> None:
        completed_ids: list[str] = []
        self.bus.subscribe(
            "ai.session_completed",
            lambda event: completed_ids.append(str(event.payload["session_id"])),
        )
        self.adapter.start()
        self.adapter.bind_session("conversation-2", "owner-2")
        self.adapter.bind_session("conversation-1", "owner-1")

        self.adapter.shutdown()
        self.adapter.shutdown()

        self.assertFalse(self.adapter.running)
        self.assertEqual(completed_ids, ["conversation-2", "conversation-1"])
        self.assertEqual(
            tuple(session.status.value for session in self.manager.list_orchestration_sessions()),
            ("completed", "completed"),
        )
        with self.assertRaises(AIRuntimeAdapterStateError):
            self.adapter.bind_session("conversation-3", "owner-3")

    def test_lifecycle_component_preserves_core_component_contract(self) -> None:
        lifecycle = AIRuntimeLifecycleAdapter(self.adapter)

        lifecycle.initialize(SimpleNamespace())
        session = self.adapter.bind_session("conversation-1", "owner-1")
        lifecycle.shutdown()

        self.assertEqual(session.session_id, "conversation-1")
        self.assertIs(lifecycle.state, ComponentState.STOPPED)
        self.assertFalse(self.adapter.running)
        self.assertEqual(
            self.manager.get_orchestration_session("conversation-1").status.value,
            "completed",
        )

    def test_invalid_dependencies_and_execution_metadata_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            ConversationAIRuntimeAdapter(object(), self.conversations)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ConversationAIRuntimeAdapter(self.manager, object())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            AIRuntimeMetadata(
                orchestration_session_id="conversation-1",
                owner_id="owner-1",
                status=self.manager.create_session(
                    "temporary-owner",
                    session_id="temporary-session",
                ).status,
                provider_execution_enabled=True,
            )
        with self.assertRaises(ValueError):
            AIRuntimeProviderMetadata(
                provider_id="offline",
                status=ProviderStatus.UNAVAILABLE,
                selectable=True,
            )


class NARVISRuntimeAIConversationIntegrationTests(unittest.TestCase):
    """Verify application composition while preserving the Brain execution path."""

    def _application(self) -> NARVISApplication:
        root = Path("data") / "test_runtime_tmp" / f"case_{uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return NARVISApplication(
            config=NARVISConfig(
                data_dir=root / "data",
                log_dir=root / "logs",
            )
        )

    def test_application_composes_and_orders_ai_conversation_lifecycle(self) -> None:
        application = self._application()
        lifecycle_events: list[str] = []
        for name in (
            "system.started",
            "ai.session_created",
            "conversation.created",
            "ai.session_completed",
            "conversation.updated",
            "system.stopped",
        ):
            application.event_bus.subscribe(
                name,
                lambda event: lifecycle_events.append(event.name),
            )

        try:
            application.start()
            brain = application.container.resolve("brain_engine")
            ai_manager = application.container.resolve("ai_manager")
            conversations = application.container.resolve("conversation_manager")
            runtime_adapter = application.container.resolve("ai_runtime_adapter")
            lifecycle = application.container.resolve("ai_runtime_lifecycle")
            response = SimpleNamespace(
                message="legacy brain response",
                context=SimpleNamespace(
                    conversation_id="conversation-runtime",
                    session_id="owner-runtime",
                ),
                metadata={},
            )

            with mock.patch.object(
                brain,
                "receive_text",
                return_value=response,
            ) as receive_text, mock.patch.object(
                ai_manager,
                "route_request",
                side_effect=AssertionError("AI runtime must not replace Brain routing"),
            ), mock.patch.object(
                ai_manager,
                "plan_request",
                side_effect=AssertionError("AI runtime plans must remain disabled"),
            ):
                message = application.process_text("unchanged request")

            conversation = conversations.get_conversation("conversation-runtime")
            metadata = runtime_adapter.runtime_metadata("conversation-runtime")
            self.assertEqual(message, "legacy brain response")
            receive_text.assert_called_once_with(
                "unchanged request",
                conversation_id=None,
            )
            self.assertFalse(metadata.provider_execution_enabled)
            self.assertEqual(
                conversation.metadata[AI_RUNTIME_METADATA_KEY]["owner_id"],
                "owner-runtime",
            )
            self.assertIs(lifecycle.state, ComponentState.INITIALIZED)
        finally:
            application.shutdown()

        self.assertIs(lifecycle.state, ComponentState.STOPPED)
        self.assertEqual(
            ai_manager.get_orchestration_session("conversation-runtime").status.value,
            "completed",
        )
        self.assertEqual(
            lifecycle_events,
            [
                "system.started",
                "ai.session_created",
                "conversation.created",
                "ai.session_completed",
                "conversation.updated",
                "system.stopped",
            ],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
