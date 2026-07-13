"""Deterministic verification for trusted execution results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from Core.logger import LogLevel, Logger, NullLogger

from .models import (
    ExecutionResult,
    VerificationReport,
    VerificationStatus,
)


class VerificationService(Protocol):
    """Verification contract consumed by the trusted gateway."""

    def verify(
        self,
        result: ExecutionResult,
        expected_outcome: Mapping[str, Any] | None = None,
    ) -> VerificationReport:
        """Return a structured verification report."""


class VerificationEngine:
    """Verify completion and expected output without creating side effects."""

    def __init__(self, *, logger: Logger | None = None) -> None:
        """Initialize the verification boundary."""

        self._logger = logger or NullLogger("narvis.execution.verifier")

    def verify(
        self,
        result: ExecutionResult,
        expected_outcome: Mapping[str, Any] | None = None,
    ) -> VerificationReport:
        """Return a structured report for one execution result.

        Expected mappings are treated as assertions: every expected key and
        value must appear in the actual output, while additional actual output
        remains valid for forward-compatible providers.
        """

        if not isinstance(result, ExecutionResult):
            report = VerificationReport(
                request_id="",
                action="",
                status=VerificationStatus.FAILED,
                completion_verified=False,
                outcome_verified=False,
                reason_code="invalid_execution_result",
                message="Verification requires a typed ExecutionResult.",
            )
            self._log_report(report)
            return report

        if expected_outcome is not None and not self._is_string_mapping(
            expected_outcome
        ):
            report = VerificationReport(
                request_id=result.request_id,
                action=result.action,
                status=VerificationStatus.FAILED,
                completion_verified=self.verify_completion(result),
                outcome_verified=False,
                reason_code="invalid_expected_outcome",
                message="Expected outcome must be a string-keyed mapping.",
                actual_outcome=(
                    result.output if isinstance(result.output, Mapping) else {}
                ),
            )
            self._log_report(report)
            return report

        if not self._is_string_mapping(result.output):
            report = VerificationReport(
                request_id=result.request_id,
                action=result.action,
                status=VerificationStatus.FAILED,
                completion_verified=self.verify_completion(result),
                outcome_verified=False,
                reason_code="invalid_execution_output",
                message="Execution output must be a string-keyed mapping.",
                expected_outcome=expected_outcome or {},
            )
            self._log_report(report)
            return report

        completion_verified = self.verify_completion(result)
        outcome_verified = self.verify_expected_outcome(
            result.output,
            expected_outcome,
        )
        if not completion_verified:
            status = VerificationStatus.FAILED
            reason_code = "execution_not_completed"
            message = "Execution did not report successful completion."
        elif not outcome_verified:
            status = VerificationStatus.FAILED
            reason_code = "expected_outcome_mismatch"
            message = "Execution output did not satisfy the expected outcome."
        else:
            status = VerificationStatus.PASSED
            reason_code = "verification_passed"
            message = "Execution completion and expected outcome were verified."

        report = VerificationReport(
            request_id=result.request_id,
            action=result.action,
            status=status,
            completion_verified=completion_verified,
            outcome_verified=outcome_verified,
            reason_code=reason_code,
            message=message,
            expected_outcome=expected_outcome or {},
            actual_outcome=result.output,
        )
        self._log_report(report)
        return report

    async def verify_async(
        self,
        result: ExecutionResult,
        expected_outcome: Mapping[str, Any] | None = None,
    ) -> VerificationReport:
        """Provide an awaitable compatibility point for future verification."""

        return self.verify(result, expected_outcome)

    def verify_result(
        self,
        result: ExecutionResult,
        expected_outcome: Mapping[str, Any] | None = None,
    ) -> VerificationReport:
        """Verify a result using explicit engine terminology."""

        return self.verify(result, expected_outcome)

    @staticmethod
    def verify_completion(result: ExecutionResult) -> bool:
        """Return whether the result contract confirms completion."""

        return isinstance(result, ExecutionResult) and result.successful

    @staticmethod
    def verify_expected_outcome(
        actual_outcome: Mapping[str, Any],
        expected_outcome: Mapping[str, Any] | None,
    ) -> bool:
        """Return whether all expected top-level values match actual output."""

        if expected_outcome is None:
            return True
        return all(
            key in actual_outcome and actual_outcome[key] == expected_value
            for key, expected_value in expected_outcome.items()
        )

    @staticmethod
    def _is_string_mapping(value: object) -> bool:
        """Return whether a value is a mapping with string keys."""

        return isinstance(value, Mapping) and all(
            isinstance(key, str) for key in value
        )

    def _log_report(self, report: VerificationReport) -> None:
        """Log one verification stage without altering its report."""

        self._log(
            LogLevel.INFO if report.passed else LogLevel.WARNING,
            "Execution result verified",
            request_id=report.request_id,
            action=report.action,
            status=report.status.value,
            completion_verified=report.completion_verified,
            outcome_verified=report.outcome_verified,
            reason_code=report.reason_code,
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a structured log without changing verification."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["VerificationEngine", "VerificationService"]
