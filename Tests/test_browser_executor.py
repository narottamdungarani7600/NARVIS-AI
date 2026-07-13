"""Focused tests for the standalone Phase 10 offline browser executor."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.browser_executor import (
    BrowserExecutionRequest,
    BrowserExecutorService,
    BrowserOperation,
)
from Evolution.execution_validator import ExecutionValidationReason, ExecutionValidationResult


class BrowserExecutorServiceTests(unittest.TestCase):
    """Verify browser simulations stay validated, deterministic, and completely offline."""

    def setUp(self) -> None:
        self.executor = BrowserExecutorService()

    def _validation(self) -> ExecutionValidationResult:
        return ExecutionValidationResult(
            decision="ALLOW",
            reason=ExecutionValidationReason.ALLOWED,
            detail="A complete future request was validated without execution.",
            action_id="browser.navigate",
            context_snapshot_id="execution-context-001",
            mutation_approval_id="mutation-approval-001",
            recovery_outcome_id="recovery-outcome-001",
            mutation_target_ids=("target-001",),
        )

    def test_all_supported_operations_return_deterministic_offline_placeholder_results(self) -> None:
        self.assertEqual(self.executor.list_supported_operations(), tuple(BrowserOperation))
        for operation in BrowserOperation:
            with self.subTest(operation=operation.value):
                url = "https://example.com/guide?phase=10" if operation is BrowserOperation.NAVIGATE_URL else None
                request = BrowserExecutionRequest(self._validation(), operation, "Chrome.Stable", url)
                first = self.executor.execute(request)
                second = self.executor.execute(request)

                self.assertTrue(first.successful)
                self.assertEqual(first.decision, "simulated")
                self.assertEqual(first.reason_code, "browser_operation_simulated")
                self.assertEqual(first.operation, operation)
                self.assertEqual(first.browser_id, "chrome.stable")
                self.assertEqual(first.execution_id, second.execution_id)
                self.assertFalse(first.browser_launch_performed)
                self.assertFalse(first.browser_interaction_performed)
                self.assertFalse(first.network_accessed)
                self.assertFalse(first.operating_system_interaction_performed)
                self.assertFalse(first.filesystem_operation_performed)

    def test_rejects_missing_denied_or_incomplete_prior_validation(self) -> None:
        missing = self.executor.execute(
            BrowserExecutionRequest(None, BrowserOperation.OPEN_BROWSER, "chrome")  # type: ignore[arg-type]
        )
        denied = self.executor.execute(
            BrowserExecutionRequest(
                replace(self._validation(), decision="DENY"),
                BrowserOperation.OPEN_BROWSER,
                "chrome",
            )
        )
        incomplete = self.executor.execute(
            BrowserExecutionRequest(
                replace(self._validation(), mutation_target_ids=()),
                BrowserOperation.OPEN_BROWSER,
                "chrome",
            )
        )

        self.assertEqual(missing.reason_code, "execution_validation_required")
        self.assertEqual(denied.reason_code, "execution_not_validated")
        self.assertEqual(incomplete.reason_code, "execution_validation_binding_incomplete")

    def test_rejects_invalid_operations_and_browser_identifiers(self) -> None:
        invalid_operation = self.executor.execute(
            BrowserExecutionRequest(
                self._validation(),
                "download_file",  # type: ignore[arg-type]
                "chrome",
            )
        )
        invalid_identifiers = ("", "chrome browser", "../chrome", "https://example.invalid/browser")

        self.assertEqual(invalid_operation.reason_code, "invalid_browser_operation")
        for browser_id in invalid_identifiers:
            with self.subTest(browser_id=browser_id):
                result = self.executor.execute(
                    BrowserExecutionRequest(self._validation(), BrowserOperation.QUERY_BROWSER, browser_id)
                )
                self.assertEqual(result.reason_code, "invalid_browser_identifier")

    def test_requires_and_validates_urls_syntactically_without_network_access(self) -> None:
        missing_url = self.executor.execute(
            BrowserExecutionRequest(self._validation(), BrowserOperation.NAVIGATE_URL, "chrome")
        )
        invalid_urls = ("", "example.com/path", "ftp://example.com", "https:///missing-host", "https://user@example.com")

        self.assertEqual(missing_url.reason_code, "browser_url_required")
        for url in invalid_urls:
            with self.subTest(url=url):
                result = self.executor.execute(
                    BrowserExecutionRequest(self._validation(), BrowserOperation.NAVIGATE_URL, "chrome", url)
                )
                self.assertEqual(result.reason_code, "invalid_browser_url")
                self.assertFalse(result.network_accessed)

    def test_denied_results_never_claim_browser_network_or_host_interaction(self) -> None:
        result = self.executor.execute(
            BrowserExecutionRequest(
                self._validation(),
                BrowserOperation.OPEN_TAB,
                "chrome",
                "file:///C:/restricted.txt",
            )
        )

        self.assertFalse(result.successful)
        self.assertFalse(result.browser_launch_performed)
        self.assertFalse(result.browser_interaction_performed)
        self.assertFalse(result.network_accessed)
        self.assertFalse(result.operating_system_interaction_performed)
        self.assertFalse(result.filesystem_operation_performed)

    def test_service_has_no_runtime_browser_or_network_integration(self) -> None:
        result = self.executor.execute(
            BrowserExecutionRequest(self._validation(), BrowserOperation.OPEN_BROWSER, "chrome")
        )

        self.assertTrue(result.successful)
        self.assertFalse(hasattr(self.executor, "runtime"))
        self.assertFalse(hasattr(self.executor, "browser"))
        self.assertFalse(hasattr(self.executor, "network_client"))
        self.assertFalse(hasattr(self.executor, "desktop_executor"))
        self.assertFalse(hasattr(self.executor, "next_executor"))


if __name__ == "__main__":
    unittest.main()
