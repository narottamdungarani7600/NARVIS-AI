"""User profile storage services for the NARVIS Memory package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .memory import MemoryEntry, MemoryRepository, _emit_log, utc_now


@dataclass(slots=True)
class UserProfile:
    """Represents a persisted user profile record."""

    user_id: str
    preferences: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    display_name: str | None = None
    traits: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Convert the profile to a repository-friendly dictionary."""

        return {
            "user_id": self.user_id,
            "preferences": dict(self.preferences),
            "metadata": dict(self.metadata),
            "display_name": self.display_name,
            "traits": dict(self.traits),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_value(cls, user_id: str, value: Any) -> UserProfile | None:
        """Restore a profile from repository data."""

        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            return None

        created_at = value.get("created_at")
        updated_at = value.get("updated_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not isinstance(created_at, datetime):
            created_at = utc_now()
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif not isinstance(updated_at, datetime):
            updated_at = created_at

        return cls(
            user_id=str(value.get("user_id", user_id)),
            preferences=dict(value.get("preferences", {})),
            metadata=dict(value.get("metadata", {})),
            display_name=value.get("display_name"),
            traits=dict(value.get("traits", {})),
            created_at=created_at,
            updated_at=updated_at,
        )


class ProfileMemory(Protocol):
    """Protocol for profile memory services."""

    def save_profile(self, profile: UserProfile) -> None:
        """Persist a user profile."""

    def load_profile(self, user_id: str) -> UserProfile | None:
        """Load a user profile by user id."""


class BaseProfileMemory(ABC):
    """Abstract base class for profile memory implementations."""

    def __init__(self, repository: MemoryRepository, logger: Any | None = None) -> None:
        self.repository = repository
        self.logger = logger

    @abstractmethod
    def save_profile(self, profile: UserProfile) -> None:
        """Persist a user profile."""

    @abstractmethod
    def load_profile(self, user_id: str) -> UserProfile | None:
        """Load a user profile by user id."""


class InMemoryProfileMemory(BaseProfileMemory):
    """Repository-backed user profile storage."""

    def save_profile(self, profile: UserProfile) -> None:
        """Store the profile as a memory entry."""

        existing_profile = self.load_profile(profile.user_id)
        profile.created_at = existing_profile.created_at if existing_profile is not None else profile.created_at
        profile.updated_at = utc_now()
        entry = MemoryEntry(
            key=self._profile_key(profile.user_id),
            value=profile.to_dict(),
            category="profile",
            importance=1.0,
            metadata={"user_id": profile.user_id, "display_name": profile.display_name},
        )
        self.repository.save(entry)
        _emit_log(self.logger, "info", "Saved user profile", user_id=profile.user_id)

    def load_profile(self, user_id: str) -> UserProfile | None:
        """Load a user profile from repository storage."""

        entry = self.repository.load(self._profile_key(user_id))
        if entry is None or entry.category != "profile":
            return None
        profile = UserProfile.from_value(user_id, entry.value)
        if profile is not None:
            _emit_log(self.logger, "debug", "Loaded user profile", user_id=user_id)
        return profile

    def delete_profile(self, user_id: str) -> None:
        """Delete a user profile from the repository."""

        self.repository.delete(self._profile_key(user_id))
        _emit_log(self.logger, "info", "Deleted user profile", user_id=user_id)

    def list_profiles(self) -> list[UserProfile]:
        """Return every stored profile."""

        profiles: list[UserProfile] = []
        for entry in self.repository.list_entries(category="profile"):
            profile = UserProfile.from_value(str(entry.metadata.get("user_id", "")), entry.value)
            if profile is not None:
                profiles.append(profile)
        return profiles

    def set_preference(self, user_id: str, key: str, value: Any) -> UserProfile:
        """Create or update a single user preference."""

        profile = self.load_profile(user_id) or UserProfile(user_id=user_id)
        profile.preferences[key] = value
        self.save_profile(profile)
        return profile

    def get_preference(self, user_id: str, key: str, default: Any | None = None) -> Any | None:
        """Return one preference value from a stored profile."""

        profile = self.load_profile(user_id)
        if profile is None:
            return default
        return profile.preferences.get(key, default)

    def _profile_key(self, user_id: str) -> str:
        """Build the storage key for a user profile."""

        return f"profile:{user_id}"


__all__ = ["BaseProfileMemory", "InMemoryProfileMemory", "ProfileMemory", "UserProfile"]
