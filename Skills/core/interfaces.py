"""Abstract interfaces for future intelligent NARVIS skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, Protocol, TypeVar


RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class SkillInterface(ABC, Generic[RequestT, ResultT]):
    """Lifecycle contract implemented by future skill adapters.

    The interface deliberately defines no reasoning, routing, or execution
    policy. Dependencies needed by a skill should be supplied when its
    implementation is constructed.
    """

    @abstractmethod
    def initialize(self) -> None:
        """Prepare the skill for use without executing a request."""

    @abstractmethod
    def execute(self, request: RequestT) -> ResultT:
        """Handle one explicitly supplied request."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release resources held by the skill."""


class EventPublisher(Protocol):
    """Structural contract for the existing EventBus abstraction."""

    def publish(self, event: Any) -> None:
        """Publish one event."""


__all__ = ["EventPublisher", "RequestT", "ResultT", "SkillInterface"]
