"""Exception hierarchy for dry-run execution previews."""

from __future__ import annotations


class PreviewError(Exception):
    """Base exception for action preview services."""


class PreviewValidationError(PreviewError, ValueError):
    """Raised when preview input violates the immutable planning contract."""


class PreviewNotFoundError(PreviewError, LookupError):
    """Raised when a retained preview cannot be found."""


class DuplicatePreviewError(PreviewError, ValueError):
    """Raised when a preview identifier is retained more than once."""


class PreviewCancelledError(PreviewError):
    """Raised when an operation requires a non-cancelled preview."""


class RiskAnalysisError(PreviewError, ValueError):
    """Raised when deterministic risk scoring cannot be completed."""


class SummaryValidationError(PreviewError, ValueError):
    """Raised when an execution summary cannot be generated safely."""


__all__ = [
    "DuplicatePreviewError",
    "PreviewCancelledError",
    "PreviewError",
    "PreviewNotFoundError",
    "PreviewValidationError",
    "RiskAnalysisError",
    "SummaryValidationError",
]
