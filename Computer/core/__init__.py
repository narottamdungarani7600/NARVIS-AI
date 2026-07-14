"""Phase 10 Computer Integration Layer foundation for NARVIS."""

from .exceptions import (
    ComputerCapabilityDiscoveryError,
    ComputerProviderAlreadyInitializedError,
    ComputerProviderHealthError,
    ComputerProviderInitializationError,
    ComputerProviderInspectionError,
    ComputerProviderLifecycleError,
    ComputerProviderNotFoundError,
    ComputerProviderNotInitializedError,
    ComputerProviderShutdownError,
    ComputerRegistryError,
    ComputerServiceError,
    DuplicateComputerProviderError,
    DuplicateProviderError,
    ProviderAlreadyRegisteredError,
    ProviderNotFoundError,
    ProviderNotRegisteredError,
)
from .interfaces import EventPublisher
from .manager import ComputerManager
from .models import (
    ComputerCapability,
    ComputerHealth,
    ComputerProviderInfo,
    ComputerStatus,
)
from .provider import ComputerProvider
from .registry import ComputerRegistry

__all__ = [
    "ComputerCapability",
    "ComputerCapabilityDiscoveryError",
    "ComputerHealth",
    "ComputerManager",
    "ComputerProvider",
    "ComputerProviderAlreadyInitializedError",
    "ComputerProviderHealthError",
    "ComputerProviderInfo",
    "ComputerProviderInitializationError",
    "ComputerProviderInspectionError",
    "ComputerProviderLifecycleError",
    "ComputerProviderNotFoundError",
    "ComputerProviderNotInitializedError",
    "ComputerProviderShutdownError",
    "ComputerRegistry",
    "ComputerRegistryError",
    "ComputerServiceError",
    "ComputerStatus",
    "DuplicateComputerProviderError",
    "DuplicateProviderError",
    "EventPublisher",
    "ProviderAlreadyRegisteredError",
    "ProviderNotFoundError",
    "ProviderNotRegisteredError",
]
