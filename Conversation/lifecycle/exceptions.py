"""Typed failures for UI-independent conversation lifecycle services."""

from __future__ import annotations

from Conversation.core.exceptions import ConversationError, ConversationValidationError


class ConversationLifecycleError(ConversationError):
    """Base failure for lifecycle, archive, cleanup, and export services."""


class LifecycleValidationError(
    ConversationLifecycleError,
    ConversationValidationError,
):
    """Raised when lifecycle inputs violate immutable contracts."""


class ConversationArchiveError(ConversationLifecycleError):
    """Base failure for in-memory archive operations."""


class ConversationAlreadyArchivedError(ConversationArchiveError):
    """Raised when an archived conversation is archived again."""


class ConversationNotArchivedError(ConversationArchiveError):
    """Raised when restoration targets a non-archived conversation."""


class ConversationExpiredError(ConversationLifecycleError):
    """Raised when an operation targets an expired conversation."""


class SessionSwitchError(ConversationLifecycleError):
    """Raised when a session cannot become the selected active session."""


class NoCurrentSessionError(SessionSwitchError):
    """Raised when no current conversation session is selected."""


class CleanupError(ConversationLifecycleError):
    """Raised when in-memory cleanup cannot be completed safely."""


class SessionRemovalUnsupportedError(CleanupError):
    """Raised when an injected store cannot remove sessions."""


class RetentionPolicyError(LifecycleValidationError):
    """Raised when a retention policy is invalid."""


class ConversationExportError(ConversationLifecycleError):
    """Raised when an export-ready snapshot cannot be prepared."""


__all__ = [
    "CleanupError",
    "ConversationAlreadyArchivedError",
    "ConversationArchiveError",
    "ConversationExpiredError",
    "ConversationExportError",
    "ConversationLifecycleError",
    "ConversationNotArchivedError",
    "LifecycleValidationError",
    "NoCurrentSessionError",
    "RetentionPolicyError",
    "SessionRemovalUnsupportedError",
    "SessionSwitchError",
]
