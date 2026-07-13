"""Focused tests for the standalone Phase 10 placeholder application executor."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.application_executor import (
    ApplicationExecutionRequest,
    ApplicationExecutorService,
    ApplicationOperation,
)
from Evolution.execution_validator import ExecutionValidationReason, ExecutionValidationResult


class ApplicationExecutorServiceTests(unittest.TestCase):
    """Verify application simulations stay validated, deterministic, and host-independent."""

    def setUp(self) -> None:
        self.executor = ApplicationExecutorService()

    def _validation(self) -> ExecutionValidationResult:
        return ExecutionValidationResult(
            decision="ALLOW",
            reason=ExecutionValidationReason.ALLOWED,
            detail="A complete future request was validated without execution.",
            action_id="desktop.open_application",
            context_snapshot_id="execution-context-001",
            mutation_approval_id="mutation-approval-001",
            recovery_outcome_id="recovery-outcome-001",
            mutation_target_ids=("target-001",),
        )

    def test_all_supported_operations_return_deterministic_placeholder_results(self) -> None:
        self.assertEqual(self.executor.list_supported_operations(), tuple(ApplicationOperation))
        for operation in ApplicationOperation:
            with self.subTest(operation=operation.value):
                request = ApplicationExecutionRequest(self._validation(), operation, "NARVIS.Desktop")
                first = self.executor.execute(request)
                second = self.executor.execute(request)

                self.assertTrue(first.successful)
                self.assertEqual(first.decision, "simulated")
                self.assertEqual(first.reason_code, "application_operation_simulated")
                self.assertEqual(first.operation, operation)
                self.assertEqual(first.application_id, "narvis.desktop")
                self.assertEqual(first.execution_id, second.execution_id)
                self.assertFalse(first.operating_system_interaction_performed)
                self.assertFalse(first.process_created)
                self.assertFalse(first.process_terminated)
                self.assertFalse(first.desktop_interaction_performed)
                self.assertFalse(first.filesystem_operation_performed)

    def test_rejects_missing_denied_or_incomplete_prior_validation(self) -> None:
        missing = self.executor.execute(
            ApplicationExecutionRequest(None, ApplicationOperation.LAUNCH_APPLICATION, "narvis.desktop")  # type: ignore[arg-type]
        )
        denied = self.executor.execute(
            ApplicationExecutionRequest(
                replace(self._validation(), decision="DENY"),
                ApplicationOperation.LAUNCH_APPLICATION,
                "narvis.desktop",
            )
        )
        incomplete = self.executor.execute(
            ApplicationExecutionRequest(
                replace(self._validation(), mutation_target_ids=()),
                ApplicationOperation.LAUNCH_APPLICATION,
                "narvis.desktop",
            )
        )

        self.assertEqual(missing.reason_code, "execution_validation_required")
        self.assertEqual(denied.reason_code, "execution_not_validated")
        self.assertEqual(incomplete.reason_code, "execution_validation_binding_incomplete")

    def test_rejects_invalid_operations_and_application_identifiers(self) -> None:
        invalid_operation = self.executor.execute(
            ApplicationExecutionRequest(
                self._validation(),
                "terminate_all",  # type: ignore[arg-type]
                "narvis.desktop",
            )
        )
        invalid_identifiers = ("", "notepad app", "../notepad", "https://example.invalid/app")

        self.assertEqual(invalid_operation.reason_code, "invalid_application_operation")
        for application_id in invalid_identifiers:
            with self.subTest(application_id=application_id):
                result = self.executor.execute(
                    ApplicationExecutionRequest(
                        self._validation(),
                        ApplicationOperation.QUERY_APPLICATION,
                        application_id,
                    )
                )
                self.assertEqual(result.reason_code, "invalid_application_identifier")

    def test_denied_results_never_claim_process_or_host_interaction(self) -> None:
        result = self.executor.execute(
            ApplicationExecutionRequest(
                self._validation(),
                ApplicationOperation.RESTART_APPLICATION,
                "../narvis.desktop",
            )
        )

        self.assertFalse(result.successful)
        self.assertFalse(result.operating_system_interaction_performed)
        self.assertFalse(result.process_created)
        self.assertFalse(result.process_terminated)
        self.assertFalse(result.desktop_interaction_performed)
        self.assertFalse(result.filesystem_operation_performed)

    def test_service_has_no_runtime_process_or_desktop_integration(self) -> None:
        result = self.executor.execute(
            ApplicationExecutionRequest(
                self._validation(),
                ApplicationOperation.LAUNCH_APPLICATION,
                "narvis.desktop",
            )
        )

        self.assertTrue(result.successful)
        self.assertFalse(hasattr(self.executor, "runtime"))
        self.assertFalse(hasattr(self.executor, "process_manager"))
        self.assertFalse(hasattr(self.executor, "desktop_executor"))
        self.assertFalse(hasattr(self.executor, "filesystem"))
        self.assertFalse(hasattr(self.executor, "next_executor"))


if __name__ == "__main__":
    unittest.main()
