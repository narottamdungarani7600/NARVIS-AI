"""Fail-closed validation for coordinated execution planning."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

from Core.execution.models import ExecutionRequest, PermissionLevel
from Execution.preview.models import ExecutionPreview, PreviewRiskAnalysis
from Execution.session.models import (
    ExecutionSession,
    SessionStatus,
    immutable_mapping,
    utc_now,
)

from .models import ExecutionCoordination, ValidationReport

_PERMISSION_ORDER: dict[PermissionLevel, int] = {
    PermissionLevel.NONE: 0,
    PermissionLevel.READ_ONLY: 1,
    PermissionLevel.STANDARD: 2,
    PermissionLevel.ELEVATED: 3,
    PermissionLevel.ADMINISTRATOR: 4,
}


class CoordinatorValidator:
    """Validate all typed prerequisites without raising for ordinary failures."""

    def __init__(
        self,
        *,
        available_permissions: Iterable[PermissionLevel] = tuple(PermissionLevel),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Initialize replaceable permission and clock dependencies."""

        permissions = tuple(available_permissions)
        if any(not isinstance(item, PermissionLevel) for item in permissions):
            raise TypeError(
                "available_permissions must contain PermissionLevel members"
            )
        self._available_permissions = permissions
        self._clock = clock

    @property
    def available_permissions(self) -> tuple[PermissionLevel, ...]:
        """Return the configured permission capabilities."""

        return self._available_permissions

    def validate_initial(
        self,
        request: object,
        session: object,
        metadata: object,
        *,
        available_permissions: Iterable[PermissionLevel] | None = None,
    ) -> ValidationReport:
        """Validate request, approval session, base permission, and metadata."""

        missing: list[str] = []
        errors: list[str] = []
        now = self._now()

        if not isinstance(request, ExecutionRequest):
            missing.append("execution_request")
            errors.append("A typed ExecutionRequest is required.")
        else:
            if (
                not isinstance(request.request_id, str)
                or not request.request_id
                or request.request_id != request.request_id.strip()
                or not isinstance(request.action, str)
                or not request.action
                or request.action != request.action.strip()
            ):
                missing.append("execution_request")
                errors.append("The execution request identity is invalid.")
            if not isinstance(request.permission_level, PermissionLevel):
                missing.append("permissions")
                errors.append("The execution request permission is invalid.")
            elif not self.permission_available(
                request.permission_level,
                available_permissions=available_permissions,
            ):
                missing.append(f"permission:{request.permission_level.value}")

        if not isinstance(session, ExecutionSession):
            missing.append("approval_session")
            errors.append("A typed ExecutionSession is required.")
        elif session.status is not SessionStatus.ACTIVE or session.is_expired(now):
            missing.append("active_session")
            errors.append("The execution session is not active.")

        if not isinstance(metadata, Mapping):
            missing.append("metadata")
            errors.append("Coordinator metadata must be a mapping.")
        else:
            try:
                immutable_mapping(metadata)
            except (TypeError, ValueError):
                missing.append("metadata")
                errors.append("Coordinator metadata must use string mapping keys.")

        return self._report(missing, errors, at=now)

    def validate(
        self,
        coordination: ExecutionCoordination | None = None,
        *,
        request: ExecutionRequest | None = None,
        preview: ExecutionPreview | None = None,
        risk_analysis: PreviewRiskAnalysis | None = None,
        approval_session: ExecutionSession | None = None,
        metadata: Mapping[str, Any] | None = None,
        available_permissions: Iterable[PermissionLevel] | None = None,
    ) -> ValidationReport:
        """Validate the full preview, risk, session, permission, and metadata set."""

        if coordination is not None:
            if not isinstance(coordination, ExecutionCoordination):
                raise TypeError("coordination must be an ExecutionCoordination")
            request = coordination.request
            preview = coordination.preview
            risk_analysis = coordination.risk_analysis
            approval_session = coordination.session
            metadata = coordination.metadata

        initial = self.validate_initial(
            request,
            approval_session,
            metadata,
            available_permissions=available_permissions,
        )
        missing = list(initial.missing_requirements)
        errors = list(initial.errors)

        if not isinstance(preview, ExecutionPreview):
            missing.append("preview")
            errors.append("An ExecutionPreview is required.")
        else:
            if request is not None and preview.request_id != request.request_id:
                missing.append("request_binding")
                errors.append("The preview is bound to another execution request.")
            if (
                approval_session is not None
                and preview.session_id != approval_session.session_id
            ):
                missing.append("session_binding")
                errors.append("The preview is bound to another execution session.")
            for permission in preview.required_permissions:
                if not self.permission_available(
                    permission,
                    available_permissions=available_permissions,
                ):
                    requirement = f"permission:{permission.value}"
                    if requirement not in missing:
                        missing.append(requirement)

        if not isinstance(risk_analysis, PreviewRiskAnalysis):
            missing.append("risk_analysis")
            errors.append("A PreviewRiskAnalysis is required.")
        elif preview is not None and risk_analysis.preview_id != preview.preview_id:
            missing.append("risk_binding")
            errors.append("Risk analysis is bound to another execution preview.")

        return self._report(missing, errors, at=self._now())

    def permission_available(
        self,
        required: PermissionLevel,
        *,
        available_permissions: Iterable[PermissionLevel] | None = None,
    ) -> bool:
        """Return whether an available permission meets or exceeds ``required``."""

        if not isinstance(required, PermissionLevel):
            return False
        available = (
            tuple(available_permissions)
            if available_permissions is not None
            else self._available_permissions
        )
        if any(not isinstance(item, PermissionLevel) for item in available):
            return False
        if required is PermissionLevel.NONE:
            return True
        return any(
            _PERMISSION_ORDER[item] >= _PERMISSION_ORDER[required] for item in available
        )

    @staticmethod
    def _report(
        missing: list[str],
        errors: list[str],
        *,
        at: datetime,
    ) -> ValidationReport:
        """Build one de-duplicated immutable validation report."""

        unique_missing = tuple(dict.fromkeys(missing))
        unique_errors = tuple(dict.fromkeys(errors))
        return ValidationReport(
            valid=not unique_missing and not unique_errors,
            missing_requirements=unique_missing,
            errors=unique_errors,
            validated_at=at,
        )

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("validator clock must return an aware datetime")
        return value


ExecutionValidator = CoordinatorValidator


__all__ = ["CoordinatorValidator", "ExecutionValidator"]
