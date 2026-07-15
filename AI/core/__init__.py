"""Provider-agnostic, architecture-only AI orchestration foundation."""

from .exceptions import (
    AIOrchestratorError,
    AIValidationError,
    NoEligibleProviderError,
    ProviderAlreadyRegisteredError,
    ProviderCapabilityError,
    ProviderHealthError,
    ProviderNotFoundError,
    ProviderRegistryError,
    ProviderUnavailableError,
)
from .interfaces import (
    EventPublisher,
    ProviderCatalog,
    ProviderDescriptor,
    ProviderSelectionStrategy,
)
from .manager import (
    AIManager,
    AIOrchestratorManager,
    AI_PROVIDER_REGISTERED_EVENT,
    AI_PROVIDER_REMOVED_EVENT,
    AI_PROVIDER_SELECTED_EVENT,
    ProviderManager,
)
from .models import (
    AIProvider,
    AIRequest,
    AIResponse,
    ProviderCapability,
    ProviderHealth,
    ProviderMetadata,
    ProviderPriority,
    ProviderStatus,
)
from .provider import (
    DefaultProviderSelector,
    PriorityProviderSelector,
    ProviderSnapshotFactory,
)
from .registry import AIProviderRegistry, ProviderRegistry

__all__ = [
    "AIManager",
    "AIOrchestratorError",
    "AIOrchestratorManager",
    "AIProvider",
    "AIProviderRegistry",
    "AIRequest",
    "AIResponse",
    "AIValidationError",
    "AI_PROVIDER_REGISTERED_EVENT",
    "AI_PROVIDER_REMOVED_EVENT",
    "AI_PROVIDER_SELECTED_EVENT",
    "DefaultProviderSelector",
    "EventPublisher",
    "NoEligibleProviderError",
    "PriorityProviderSelector",
    "ProviderAlreadyRegisteredError",
    "ProviderCapability",
    "ProviderCapabilityError",
    "ProviderCatalog",
    "ProviderDescriptor",
    "ProviderHealth",
    "ProviderHealthError",
    "ProviderManager",
    "ProviderMetadata",
    "ProviderNotFoundError",
    "ProviderPriority",
    "ProviderRegistry",
    "ProviderRegistryError",
    "ProviderSelectionStrategy",
    "ProviderSnapshotFactory",
    "ProviderStatus",
    "ProviderUnavailableError",
]
