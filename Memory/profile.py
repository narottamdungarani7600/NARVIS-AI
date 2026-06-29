"""User profile memory abstractions for the NARVIS Memory package.

Profile memory is intended to hold structured, persistent user preference and
identity information that can be used by higher-level services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository


@dataclass(slots=True)
class UserProfile:
    """Represents a user profile record."""

    user_id: str
    preferences: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProfileMemory(Protocol):
    """Protocol for profile memory services."""

    def save_profile(self, profile: UserProfile) -> None:
        """Persist a user profile."""

    def load_profile(self, user_id: str) -> UserProfile | None:
        """Load a user profile by user id."""


class BaseProfileMemory(ABC):
    """Abstract base class for profile memory implementations."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @abstractmethod
    def save_profile(self, profile: UserProfile) -> None:
        """Persist a user profile."""

    @abstractmethod
    def load_profile(self, user_id: str) -> UserProfile | None:
        """Load a user profile by user id."""


class InMemoryProfileMemory(BaseProfileMemory):
    """In-memory profile memory implementation."""

    def save_profile(self, profile: UserProfile) -> None:
        """Store the profile as a memory entry."""
        self.repository.save(
            MemoryEntry(
                key=f"profile:{profile.user_id}",
                value=profile,
                category="profile",
                importance=1.0,
            )
        )

    def load_profile(self, user_id: str) -> UserProfile | None:
        """Load a user profile from repository storage."""
        entry = self.repository.load(f"profile:{user_id}")
        if entry is None:
            return None
        return entry.value if isinstance(entry.value, UserProfile) else None
