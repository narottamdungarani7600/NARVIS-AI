"""Focused tests for the standalone Phase 10 action registry."""

from __future__ import annotations

import unittest

from Evolution.action_registry import ActionCategory, ActionRecord, ActionRegistryService


class ActionRegistryServiceTests(unittest.TestCase):
    """Verify future-action descriptors remain typed, deterministic, and execution-disabled."""

    def setUp(self) -> None:
        self.registry = ActionRegistryService()

    def test_common_future_actions_cover_every_required_category(self) -> None:
        actions = self.registry.list_actions()

        self.assertIsInstance(actions, tuple)
        self.assertEqual([action.action_id for action in actions], sorted(action.action_id for action in actions))
        self.assertEqual({action.category for action in actions}, set(ActionCategory))
        self.assertTrue(all(action.requires_human_approval for action in actions))
        self.assertTrue(all(not action.execution_enabled for action in actions))
        self.assertTrue(all(not action.metadata["execution_performed"] for action in actions))
        self.assertEqual(self.registry.list_categories(), tuple(ActionCategory))

    def test_register_lookup_and_validate_a_typed_inert_action(self) -> None:
        action = ActionRecord(
            action_id="desktop.inspect_window",
            category=ActionCategory.DESKTOP,
            title="Inspect window",
            description="Future desktop window-inspection action.",
            metadata={"origin": "unit-test"},
        )

        registration = self.registry.register_action(action)
        lookup = self.registry.get_action("DESKTOP.INSPECT_WINDOW")
        validation = self.registry.validate_action(action)

        self.assertTrue(registration.registered)
        self.assertEqual(registration.reason_code, "action_registered")
        self.assertIs(lookup, registration.action)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.reason_code, "action_valid")
        assert lookup is not None
        self.assertFalse(lookup.execution_enabled)

    def test_duplicate_action_registration_is_rejected_without_overwriting_record(self) -> None:
        original = self.registry.get_action("browser.open_url")
        duplicate = ActionRecord(
            action_id="browser.open_url",
            category=ActionCategory.BROWSER,
            title="Different title",
            description="A duplicate record that must not replace the common action.",
        )

        result = self.registry.register_action(duplicate)

        self.assertFalse(result.registered)
        self.assertEqual(result.reason_code, "duplicate_action_id")
        self.assertIs(result.action, original)
        self.assertIs(self.registry.get_action("browser.open_url"), original)

    def test_invalid_records_fail_closed_before_registration(self) -> None:
        invalid_category = ActionRecord(
            action_id="desktop.inspect_window",
            category=ActionCategory.KEYBOARD,
            title="Inspect window",
            description="The category prefix is intentionally invalid.",
        )
        execution_enabled = ActionRecord(
            action_id="system.inspect_logs",
            category=ActionCategory.SYSTEM,
            title="Inspect logs",
            description="The execution flag is intentionally invalid.",
            execution_enabled=True,
        )

        category_result = self.registry.register_action(invalid_category)
        execution_result = self.registry.register_action(execution_enabled)

        self.assertFalse(category_result.registered)
        self.assertEqual(category_result.reason_code, "invalid_action_category")
        self.assertFalse(execution_result.registered)
        self.assertEqual(execution_result.reason_code, "action_execution_disabled")
        self.assertIsNone(self.registry.get_action("system.inspect_logs"))

    def test_unknown_or_altered_actions_fail_validation(self) -> None:
        unknown = self.registry.validate_action("filesystem.delete_file")
        registered = self.registry.get_action("clipboard.read")
        assert registered is not None
        altered = ActionRecord(
            action_id=registered.action_id,
            category=registered.category,
            title="Altered clipboard read",
            description=registered.description,
            metadata=registered.metadata,
        )
        mismatch = self.registry.validate_action(altered)

        self.assertFalse(unknown.valid)
        self.assertEqual(unknown.reason_code, "unknown_action")
        self.assertFalse(mismatch.valid)
        self.assertEqual(mismatch.reason_code, "action_record_mismatch")

    def test_enumeration_and_registered_metadata_are_read_only(self) -> None:
        browser_actions = self.registry.list_actions(ActionCategory.BROWSER)
        first_action = browser_actions[0]

        self.assertEqual({action.category for action in browser_actions}, {ActionCategory.BROWSER})
        with self.assertRaises(TypeError):
            first_action.metadata["changed"] = True  # type: ignore[index]
        with self.assertRaises(AttributeError):
            browser_actions.append(first_action)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
