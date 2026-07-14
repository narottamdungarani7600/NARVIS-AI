"""Exception hierarchy for the UI-independent conversation framework."""

from __future__ import annotations


class ConversationError(Exception):
    """Base exception for conversation core services."""


class ConversationValidationError(ConversationError, ValueError):
    """Raised when a conversation model or operation is invalid."""


class ConversationNotFoundError(ConversationError, LookupError):
    """Raised when a conversation session cannot be found."""


class DuplicateConversationError(ConversationError, ValueError):
    """Raised when a conversation session identifier already exists."""


class ConversationClosedError(ConversationError):
    """Raised when an active-only operation targets a closed conversation."""


class ConversationAlreadyActiveError(ConversationError):
    """Raised when an active conversation is resumed."""


class ConversationAlreadyClosedError(ConversationError):
    """Raised when a closed conversation is closed again."""


class MessageValidationError(ConversationValidationError):
    """Raised when a conversation message violates the typed contract."""


class ContextValidationError(ConversationValidationError):
    """Raised when conversation context cannot be updated safely."""


__all__ = [
    "ContextValidationError",
    "ConversationAlreadyActiveError",
    "ConversationAlreadyClosedError",
    "ConversationClosedError",
    "ConversationError",
    "ConversationNotFoundError",
    "ConversationValidationError",
    "DuplicateConversationError",
    "MessageValidationError",
]
