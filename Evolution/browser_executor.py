"""Standalone placeholder browser executor for future Phase 10 automation work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Literal
from urllib.parse import urlsplit

from .execution_validator import ExecutionValidationReason, ExecutionValidationResult
from .models import stable_id


class BrowserOperation(str, Enum):
    """The closed browser operations represented by this offline placeholder."""

    OPEN_BROWSER = "open_browser"
    OPEN_TAB = "open_tab"
    CLOSE_TAB = "close_tab"
    SWITCH_TAB = "switch_tab"
    NAVIGATE_URL = "navigate_url"
    REFRESH_PAGE = "refresh_page"
    GO_BACK = "go_back"
    GO_FORWARD = "go_forward"
    QUERY_BROWSER = "query_browser"


@dataclass(slots=True, frozen=True)
class BrowserExecutionRequest:
    """One future browser request bound to a prior typed ALLOW validation result."""

    validation_result: ExecutionValidationResult
    operation: BrowserOperation
    browser_id: str
    url: str | None = None


@dataclass(slots=True, frozen=True)
class BrowserExecutionResult:
    """One deterministic placeholder result that never launches or controls a browser."""

    decision: Literal["simulated", "rejected"]
    reason_code: str
    reason: str
    operation: BrowserOperation | None = None
    browser_id: str = ""
    url: str = ""
    context_snapshot_id: str = ""
    execution_id: str = ""
    browser_launch_performed: bool = False
    browser_interaction_performed: bool = False
    network_accessed: bool = False
    operating_system_interaction_performed: bool = False
    filesystem_operation_performed: bool = False

    @property
    def successful(self) -> bool:
        """Return True only when one typed browser operation was simulated."""

        return self.decision == "simulated"


_BROWSER_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


class BrowserExecutorService:
    """Simulate closed browser operations without browser, network, OS, runtime, or DI integration."""

    def list_supported_operations(self) -> tuple[BrowserOperation, ...]:
        """Return all supported placeholder operations in deterministic declaration order."""

        return tuple(BrowserOperation)

    def execute(self, request: BrowserExecutionRequest) -> BrowserExecutionResult:
        """Return one offline typed simulation result after validating in-memory request data."""

        if not isinstance(request, BrowserExecutionRequest):
            return self._reject(
                reason_code="invalid_browser_execution_request",
                reason="Browser execution requires one typed BrowserExecutionRequest.",
            )
        if not isinstance(request.operation, BrowserOperation):
            return self._reject(
                reason_code="invalid_browser_operation",
                reason="Browser execution accepts only one typed supported browser operation.",
            )
        validation_error = self._validate_prior_result(request.validation_result)
        if validation_error is not None:
            reason_code, reason = validation_error
            return self._reject(
                reason_code=reason_code,
                reason=reason,
                operation=request.operation,
                validation_result=request.validation_result,
            )
        browser_id = self._normalize_browser_id(request.browser_id)
        if browser_id is None:
            return self._reject(
                reason_code="invalid_browser_identifier",
                reason="Browser identifiers must be compact local identifiers without paths, URLs, or whitespace.",
                operation=request.operation,
                validation_result=request.validation_result,
            )
        normalized_url, url_error = self._validate_url(request.operation, request.url)
        if url_error is not None:
            return self._reject(
                reason_code=url_error[0],
                reason=url_error[1],
                operation=request.operation,
                validation_result=request.validation_result,
            )

        execution_id = stable_id(
            "browser_execution_placeholder",
            request.operation.value,
            browser_id,
            normalized_url,
            request.validation_result.action_id,
            request.validation_result.context_snapshot_id,
            request.validation_result.mutation_approval_id,
            request.validation_result.recovery_outcome_id,
            request.validation_result.mutation_target_ids,
        )
        return BrowserExecutionResult(
            decision="simulated",
            reason_code="browser_operation_simulated",
            reason="The approved browser operation was represented as a deterministic offline placeholder only.",
            operation=request.operation,
            browser_id=browser_id,
            url=normalized_url or "",
            context_snapshot_id=request.validation_result.context_snapshot_id,
            execution_id=execution_id,
        )

    def _validate_prior_result(
        self,
        validation_result: ExecutionValidationResult,
    ) -> tuple[str, str] | None:
        """Require complete immutable evidence from the standalone execution validation boundary."""

        if not isinstance(validation_result, ExecutionValidationResult):
            return (
                "execution_validation_required",
                "Browser execution requires one typed prior ExecutionValidationResult.",
            )
        if (
            not validation_result.allowed
            or validation_result.decision != "ALLOW"
            or validation_result.reason is not ExecutionValidationReason.ALLOWED
        ):
            return (
                "execution_not_validated",
                "Browser execution remains denied until prior validation explicitly allows it.",
            )
        if (
            not validation_result.action_id
            or not validation_result.context_snapshot_id
            or not validation_result.mutation_approval_id
            or not validation_result.recovery_outcome_id
            or not validation_result.mutation_target_ids
        ):
            return (
                "execution_validation_binding_incomplete",
                "Browser execution requires complete action, context, approval, recovery, and target bindings.",
            )
        return None

    def _normalize_browser_id(self, value: str) -> str | None:
        """Return one normalized local browser identifier without resolving a host browser."""

        if not isinstance(value, str) or value != value.strip() or not _BROWSER_IDENTIFIER_PATTERN.fullmatch(value):
            return None
        return value.lower()

    def _validate_url(
        self,
        operation: BrowserOperation,
        value: str | None,
    ) -> tuple[str | None, tuple[str, str] | None]:
        """Validate explicit HTTP(S) URL syntax without resolving, fetching, or opening the URL."""

        if value is None:
            if operation is BrowserOperation.NAVIGATE_URL:
                return None, (
                    "browser_url_required",
                    "The navigate_url operation requires one syntactically valid HTTP(S) URL.",
                )
            return None, None
        if not isinstance(value, str) or value != value.strip() or not value or len(value) > 2048:
            return None, (
                "invalid_browser_url",
                "Browser URLs must be compact syntactically valid HTTP(S) URL strings.",
            )
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return None, (
                "invalid_browser_url",
                "Browser URLs must contain a syntactically valid HTTP(S) authority and port.",
            )
        if (
            parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None and not 1 <= port <= 65535
            or any(character.isspace() for character in value)
        ):
            return None, (
                "invalid_browser_url",
                "Browser URLs must use HTTP(S), a host, and no embedded credentials or whitespace.",
            )
        return value, None

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        operation: BrowserOperation | None = None,
        validation_result: ExecutionValidationResult | None = None,
    ) -> BrowserExecutionResult:
        """Build one typed rejection without browser launch, network access, or host interaction."""

        return BrowserExecutionResult(
            decision="rejected",
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            context_snapshot_id=(
                validation_result.context_snapshot_id
                if isinstance(validation_result, ExecutionValidationResult)
                else ""
            ),
        )


__all__ = [
    "BrowserExecutionRequest",
    "BrowserExecutionResult",
    "BrowserExecutorService",
    "BrowserOperation",
]
