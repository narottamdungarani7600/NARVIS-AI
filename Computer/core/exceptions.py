"""Typed failures for the NARVIS Computer service foundation."""

from __future__ import annotations


class ComputerServiceError(Exception):
    """Base exception for Computer service foundation failures."""


class ComputerRegistryError(ComputerServiceError):
    """Base exception for provider registry failures."""


class DuplicateComputerProviderError(ComputerRegistryError):
    """Raised when a provider name is registered more than once."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Computer provider '{provider_name}' is already registered")


class ComputerProviderNotFoundError(ComputerRegistryError):
    """Raised when a provider name is not registered."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Computer provider '{provider_name}' is not registered")


class ComputerProviderLifecycleError(ComputerServiceError):
    """Base exception for provider lifecycle failures."""


class ComputerProviderAlreadyInitializedError(ComputerProviderLifecycleError):
    """Raised when an initialized provider is initialized again."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Computer provider '{provider_name}' is already initialized")


class ComputerProviderNotInitializedError(ComputerProviderLifecycleError):
    """Raised when shutdown is requested for an inactive provider."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"Computer provider '{provider_name}' is not initialized")


class ComputerProviderInitializationError(ComputerProviderLifecycleError):
    """Raised when a provider cannot be initialized."""

    def __init__(self, provider_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"Unable to initialize computer provider '{provider_name}': {reason}"
        )


class ComputerProviderShutdownError(ComputerProviderLifecycleError):
    """Raised when a provider cannot be shut down."""

    def __init__(self, provider_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"Unable to shut down computer provider '{provider_name}': {reason}"
        )


class ComputerProviderInspectionError(ComputerServiceError):
    """Base exception for health and capability inspection failures."""


class ComputerProviderHealthError(ComputerProviderInspectionError):
    """Raised when a provider health check fails or returns invalid data."""

    def __init__(self, provider_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"Unable to check computer provider '{provider_name}' health: {reason}"
        )


class ComputerCapabilityDiscoveryError(ComputerProviderInspectionError):
    """Raised when provider capability discovery fails."""

    def __init__(self, provider_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"Unable to discover computer provider '{provider_name}' capabilities: "
            f"{reason}"
        )


class ComputerInformationServiceError(ComputerServiceError):
    """Base failure for provider-backed, read-only information requests."""

    service_name = "computer information"

    def __init__(self, provider_name: str, operation: str, reason: str) -> None:
        self.provider_name = provider_name
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"Unable to complete {self.service_name} request '{operation}' "
            f"with provider '{provider_name}': {reason}"
        )


class FileSystemServiceError(ComputerInformationServiceError):
    """Raised when a read-only filesystem provider request fails."""

    service_name = "filesystem"


class ProcessServiceError(ComputerInformationServiceError):
    """Raised when a process-information provider request fails."""

    service_name = "process"


class ClipboardServiceError(ComputerInformationServiceError):
    """Raised when a text-clipboard provider request fails."""

    service_name = "clipboard"


class ApplicationServiceError(ComputerInformationServiceError):
    """Raised when an application-discovery provider request fails."""

    service_name = "application"


# Concise aliases for callers that already have a Computer-specific namespace.
DuplicateProviderError = DuplicateComputerProviderError
ProviderAlreadyRegisteredError = DuplicateComputerProviderError
ProviderNotFoundError = ComputerProviderNotFoundError
ProviderNotRegisteredError = ComputerProviderNotFoundError


__all__ = [
    "ApplicationServiceError",
    "ClipboardServiceError",
    "ComputerCapabilityDiscoveryError",
    "ComputerInformationServiceError",
    "ComputerProviderAlreadyInitializedError",
    "ComputerProviderHealthError",
    "ComputerProviderInitializationError",
    "ComputerProviderInspectionError",
    "ComputerProviderLifecycleError",
    "ComputerProviderNotFoundError",
    "ComputerProviderNotInitializedError",
    "ComputerProviderShutdownError",
    "ComputerRegistryError",
    "ComputerServiceError",
    "DuplicateComputerProviderError",
    "DuplicateProviderError",
    "ProviderAlreadyRegisteredError",
    "ProviderNotFoundError",
    "ProviderNotRegisteredError",
    "FileSystemServiceError",
    "ProcessServiceError",
]
