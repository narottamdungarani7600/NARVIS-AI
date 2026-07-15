"""Typed failures for intelligent, UI-independent conversation context."""

from __future__ import annotations

from Conversation.core.exceptions import ConversationError, ConversationValidationError


class ConversationContextError(ConversationError):
    """Base exception for Sprint 2 context services."""


class ContextServiceValidationError(
    ConversationContextError,
    ConversationValidationError,
):
    """Raised when a context service receives invalid input."""


class SummaryGenerationError(ContextServiceValidationError):
    """Raised when a conversation summary cannot be generated."""


class TopicDetectionError(ContextServiceValidationError):
    """Raised when topic analysis input is invalid."""


class WindowValidationError(ContextServiceValidationError):
    """Raised when a conversation window request is invalid."""


class SearchValidationError(ContextServiceValidationError):
    """Raised when a conversation search request is invalid."""


class ReferenceValidationError(ContextServiceValidationError):
    """Raised when a read-only context reference is invalid."""


class ReferenceNotFoundError(ReferenceValidationError, LookupError):
    """Raised when an injected read-only source cannot resolve a reference."""


__all__ = [
    "ContextServiceValidationError",
    "ConversationContextError",
    "ReferenceNotFoundError",
    "ReferenceValidationError",
    "SearchValidationError",
    "SummaryGenerationError",
    "TopicDetectionError",
    "WindowValidationError",
]
