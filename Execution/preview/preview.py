"""In-memory lifecycle management for immutable execution previews."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from threading import RLock
from typing import Any

from Core.execution.models import ExecutionRequest
from Core.logger import Logger
from Execution.session.models import ExecutionSession, new_id, utc_now
from Execution.session.queue import EventPublisher

from .exceptions import (
    DuplicatePreviewError,
    PreviewCancelledError,
    PreviewNotFoundError,
)
from .models import ActionPreview, ExecutionPreview
from .planner import DurationEstimator, PreviewPlanner
from .risk import PreviewRiskAnalyzer
from .summary import ApprovalContext, SummaryGenerator


class ExecutionPreviewManager:
    """Retain preview snapshots and coordinate create/update/cancel transitions."""

    def __init__(
        self,
        planner: PreviewPlanner | None = None,
        *,
        risk_analyzer: PreviewRiskAnalyzer | None = None,
        summary_generator: SummaryGenerator | None = None,
        duration_estimator: DurationEstimator | None = None,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        """Initialize the planner through dependency injection."""

        if planner is not None and any(
            dependency is not None
            for dependency in (
                risk_analyzer,
                summary_generator,
                duration_estimator,
            )
        ):
            raise ValueError(
                "planner dependencies must be injected through the planner"
            )
        self._planner = planner or PreviewPlanner(
            risk_analyzer,
            summary_generator,
            duration_estimator,
            event_bus=event_bus,
            logger=logger,
            clock=clock,
            id_factory=id_factory,
        )
        self._previews: dict[str, ExecutionPreview] = {}
        self._lock = RLock()

    @property
    def planner(self) -> PreviewPlanner:
        """Return the injected pure preview planner."""

        return self._planner

    def create_preview(
        self,
        request: ExecutionRequest,
        *,
        session: ExecutionSession | None = None,
        actions: Sequence[ActionPreview] | None = None,
        approval: ApprovalContext = None,
        metadata: Mapping[str, Any] | None = None,
        preview_id: str | None = None,
    ) -> ExecutionPreview:
        """Generate and retain one immutable preview snapshot."""

        if preview_id is not None:
            with self._lock:
                if preview_id in self._previews:
                    raise DuplicatePreviewError(
                        f"execution preview '{preview_id}' already exists"
                    )
        preview = self._planner.generate(
            request,
            session=session,
            actions=actions,
            approval=approval,
            metadata=metadata,
            preview_id=preview_id,
        )
        with self._lock:
            if preview.preview_id in self._previews:
                raise DuplicatePreviewError(
                    f"execution preview '{preview.preview_id}' already exists"
                )
            self._previews[preview.preview_id] = preview
        return preview

    def create(
        self,
        request: ExecutionRequest,
        **kwargs: Any,
    ) -> ExecutionPreview:
        """Return :meth:`create_preview` for concise callers."""

        return self.create_preview(request, **kwargs)

    def update_preview(
        self,
        preview_id: str,
        *,
        actions: Sequence[ActionPreview] | None = None,
        approval: ApprovalContext = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionPreview:
        """Revise and replace one retained preview snapshot."""

        with self._lock:
            preview = self._require_preview(preview_id)
            if preview.cancelled:
                raise PreviewCancelledError("cancelled previews cannot be updated")
            updated = self._planner.revise(
                preview,
                actions=actions,
                approval=approval,
                metadata=metadata,
            )
            self._previews[preview_id] = updated
            return updated

    def update(
        self,
        preview_id: str,
        **kwargs: Any,
    ) -> ExecutionPreview:
        """Return :meth:`update_preview` for concise callers."""

        return self.update_preview(preview_id, **kwargs)

    def cancel_preview(
        self,
        preview_id: str,
        *,
        reason: str = "cancelled",
    ) -> ExecutionPreview:
        """Cancel and replace one retained preview snapshot."""

        with self._lock:
            preview = self._require_preview(preview_id)
            cancelled = self._planner.cancel_preview(preview, reason=reason)
            self._previews[preview_id] = cancelled
            return cancelled

    def cancel(
        self,
        preview_id: str,
        *,
        reason: str = "cancelled",
    ) -> ExecutionPreview:
        """Return :meth:`cancel_preview` for concise callers."""

        return self.cancel_preview(preview_id, reason=reason)

    def get_preview(self, preview_id: str) -> ExecutionPreview:
        """Return one retained immutable preview."""

        with self._lock:
            return self._require_preview(preview_id)

    def list_previews(self) -> tuple[ExecutionPreview, ...]:
        """Return all retained previews in creation order."""

        with self._lock:
            return tuple(self._previews.values())

    def _require_preview(self, preview_id: str) -> ExecutionPreview:
        """Return one retained preview or raise a typed lookup error."""

        if not isinstance(preview_id, str) or not preview_id:
            raise PreviewNotFoundError("a non-empty preview_id is required")
        try:
            return self._previews[preview_id]
        except KeyError as error:
            raise PreviewNotFoundError(
                f"execution preview '{preview_id}' was not found"
            ) from error


PreviewManager = ExecutionPreviewManager
PreviewService = ExecutionPreviewManager


__all__ = [
    "ExecutionPreviewManager",
    "PreviewManager",
    "PreviewService",
]
