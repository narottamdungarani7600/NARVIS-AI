"""Focused tests for the standalone Phase 10 placeholder desktop executor."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.desktop_executor import (
    DesktopExecutionOperation,
    DesktopExecutionRequest,
    DesktopExecutorService,
)
from Evolution.execution_validator import ExecutionValidationReason, ExecutionValidationResult


class DesktopExecutorServiceTests(unittest.TestCase):
    """Verify placeholder desktop results stay validated, deterministic, and non-interacting."""

    def setUp(self) -> None:
        self.executor = DesktopExecutorService()

    def _validation(self, action_id: str) -> ExecutionValidationResult:
        return ExecutionValidationResult(
            decision="ALLOW",
            reason=ExecutionValidationReason.ALLOWED,
            detail="A complete future request was validated without execution.",
            action_id=action_id,
            context_snapshot_id="execution-context-001",
            mutation_approval_id="mutation-approval-001",
            recovery_outcome_id="recovery-outcome-001",
            mutation_target_ids=("target-001",),
        )

    def test_all_supported_operations_return_deterministic_placeholder_results(self) -> None:
        expected_actions = {
            DesktopExecutionOperation.OPEN_APPLICATION: "desktop.open_application",
            DesktopExecutionOperation.FOCUS_WINDOW: "desktop.focus_window",
            DesktopExecutionOperation.TYPE_TEXT: "keyboard.type_text",
            DesktopExecutionOperation.MOUSE_CLICK: "mouse.click",
            DesktopExecutionOperation.SCREENSHOT: "vision.capture_screenshot",
        }

        self.assertEqual(self.executor.list_supported_operations(), tuple(DesktopExecutionOperation))
        for operation, action_id in expected_actions.items():
            with self.subTest(operation=operation.value):
                request = DesktopExecutionRequest(self._validation(action_id), operation)
                first = self.executor.execute(request)
                second = self.executor.execute(request)

                self.assertTrue(first.successful)
                self.assertEqual(first.decision, "simulated")
                self.assertEqual(first.reason_code, "desktop_operation_simulated")
                self.assertEqual(first.operation, operation)
                self.assertEqual(first.execution_id, second.execution_id)
                self.assertFalse(first.desktop_interaction_performed)
                self.assertFalse(first.operating_system_api_invoked)
                self.assertFalse(first.filesystem_mutated)

    def test_rejects_missing_or_denied_prior_execution_validation(self) -> None:
        missing_validation = self.executor.execute(
            DesktopExecutionRequest(None, DesktopExecutionOperation.OPEN_APPLICATION)  # type: ignore[arg-type]
        )
        denied_validation = self.executor.execute(
            DesktopExecutionRequest(
                replace(self._validation("desktop.open_application"), decision="DENY"),
                DesktopExecutionOperation.OPEN_APPLICATION,
            )
        )

        self.assertEqual(missing_validation.reason_code, "execution_validation_required")
        self.assertEqual(denied_validation.reason_code, "execution_not_validated")
        self.assertFalse(denied_validation.desktop_interaction_performed)

    def test_rejects_incomplete_or_wrongly_typed_validation_results(self) -> None:
        incomplete_validation = self.executor.execute(
            DesktopExecutionRequest(
                replace(self._validation("desktop.open_application"), mutation_target_ids=()),
                DesktopExecutionOperation.OPEN_APPLICATION,
            )
        )
        invalid_reason = self.executor.execute(
            DesktopExecutionRequest(
                replace(
                    self._validation("desktop.open_application"),
                    reason=ExecutionValidationReason.INVALID_REQUEST,
                ),
                DesktopExecutionOperation.OPEN_APPLICATION,
            )
        )

        self.assertEqual(incomplete_validation.reason_code, "execution_validation_binding_incomplete")
        self.assertEqual(invalid_reason.reason_code, "execution_not_validated")

    def test_rejects_action_operation_mismatch_and_unknown_operations(self) -> None:
        mismatch = self.executor.execute(
            DesktopExecutionRequest(
                self._validation("desktop.open_application"),
                DesktopExecutionOperation.FOCUS_WINDOW,
            )
        )
        invalid_operation = self.executor.execute(
            DesktopExecutionRequest(
                self._validation("desktop.open_application"),
                "open_terminal",  # type: ignore[arg-type]
            )
        )

        self.assertEqual(mismatch.reason_code, "desktop_operation_action_mismatch")
        self.assertEqual(invalid_operation.reason_code, "invalid_desktop_operation")

    def test_service_has_no_runtime_or_host_control_integration(self) -> None:
        result = self.executor.execute(
            DesktopExecutionRequest(
                self._validation("desktop.open_application"),
                DesktopExecutionOperation.OPEN_APPLICATION,
            )
        )

        self.assertTrue(result.successful)
        self.assertFalse(hasattr(self.executor, "runtime"))
        self.assertFalse(hasattr(self.executor, "mouse"))
        self.assertFalse(hasattr(self.executor, "keyboard"))
        self.assertFalse(hasattr(self.executor, "window_controller"))
        self.assertFalse(hasattr(self.executor, "next_executor"))


if __name__ == "__main__":
    unittest.main()
