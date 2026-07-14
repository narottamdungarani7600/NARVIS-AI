"""Pure preview planning from typed execution requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from Core.execution.models import ExecutionRequest, PermissionLevel
from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent
from Execution.session.models import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalToken,
    ExecutionSession,
    SessionStatus,
    new_id,
    utc_now,
)
from Execution.session.queue import EventPublisher

from .exceptions import PreviewCancelledError, PreviewValidationError
from .models import (
    ActionPreview,
    ExecutionPreview,
    PreviewStatus,
)
from .risk import PreviewRiskAnalyzer
from .summary import ApprovalContext, SummaryGenerator


class DurationEstimator(Protocol):
    """Replaceable deterministic duration estimator contract."""

    def estimate(self, request: ExecutionRequest) -> timedelta:
        """Estimate one request duration without invoking its action."""


class DefaultDurationEstimator:
    """Use explicit preview metadata or a conservative fixed duration."""

    def __init__(self, default_duration: timedelta = timedelta(seconds=1)) -> None:
        """Initialize a non-negative default estimate."""

        if not isinstance(default_duration, timedelta):
            raise TypeError("default_duration must be a timedelta")
        if default_duration < timedelta(0):
            raise ValueError("default_duration cannot be negative")
        self._default_duration = default_duration

    def estimate(self, request: ExecutionRequest) -> timedelta:
        """Return the declared seconds estimate or the configured default."""

        if not isinstance(request, ExecutionRequest):
            raise PreviewValidationError(
                "duration estimation requires an ExecutionRequest"
            )
        declared = request.metadata.get("estimated_duration_seconds")
        if declared is None:
            return self._default_duration
        if isinstance(declared, bool) or not isinstance(declared, (int, float)):
            raise PreviewValidationError("estimated_duration_seconds must be numeric")
        seconds = float(declared)
        if seconds < 0 or seconds != seconds:
            raise PreviewValidationError(
                "estimated_duration_seconds cannot be negative or NaN"
            )
        return timedelta(seconds=seconds)


class PreviewPlanner:
    """Generate and revise immutable previews without execution capability."""

    PREVIEW_CREATED_EVENT = "execution.preview.created"
    PREVIEW_UPDATED_EVENT = "execution.preview.updated"
    PREVIEW_CANCELLED_EVENT = "execution.preview.cancelled"

    def __init__(
        self,
        risk_analyzer: PreviewRiskAnalyzer | None = None,
        summary_generator: SummaryGenerator | None = None,
        duration_estimator: DurationEstimator | None = None,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        """Initialize all planning collaborators through dependency injection."""

        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.execution.preview.planner")
        self._clock = clock
        self._id_factory = id_factory
        self._risk_analyzer = risk_analyzer or PreviewRiskAnalyzer(
            event_bus=event_bus,
            logger=self._logger,
            clock=clock,
        )
        self._summary_generator = summary_generator or SummaryGenerator(clock=clock)
        self._duration_estimator = duration_estimator or DefaultDurationEstimator()

    @property
    def risk_analyzer(self) -> PreviewRiskAnalyzer:
        """Return the injected scoring service."""

        return self._risk_analyzer

    @property
    def summary_generator(self) -> SummaryGenerator:
        """Return the injected summary service."""

        return self._summary_generator

    def generate(
        self,
        request: ExecutionRequest,
        *,
        session: ExecutionSession | None = None,
        actions: Sequence[ActionPreview] | None = None,
        approval: ApprovalContext = None,
        metadata: Mapping[str, Any] | None = None,
        preview_id: str | None = None,
    ) -> ExecutionPreview:
        """Generate one complete immutable dry-run preview."""

        self._validate_request(request)
        now = self._now()
        session_id = self._validate_session(session, now=now)
        if not session_id and isinstance(approval, ApprovalRequest):
            session_id = approval.session_id
        elif not session_id and isinstance(approval, ApprovalToken):
            session_id = approval.session_id
        elif (
            not session_id
            and isinstance(approval, ApprovalResponse)
            and approval.token is not None
        ):
            session_id = approval.token.session_id
        self._validate_approval_binding(
            approval,
            request=request,
            session_id=session_id,
        )
        ordered = self._actions_for(request, actions)
        resolved_preview_id = preview_id or self._make_id()
        risk_analysis = self._risk_analyzer.analyze(
            request,
            ordered,
            preview_id=resolved_preview_id,
        )
        approval_status = self._summary_generator.approval_status(approval)
        summary = self._summary_generator.generate(
            ordered,
            risk_analysis,
            approval=approval_status,
        )
        execution_metadata = dict(request.metadata)
        if metadata is not None:
            if not isinstance(metadata, Mapping):
                raise PreviewValidationError("preview metadata must be a mapping")
            execution_metadata.update(metadata)
        preview = ExecutionPreview(
            execution_request=request,
            actions=ordered,
            summary=summary,
            risk_analysis=risk_analysis,
            preview_id=resolved_preview_id,
            session_id=session_id,
            approval_status=approval_status,
            metadata=execution_metadata,
            created_at=now,
            updated_at=now,
        )
        self._log_generation(preview, "generated")
        self._publish(self.PREVIEW_CREATED_EVENT, preview)
        return preview

    def plan(
        self,
        request: ExecutionRequest,
        **kwargs: Any,
    ) -> ExecutionPreview:
        """Return :meth:`generate` for planner-oriented callers."""

        return self.generate(request, **kwargs)

    def create_preview(
        self,
        request: ExecutionRequest,
        **kwargs: Any,
    ) -> ExecutionPreview:
        """Return :meth:`generate` for preview-oriented callers."""

        return self.generate(request, **kwargs)

    def revise(
        self,
        preview: ExecutionPreview,
        *,
        actions: Sequence[ActionPreview] | None = None,
        approval: ApprovalContext = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionPreview:
        """Return a revised immutable preview with recomputed risk and summary."""

        if not isinstance(preview, ExecutionPreview):
            raise TypeError("revise requires an ExecutionPreview")
        if preview.cancelled:
            raise PreviewCancelledError("cancelled previews cannot be revised")
        now = self._now()
        ordered = (
            self._actions_for(preview.execution_request, actions)
            if actions is not None
            else preview.actions
        )
        self._validate_approval_binding(
            approval,
            request=preview.execution_request,
            session_id=preview.session_id,
        )
        risk_analysis = self._risk_analyzer.analyze(
            preview.execution_request,
            ordered,
            preview_id=preview.preview_id,
        )
        approval_context: ApprovalContext = (
            preview.approval_status if approval is None else approval
        )
        approval_status = self._summary_generator.approval_status(approval_context)
        summary = self._summary_generator.generate(
            ordered,
            risk_analysis,
            approval=approval_status,
        )
        revised_metadata = dict(preview.metadata)
        if metadata is not None:
            if not isinstance(metadata, Mapping):
                raise PreviewValidationError("preview metadata must be a mapping")
            revised_metadata.update(metadata)
        revised = ExecutionPreview(
            execution_request=preview.execution_request,
            actions=ordered,
            summary=summary,
            risk_analysis=risk_analysis,
            preview_id=preview.preview_id,
            session_id=preview.session_id,
            approval_status=approval_status,
            metadata=revised_metadata,
            status=PreviewStatus.UPDATED,
            created_at=preview.created_at,
            updated_at=now,
        )
        self._log_generation(revised, "updated")
        self._publish(self.PREVIEW_UPDATED_EVENT, revised)
        return revised

    def update_preview(
        self,
        preview: ExecutionPreview,
        **kwargs: Any,
    ) -> ExecutionPreview:
        """Return :meth:`revise` for lifecycle-oriented callers."""

        return self.revise(preview, **kwargs)

    def cancel_preview(
        self,
        preview: ExecutionPreview,
        *,
        reason: str = "cancelled",
    ) -> ExecutionPreview:
        """Return an immutable cancelled preview without invoking any action."""

        if not isinstance(preview, ExecutionPreview):
            raise TypeError("cancel_preview requires an ExecutionPreview")
        if preview.cancelled:
            raise PreviewCancelledError("preview is already cancelled")
        if not isinstance(reason, str) or not reason or len(reason) > 1024:
            raise PreviewValidationError(
                "cancellation reason must be a non-empty string"
            )
        now = self._now()
        summary = self._summary_generator.generate(
            preview.actions,
            preview.risk_analysis,
            approval=preview.approval_status,
            cancelled=True,
        )
        cancelled_metadata = dict(preview.metadata)
        cancelled_metadata["cancellation_reason"] = reason
        cancelled = ExecutionPreview(
            execution_request=preview.execution_request,
            actions=preview.actions,
            summary=summary,
            risk_analysis=preview.risk_analysis,
            preview_id=preview.preview_id,
            session_id=preview.session_id,
            approval_status=preview.approval_status,
            metadata=cancelled_metadata,
            status=PreviewStatus.CANCELLED,
            created_at=preview.created_at,
            updated_at=now,
        )
        self._log_generation(cancelled, "cancelled")
        self._publish(
            self.PREVIEW_CANCELLED_EVENT,
            cancelled,
            reason=reason,
        )
        return cancelled

    def _actions_for(
        self,
        request: ExecutionRequest,
        actions: Sequence[ActionPreview] | None,
    ) -> tuple[ActionPreview, ...]:
        """Return explicit actions or construct one inert request action."""

        if actions is not None:
            if isinstance(actions, (str, bytes, Mapping)):
                raise PreviewValidationError(
                    "actions must be a sequence of ActionPreview instances"
                )
            ordered = tuple(actions)
            if not ordered:
                raise PreviewValidationError(
                    "execution previews require at least one action"
                )
            if any(not isinstance(action, ActionPreview) for action in ordered):
                raise PreviewValidationError(
                    "actions must contain ActionPreview instances"
                )
            return self._validate_actions(ordered)

        description = request.metadata.get("preview_description", "")
        if not isinstance(description, str):
            raise PreviewValidationError("preview_description must be a string")
        rollback_available = request.metadata.get("rollback_available", False)
        if not isinstance(rollback_available, bool):
            raise PreviewValidationError("rollback_available must be a bool")
        return (
            ActionPreview(
                action=request.action,
                order=1,
                description=description,
                estimated_duration=self._duration_estimator.estimate(request),
                required_permission=request.permission_level,
                rollback_available=rollback_available,
                parameters=request.parameters,
                metadata={"source": "execution_request"},
                action_id=request.request_id,
            ),
        )

    @staticmethod
    def _validate_request(request: ExecutionRequest) -> None:
        """Require a normalized typed execution request."""

        if not isinstance(request, ExecutionRequest):
            raise PreviewValidationError(
                "preview planning requires an ExecutionRequest"
            )
        if (
            not isinstance(request.request_id, str)
            or not request.request_id
            or request.request_id != request.request_id.strip()
            or len(request.request_id) > 128
        ):
            raise PreviewValidationError("execution request_id is invalid")
        if (
            not isinstance(request.action, str)
            or not request.action
            or request.action != request.action.strip()
            or len(request.action) > 256
        ):
            raise PreviewValidationError("execution action is invalid")
        if not isinstance(request.permission_level, PermissionLevel):
            raise PreviewValidationError("execution permission level is invalid")
        if not isinstance(request.parameters, Mapping) or not isinstance(
            request.metadata, Mapping
        ):
            raise PreviewValidationError(
                "execution parameters and metadata must be mappings"
            )

    @staticmethod
    def _validate_actions(
        actions: tuple[ActionPreview, ...],
    ) -> tuple[ActionPreview, ...]:
        """Validate ordering before scoring or lifecycle events are emitted."""

        if tuple(action.order for action in actions) != tuple(
            range(1, len(actions) + 1)
        ):
            raise PreviewValidationError(
                "actions must be ordered contiguously starting at 1"
            )
        action_ids = tuple(action.action_id for action in actions)
        if len(set(action_ids)) != len(action_ids):
            raise PreviewValidationError("action identifiers must be unique")
        return actions

    @staticmethod
    def _validate_session(
        session: ExecutionSession | None,
        *,
        now: datetime,
    ) -> str:
        """Return an active session binding or the optional empty binding."""

        if session is None:
            return ""
        if not isinstance(session, ExecutionSession):
            raise PreviewValidationError("session must be an ExecutionSession or None")
        if session.status is not SessionStatus.ACTIVE or session.is_expired(now):
            raise PreviewValidationError(
                "execution previews require an active, unexpired session"
            )
        return session.session_id

    @staticmethod
    def _validate_approval_binding(
        approval: ApprovalContext,
        *,
        request: ExecutionRequest,
        session_id: str,
    ) -> None:
        """Validate exact bindings available on existing approval requests."""

        if isinstance(approval, ApprovalRequest):
            if approval.execution_request_id != request.request_id:
                raise PreviewValidationError(
                    "approval request belongs to another execution request"
                )
            if session_id and approval.session_id != session_id:
                raise PreviewValidationError(
                    "approval request belongs to another execution session"
                )
        elif isinstance(approval, ApprovalToken):
            if session_id and approval.session_id != session_id:
                raise PreviewValidationError(
                    "approval token belongs to another execution session"
                )
        elif isinstance(approval, ApprovalResponse):
            if (
                session_id
                and approval.token is not None
                and approval.token.session_id != session_id
            ):
                raise PreviewValidationError(
                    "approval response belongs to another execution session"
                )
        elif approval is not None and not isinstance(
            approval,
            ApprovalStatus,
        ):
            raise PreviewValidationError("unsupported approval context")

    def _publish(
        self,
        event_name: str,
        preview: ExecutionPreview,
        **extra: object,
    ) -> None:
        """Publish a non-sensitive preview lifecycle event."""

        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "preview_id": preview.preview_id,
            "request_id": preview.request_id,
            "session_id": preview.session_id,
            "status": preview.status.value,
            "action_count": preview.summary.action_count,
            "estimated_duration_seconds": (preview.summary.estimated_duration_seconds),
            "approval_required": preview.summary.approval_required,
            "rollback_available": preview.summary.rollback_available,
            "execution_readiness": preview.summary.readiness.value,
            "risk_level": preview.risk_analysis.level.value,
            "dry_run": True,
            "executed": False,
            "dispatcher_invoked": False,
        }
        payload.update(extra)
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish execution preview event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log_generation(self, preview: ExecutionPreview, outcome: str) -> None:
        """Log preview generation and lifecycle changes."""

        self._log(
            LogLevel.INFO,
            f"Execution preview {outcome}",
            preview_id=preview.preview_id,
            request_id=preview.request_id,
            session_id=preview.session_id,
            action_count=preview.summary.action_count,
            risk_level=preview.risk_analysis.level.value,
            dry_run=True,
            executed=False,
            dispatcher_invoked=False,
        )

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise PreviewValidationError(
                "preview planner clock must return an aware datetime"
            )
        return value

    def _make_id(self) -> str:
        """Return and validate one injected opaque identifier."""

        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise PreviewValidationError(
                "id_factory must return normalized non-empty text"
            )
        return value

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failure to alter preview state."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


ExecutionPreviewPlanner = PreviewPlanner


__all__ = [
    "DefaultDurationEstimator",
    "DurationEstimator",
    "ExecutionPreviewPlanner",
    "PreviewPlanner",
]
