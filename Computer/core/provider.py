"""Abstract provider contract for the NARVIS Computer service layer."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ComputerCapability, ComputerHealth, ComputerProviderInfo


class ComputerProvider(ABC):
    """Foundation-only contract implemented by future computer adapters.

    Providers expose lifecycle and inspection operations only. Optional
    read-only information features are defined by narrow protocols in
    :mod:`Computer.services`; execution and computer-control methods remain
    outside this foundation contract.
    """

    def __init__(self, info: ComputerProviderInfo) -> None:
        if not isinstance(info, ComputerProviderInfo):
            raise TypeError("provider info must be ComputerProviderInfo")
        self._info = info

    @property
    def info(self) -> ComputerProviderInfo:
        """Return immutable provider identity metadata."""

        return self._info

    @abstractmethod
    def initialize(self) -> None:
        """Prepare provider-owned resources without performing an OS action."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release provider-owned resources."""

    @abstractmethod
    def health(self) -> ComputerHealth:
        """Return the provider's current health observation."""

    @abstractmethod
    def capabilities(self) -> tuple[ComputerCapability, ...]:
        """Return inert metadata describing supported capabilities."""


__all__ = ["ComputerProvider"]
