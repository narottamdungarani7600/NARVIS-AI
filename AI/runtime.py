"""Typed, non-executing integration between AI orchestration and Conversation.

This module is an application-facing compatibility boundary.  It binds the
immutable Phase 13 orchestration lifecycle to the provider-neutral Conversation
facade without exposing provider instances or introducing an event relay.  AI
lifecycle events continue to be published only by ``AIManager`` through its
existing ``OrchestrationEvents`` dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from threading import RLock
from typing import Any, Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import BaseSystemComponent

from .core.models import AIProvider, ProviderStatus
from .orchestrator.models import (
    OrchestrationSession,
    OrchestrationSessionStatus,
    OrchestrationSummary,
)

AI_RUNTIME_METADATA_KEY = "ai_runtime"
AI_RUNTIME_METADATA_SCHEMA = "narvis.ai.runtime.v1"


class AIRuntimeIntegrationError(RuntimeError):
    """Base error for the non-executing AI runtime integration boundary."""


class AIRuntimeAdapterStateError(AIRuntimeIntegrationError):
    """Raised when a binding operation is requested outside the running state."""


class AIRuntimeSessionBindingError(AIRuntimeIntegrationError):
    """Raised when Conversation and orchestration session identities conflict."""


class ConversationSessionView(Protocol):
    """Provider-neutral Conversation snapshot fields consumed by the adapter."""

    session_id: str
    active: bool
    metadata: Mapping[str, Any]


class ConversationRuntime(Protocol):
    """Minimal Conversation facade used by the runtime adapter."""

    def create_conversation(
        self,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ConversationSessionView:
        """Create an immutable Conversation session."""

    def list_conversations(self) -> tuple[ConversationSessionView, ...]:
        """Return retained Conversation sessions in deterministic order."""

    def update_metadata(
        self,
        session_id: str,
        metadata: Mapping[str, Any],
    ) -> ConversationSessionView:
        """Merge provider-neutral session metadata."""


class AIRuntimeManager(Protocol):
    """AIManager operations required for lifecycle and metadata integration."""

    def create_session(
        self,
        owner_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        ttl: timedelta | None = None,
        session_id: str | None = None,
    ) -> OrchestrationSession:
        """Create one architecture-only orchestration session."""

    def get_orchestration_session(self, session_id: str) -> OrchestrationSession:
        """Return one immutable orchestration session."""

    def list_orchestration_sessions(self) -> tuple[OrchestrationSession, ...]:
        """Return orchestration sessions in deterministic creation order."""

    def orchestration_summary(self, session_id: str) -> OrchestrationSummary:
        """Return safe aggregate orchestration facts."""

    def complete_session(self, session_id: str) -> OrchestrationSession:
        """Complete an active architecture-only orchestration session."""

    def cancel_session(self, session_id: str) -> OrchestrationSession:
        """Cancel an active architecture-only orchestration session."""

    def list_providers(self) -> tuple[AIProvider, ...]:
        """Return immutable registered provider snapshots."""


def _identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
    ):
        raise AIRuntimeSessionBindingError(
            f"{name} must be normalized non-empty text of at most 128 characters"
        )
    return value


@dataclass(slots=True, frozen=True)
class AIRuntimeProviderMetadata:
    """Detached provider facts safe for Conversation session metadata."""

    provider_id: str
    status: ProviderStatus
    selectable: bool

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider_id")
        if not isinstance(self.status, ProviderStatus):
            raise TypeError("status must be a ProviderStatus")
        if not isinstance(self.selectable, bool):
            raise TypeError("selectable must be a bool")
        if self.selectable and self.status not in {
            ProviderStatus.AVAILABLE,
            ProviderStatus.DEGRADED,
        }:
            raise ValueError("only available or degraded providers may be selectable")

    def as_mapping(self) -> Mapping[str, object]:
        """Return primitives suitable for immutable Conversation metadata."""

        return {
            "provider_id": self.provider_id,
            "status": self.status.value,
            "selectable": self.selectable,
        }


@dataclass(slots=True, frozen=True)
class AIRuntimeMetadata:
    """Typed architecture-only AI facts exposed by a Conversation session."""

    orchestration_session_id: str
    owner_id: str
    status: OrchestrationSessionStatus
    providers: tuple[AIRuntimeProviderMetadata, ...] = ()
    request_count: int = 0
    plan_count: int = 0
    selection_count: int = 0
    last_provider_id: str | None = None
    last_model_name: str | None = None
    schema: str = AI_RUNTIME_METADATA_SCHEMA
    architecture_only: bool = True
    provider_execution_enabled: bool = False

    def __post_init__(self) -> None:
        _identifier(self.orchestration_session_id, "orchestration_session_id")
        _identifier(self.owner_id, "owner_id")
        if not isinstance(self.status, OrchestrationSessionStatus):
            raise TypeError("status must be an OrchestrationSessionStatus")
        providers = tuple(self.providers)
        if any(not isinstance(item, AIRuntimeProviderMetadata) for item in providers):
            raise TypeError("providers must contain AIRuntimeProviderMetadata values")
        provider_ids = tuple(item.provider_id for item in providers)
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError("providers cannot contain duplicate identifiers")
        for name in ("request_count", "plan_count", "selection_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not (self.request_count == self.plan_count == self.selection_count):
            raise ValueError("runtime request, plan, and selection counts must match")
        if self.last_provider_id is not None:
            _identifier(self.last_provider_id, "last_provider_id")
        if self.last_model_name is not None and (
            not isinstance(self.last_model_name, str)
            or not self.last_model_name
            or self.last_model_name != self.last_model_name.strip()
            or len(self.last_model_name) > 256
        ):
            raise ValueError(
                "last_model_name must be normalized non-empty text or None"
            )
        if self.selection_count == 0 and (
            self.last_provider_id is not None or self.last_model_name is not None
        ):
            raise ValueError("empty runtime metadata cannot report a last selection")
        if self.selection_count > 0 and self.last_provider_id is None:
            raise ValueError("runtime metadata with selections requires last_provider_id")
        if self.schema != AI_RUNTIME_METADATA_SCHEMA:
            raise ValueError("unsupported AI runtime metadata schema")
        if self.architecture_only is not True:
            raise ValueError("AI runtime metadata must remain architecture-only")
        if self.provider_execution_enabled is not False:
            raise ValueError("provider execution must remain disabled")
        object.__setattr__(self, "providers", providers)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        """Return registered provider identifiers in deterministic registry order."""

        return tuple(item.provider_id for item in self.providers)

    @property
    def selectable_provider_ids(self) -> tuple[str, ...]:
        """Return only providers whose immutable snapshots are selectable."""

        return tuple(item.provider_id for item in self.providers if item.selectable)

    @property
    def routing_ready(self) -> bool:
        """Return whether metadata-only routing has at least one eligible provider."""

        return bool(self.selectable_provider_ids)

    def as_mapping(self) -> Mapping[str, object]:
        """Return detached primitives for a Conversation session metadata field."""

        return {
            "schema": self.schema,
            "orchestration_session_id": self.orchestration_session_id,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "providers": tuple(item.as_mapping() for item in self.providers),
            "provider_ids": self.provider_ids,
            "selectable_provider_ids": self.selectable_provider_ids,
            "routing_ready": self.routing_ready,
            "request_count": self.request_count,
            "plan_count": self.plan_count,
            "selection_count": self.selection_count,
            "last_provider_id": self.last_provider_id,
            "last_model_name": self.last_model_name,
            "architecture_only": self.architecture_only,
            "provider_execution_enabled": self.provider_execution_enabled,
        }


class ConversationAIRuntimeAdapter:
    """Bind Conversation sessions to AIManager lifecycle without execution."""

    def __init__(
        self,
        ai_manager: AIRuntimeManager,
        conversation_runtime: ConversationRuntime,
        *,
        logger: Logger | None = None,
        session_ttl: timedelta | None = None,
    ) -> None:
        manager_methods = (
            "create_session",
            "get_orchestration_session",
            "list_orchestration_sessions",
            "orchestration_summary",
            "complete_session",
            "cancel_session",
            "list_providers",
        )
        if not all(callable(getattr(ai_manager, name, None)) for name in manager_methods):
            raise TypeError("ai_manager does not implement the runtime manager contract")
        conversation_methods = (
            "create_conversation",
            "list_conversations",
            "update_metadata",
        )
        if not all(
            callable(getattr(conversation_runtime, name, None))
            for name in conversation_methods
        ):
            raise TypeError(
                "conversation_runtime does not implement the Conversation contract"
            )
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if session_ttl is not None and (
            not isinstance(session_ttl, timedelta) or session_ttl <= timedelta(0)
        ):
            raise ValueError("session_ttl must be a positive timedelta or None")
        self._ai_manager = ai_manager
        self._conversation_runtime = conversation_runtime
        self._logger = logger or NullLogger("narvis.ai.runtime")
        self._session_ttl = session_ttl
        self._bindings: dict[str, str] = {}
        self._running = False
        self._lock = RLock()

    @property
    def running(self) -> bool:
        """Return whether new runtime bindings are accepted."""

        with self._lock:
            return self._running

    @property
    def binding_count(self) -> int:
        """Return the number of retained deterministic session bindings."""

        with self._lock:
            return len(self._bindings)

    def start(self) -> None:
        """Enable runtime bindings without probing or executing a provider."""

        with self._lock:
            self._running = True
        self._log(LogLevel.INFO, "AI Conversation runtime adapter started")

    def bind_session(
        self,
        conversation_id: str,
        owner_id: str,
    ) -> ConversationSessionView:
        """Create or refresh one Conversation-to-orchestration lifecycle binding."""

        conversation_identifier = _identifier(conversation_id, "conversation_id")
        owner_identifier = _identifier(owner_id, "owner_id")
        with self._lock:
            if not self._running:
                raise AIRuntimeAdapterStateError(
                    "AI Conversation runtime adapter is not running"
                )
            bound_owner = self._bindings.get(conversation_identifier)
            if bound_owner is not None and bound_owner != owner_identifier:
                raise AIRuntimeSessionBindingError(
                    "conversation is already bound to another runtime owner"
                )

            conversation = self._find_conversation(conversation_identifier)
            if conversation is not None and not conversation.active:
                raise AIRuntimeSessionBindingError(
                    "only active Conversation sessions can be bound"
                )

            orchestration = self._find_orchestration(conversation_identifier)
            created_orchestration = False
            if orchestration is None:
                orchestration = self._ai_manager.create_session(
                    owner_identifier,
                    metadata={
                        "conversation_id": conversation_identifier,
                        "runtime_adapter": AI_RUNTIME_METADATA_SCHEMA,
                        "provider_execution_enabled": False,
                    },
                    ttl=self._session_ttl,
                    session_id=conversation_identifier,
                )
                created_orchestration = True
            else:
                self._validate_existing_orchestration(
                    orchestration,
                    conversation_identifier,
                    owner_identifier,
                )

            metadata = self._metadata(orchestration)
            try:
                if conversation is None:
                    conversation = self._conversation_runtime.create_conversation(
                        session_id=conversation_identifier,
                        metadata={AI_RUNTIME_METADATA_KEY: metadata.as_mapping()},
                    )
                else:
                    conversation = self._update_conversation_metadata(
                        conversation,
                        metadata,
                    )
            except Exception:
                if created_orchestration and orchestration.active:
                    try:
                        self._ai_manager.cancel_session(orchestration.session_id)
                    except Exception:
                        pass
                raise

            self._bindings[conversation_identifier] = owner_identifier
            self._log(
                LogLevel.INFO,
                "AI orchestration session bound to Conversation",
                conversation_id=conversation_identifier,
                orchestration_session_id=orchestration.session_id,
                provider_execution_enabled=False,
            )
            return conversation

    bind = bind_session

    def runtime_metadata(self, conversation_id: str) -> AIRuntimeMetadata:
        """Return a fresh typed metadata view without mutating Conversation."""

        identifier = _identifier(conversation_id, "conversation_id")
        with self._lock:
            orchestration = self._find_orchestration(identifier)
            if orchestration is None:
                raise AIRuntimeSessionBindingError(
                    f"conversation '{identifier}' has no AI runtime binding"
                )
            return self._metadata(orchestration)

    metadata = runtime_metadata

    def refresh_session(self, conversation_id: str) -> ConversationSessionView:
        """Refresh stored Conversation metadata from immutable AI summaries."""

        identifier = _identifier(conversation_id, "conversation_id")
        with self._lock:
            conversation = self._find_conversation(identifier)
            orchestration = self._find_orchestration(identifier)
            if conversation is None or orchestration is None:
                raise AIRuntimeSessionBindingError(
                    f"conversation '{identifier}' has no complete runtime binding"
                )
            if not conversation.active:
                raise AIRuntimeSessionBindingError(
                    "only active Conversation sessions can refresh metadata"
                )
            return self._update_conversation_metadata(
                conversation,
                self._metadata(orchestration),
            )

    def complete_session(self, conversation_id: str) -> OrchestrationSession:
        """Complete one bound orchestration session and refresh Conversation."""

        identifier = _identifier(conversation_id, "conversation_id")
        with self._lock:
            orchestration = self._find_orchestration(identifier)
            if orchestration is None:
                raise AIRuntimeSessionBindingError(
                    f"conversation '{identifier}' has no AI runtime binding"
                )
            if orchestration.active:
                orchestration = self._ai_manager.complete_session(identifier)
            conversation = self._find_conversation(identifier)
            if conversation is not None and conversation.active:
                self._update_conversation_metadata(
                    conversation,
                    self._metadata(orchestration),
                )
            return orchestration

    complete = complete_session

    def shutdown(self) -> None:
        """Complete active bindings in creation order and reject new bindings."""

        with self._lock:
            if not self._running:
                return
            identifiers = tuple(self._bindings)
            for identifier in identifiers:
                try:
                    self.complete_session(identifier)
                except Exception as error:
                    self._log(
                        LogLevel.WARNING,
                        "Unable to complete AI runtime session during shutdown",
                        conversation_id=identifier,
                        error_type=type(error).__name__,
                    )
            self._running = False
        self._log(LogLevel.INFO, "AI Conversation runtime adapter stopped")

    def _metadata(self, orchestration: OrchestrationSession) -> AIRuntimeMetadata:
        summary = self._ai_manager.orchestration_summary(orchestration.session_id)
        providers = tuple(
            AIRuntimeProviderMetadata(
                provider_id=provider.provider_id,
                status=provider.status,
                selectable=provider.selectable,
            )
            for provider in self._ai_manager.list_providers()
        )
        return AIRuntimeMetadata(
            orchestration_session_id=orchestration.session_id,
            owner_id=orchestration.owner_id,
            status=summary.status,
            providers=providers,
            request_count=summary.request_count,
            plan_count=summary.plan_count,
            selection_count=summary.selection_count,
            last_provider_id=summary.last_provider_id,
            last_model_name=summary.last_model_name,
        )

    def _find_conversation(self, session_id: str) -> ConversationSessionView | None:
        return next(
            (
                session
                for session in self._conversation_runtime.list_conversations()
                if session.session_id == session_id
            ),
            None,
        )

    def _find_orchestration(self, session_id: str) -> OrchestrationSession | None:
        return next(
            (
                session
                for session in self._ai_manager.list_orchestration_sessions()
                if session.session_id == session_id
            ),
            None,
        )

    @staticmethod
    def _validate_existing_orchestration(
        orchestration: OrchestrationSession,
        conversation_id: str,
        owner_id: str,
    ) -> None:
        if orchestration.owner_id != owner_id:
            raise AIRuntimeSessionBindingError(
                "orchestration session is owned by another runtime session"
            )
        if orchestration.metadata.get("conversation_id") != conversation_id:
            raise AIRuntimeSessionBindingError(
                "orchestration session is not bound to this Conversation"
            )
        if orchestration.metadata.get("provider_execution_enabled") is not False:
            raise AIRuntimeSessionBindingError(
                "orchestration session does not preserve disabled execution"
            )

    def _update_conversation_metadata(
        self,
        conversation: ConversationSessionView,
        metadata: AIRuntimeMetadata,
    ) -> ConversationSessionView:
        value = metadata.as_mapping()
        if conversation.metadata.get(AI_RUNTIME_METADATA_KEY) == value:
            return conversation
        return self._conversation_runtime.update_metadata(
            conversation.session_id,
            {AI_RUNTIME_METADATA_KEY: value},
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


class AIRuntimeLifecycleAdapter(BaseSystemComponent):
    """Expose the typed Conversation bridge through the Core lifecycle contract."""

    def __init__(
        self,
        runtime_adapter: ConversationAIRuntimeAdapter,
        *,
        name: str = "ai_runtime",
    ) -> None:
        if not all(
            callable(getattr(runtime_adapter, method, None))
            for method in ("start", "shutdown")
        ):
            raise TypeError("runtime_adapter must provide start and shutdown")
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError("name must be normalized non-empty text")
        super().__init__(name)
        self._runtime_adapter = runtime_adapter

    @property
    def runtime_adapter(self) -> ConversationAIRuntimeAdapter:
        """Return the injected Conversation integration service."""

        return self._runtime_adapter

    def _initialize(self, context: Any) -> None:
        self._runtime_adapter.start()

    def _shutdown(self) -> None:
        self._runtime_adapter.shutdown()


__all__ = [
    "AI_RUNTIME_METADATA_KEY",
    "AI_RUNTIME_METADATA_SCHEMA",
    "AIRuntimeAdapterStateError",
    "AIRuntimeIntegrationError",
    "AIRuntimeLifecycleAdapter",
    "AIRuntimeMetadata",
    "AIRuntimeProviderMetadata",
    "AIRuntimeSessionBindingError",
    "ConversationAIRuntimeAdapter",
    "ConversationRuntime",
]
