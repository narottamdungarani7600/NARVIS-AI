"""Focused tests for the standalone Phase 10 execution-context framework."""

from __future__ import annotations

from dataclasses import replace
import unittest

from Evolution.execution_context import (
    ApplicationContext,
    DesktopContext,
    DisplayContext,
    ExecutionContextBuildRequest,
    ExecutionContextService,
    KeyboardContext,
    MouseContext,
    WindowContext,
    WorkspaceContext,
)


class ExecutionContextServiceTests(unittest.TestCase):
    """Verify context snapshots are typed, deterministic, read-only, and host-independent."""

    def setUp(self) -> None:
        self.service = ExecutionContextService()

    def _request(self) -> ExecutionContextBuildRequest:
        session = self.service.create_session(
            actor_id="human-reviewer",
            workspace_id="workspace-001",
            desktop_id="desktop-001",
            purpose="future-action-review",
        )
        return ExecutionContextBuildRequest(
            session=session,
            desktop=DesktopContext("desktop-001", "Windows", True),
            window=WindowContext("window-001", "application-001", "NARVIS", True, 10, 20, 900, 700),
            application=ApplicationContext("application-001", "NARVIS", "1.0", True),
            display=DisplayContext("display-001", "desktop-001", 1920, 1080),
            mouse=MouseContext("display-001", 640, 480, ()),
            keyboard=KeyboardContext("en-US", ()),
            workspace=WorkspaceContext("workspace-001", "NARVIS workspace", "workspace://narvis", True),
        )

    def test_session_identifier_is_deterministic_from_explicit_identity(self) -> None:
        first = self.service.create_session(
            actor_id="human-reviewer",
            workspace_id="workspace-001",
            desktop_id="desktop-001",
            purpose="future-action-review",
        )
        second = self.service.create_session(
            actor_id="human-reviewer",
            workspace_id="workspace-001",
            desktop_id="desktop-001",
            purpose="future-action-review",
        )

        self.assertEqual(first, second)
        self.assertTrue(first.session_id.startswith("execution_session-"))

    def test_builds_valid_snapshot_and_supports_read_only_lookup(self) -> None:
        result = self.service.build_snapshot(self._request())

        self.assertTrue(result.built)
        self.assertEqual(result.reason_code, "snapshot_built")
        assert result.snapshot is not None
        snapshot = result.snapshot
        self.assertEqual(self.service.get_snapshot(snapshot.snapshot_id), snapshot)
        self.assertEqual(self.service.list_snapshots(), (snapshot,))
        validation = self.service.validate_snapshot(snapshot)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.reason_code, "context_snapshot_valid")
        with self.assertRaises(AttributeError):
            self.service.list_snapshots().append(snapshot)  # type: ignore[attr-defined]

    def test_identical_context_build_is_deterministic_and_idempotent(self) -> None:
        request = self._request()
        first = self.service.build_snapshot(request)
        second = self.service.build_snapshot(request)

        self.assertTrue(first.built)
        self.assertTrue(second.built)
        assert first.snapshot is not None
        assert second.snapshot is not None
        self.assertEqual(first.snapshot.snapshot_id, second.snapshot.snapshot_id)
        self.assertEqual(second.reason_code, "snapshot_already_known")
        self.assertEqual(len(self.service.list_snapshots()), 1)

    def test_validation_fails_closed_for_tampered_identifiers_and_context_bindings(self) -> None:
        result = self.service.build_snapshot(self._request())
        assert result.snapshot is not None
        tampered_identifier = replace(result.snapshot, snapshot_id="execution_context_snapshot-tampered")
        invalid_mouse = replace(result.snapshot, mouse=MouseContext("display-001", 1920, 480))

        identifier_validation = self.service.validate_snapshot(tampered_identifier)
        mouse_validation = self.service.validate_snapshot(invalid_mouse)

        self.assertFalse(identifier_validation.valid)
        self.assertEqual(identifier_validation.reason_code, "snapshot_identifier_mismatch")
        self.assertFalse(mouse_validation.valid)
        self.assertEqual(mouse_validation.reason_code, "mouse_position_out_of_bounds")

    def test_invalid_build_requests_are_rejected_without_context_storage(self) -> None:
        request = self._request()
        invalid_request = replace(request, workspace=WorkspaceContext("other-workspace", "Other", "workspace://other", True))

        invalid_result = self.service.build_snapshot(invalid_request)
        untyped_validation = self.service.validate_snapshot("not-a-context-snapshot")  # type: ignore[arg-type]

        self.assertFalse(invalid_result.built)
        self.assertEqual(invalid_result.reason_code, "workspace_binding_mismatch")
        self.assertEqual(self.service.list_snapshots(), ())
        self.assertFalse(untyped_validation.valid)
        self.assertEqual(untyped_validation.reason_code, "invalid_context_snapshot")

    def test_service_has_no_runtime_or_execution_integration_surface(self) -> None:
        result = self.service.build_snapshot(self._request())

        self.assertTrue(result.built)
        self.assertFalse(hasattr(self.service, "runtime"))
        self.assertFalse(hasattr(self.service, "executor"))
        self.assertFalse(hasattr(self.service, "planner"))
        self.assertFalse(hasattr(self.service, "mutation_service"))


if __name__ == "__main__":
    unittest.main()
