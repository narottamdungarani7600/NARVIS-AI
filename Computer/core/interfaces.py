"""Structural dependency interfaces for the Computer service layer."""

from __future__ import annotations

from typing import Any, Protocol


class EventPublisher(Protocol):
    """Structural contract implemented by the existing Core EventBus."""

    def publish(self, event: Any) -> None:
        """Publish one domain event."""


__all__ = ["EventPublisher"]
