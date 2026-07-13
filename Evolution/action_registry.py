"""Standalone typed registry for future Phase 10 action execution boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any


class ActionCategory(str, Enum):
    """The closed categories recognized by the future-action registry."""

    DESKTOP = "desktop"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    BROWSER = "browser"
    FILESYSTEM = "filesystem"
    CLIPBOARD = "clipboard"
    VISION = "vision"
    SYSTEM = "system"


def _freeze_metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return a detached read-only metadata mapping for a registered action record."""

    return MappingProxyType(dict(value or {}))


def _normalized_action_id(value: Any) -> str:
    """Return one conservative action identifier without interpreting caller input."""

    return value.strip().lower() if isinstance(value, str) else ""


@dataclass(slots=True, frozen=True)
class ActionRecord:
    """One future action descriptor containing metadata only, never executable behavior."""

    action_id: str
    category: ActionCategory
    title: str
    description: str
    requires_human_approval: bool = True
    execution_enabled: bool = False
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(slots=True, frozen=True)
class ActionRegistrationResult:
    """One typed outcome from registering a future-action descriptor."""

    decision: str
    reason_code: str
    reason: str
    action_id: str = ""
    action: ActionRecord | None = None

    @property
    def registered(self) -> bool:
        """Return True only when one new action record was retained by the registry."""

        return self.decision == "registered" and self.action is not None


@dataclass(slots=True, frozen=True)
class ActionValidationResult:
    """One typed validation result for a known future-action descriptor."""

    valid: bool
    reason_code: str
    reason: str
    action_id: str = ""
    action: ActionRecord | None = None


def _future_action(
    action_id: str,
    category: ActionCategory,
    title: str,
    description: str,
) -> ActionRecord:
    """Build one common future-action descriptor with execution permanently disabled here."""

    return ActionRecord(
        action_id=action_id,
        category=category,
        title=title,
        description=description,
        metadata=_freeze_metadata(
            {
                "phase_scope": "evolution.phase10.action_registry",
                "execution_performed": False,
                "executor_invoked": False,
            }
        ),
    )


def common_future_actions() -> tuple[ActionRecord, ...]:
    """Return the deterministic common action catalog without registering runtime behavior."""

    return (
        _future_action("desktop.open_application", ActionCategory.DESKTOP, "Open application", "Future desktop application open action."),
        _future_action("desktop.focus_window", ActionCategory.DESKTOP, "Focus window", "Future desktop window focus action."),
        _future_action("keyboard.type_text", ActionCategory.KEYBOARD, "Type text", "Future keyboard text-entry action."),
        _future_action("keyboard.press_key", ActionCategory.KEYBOARD, "Press key", "Future keyboard key-press action."),
        _future_action("mouse.move", ActionCategory.MOUSE, "Move mouse", "Future mouse movement action."),
        _future_action("mouse.click", ActionCategory.MOUSE, "Click mouse", "Future mouse click action."),
        _future_action("browser.open_url", ActionCategory.BROWSER, "Open URL", "Future browser URL-open action."),
        _future_action("browser.navigate", ActionCategory.BROWSER, "Navigate browser", "Future browser navigation action."),
        _future_action("filesystem.read_file", ActionCategory.FILESYSTEM, "Read file", "Future workspace file-read action."),
        _future_action("filesystem.write_file", ActionCategory.FILESYSTEM, "Write file", "Future workspace file-write action."),
        _future_action("clipboard.read", ActionCategory.CLIPBOARD, "Read clipboard", "Future clipboard read action."),
        _future_action("clipboard.write", ActionCategory.CLIPBOARD, "Write clipboard", "Future clipboard write action."),
        _future_action("vision.capture_screenshot", ActionCategory.VISION, "Capture screenshot", "Future screenshot capture action."),
        _future_action("vision.analyze_image", ActionCategory.VISION, "Analyze image", "Future image analysis action."),
        _future_action("system.inspect_status", ActionCategory.SYSTEM, "Inspect system status", "Future system-status inspection action."),
        _future_action("system.open_settings", ActionCategory.SYSTEM, "Open system settings", "Future system-settings action."),
    )


class ActionRegistryService:
    """Maintain a typed in-memory future-action catalog without execution or runtime wiring."""

    def __init__(self, actions: tuple[ActionRecord, ...] | None = None) -> None:
        self._actions: dict[str, ActionRecord] = {}
        initial_actions = common_future_actions() if actions is None else actions
        for action in initial_actions:
            result = self.register_action(action)
            if not result.registered:
                raise ValueError(result.reason)

    def register_action(self, action: ActionRecord) -> ActionRegistrationResult:
        """Validate and retain one new future-action descriptor without connecting it to execution."""

        validation = self._validate_record(action)
        if validation is not None:
            reason_code, reason = validation
            return ActionRegistrationResult(
                decision="rejected",
                reason_code=reason_code,
                reason=reason,
                action_id=_normalized_action_id(getattr(action, "action_id", "")),
            )

        assert isinstance(action, ActionRecord)
        action_id = action.action_id
        if action_id in self._actions:
            return ActionRegistrationResult(
                decision="rejected",
                reason_code="duplicate_action_id",
                reason="An action with this exact identifier is already registered.",
                action_id=action_id,
                action=self._actions[action_id],
            )

        stored_action = replace(action, metadata=_freeze_metadata(action.metadata))
        self._actions[action_id] = stored_action
        return ActionRegistrationResult(
            decision="registered",
            reason_code="action_registered",
            reason="The future-action descriptor was registered without enabling execution.",
            action_id=action_id,
            action=stored_action,
        )

    def get_action(self, action_id: str) -> ActionRecord | None:
        """Return one known action descriptor by identifier without exposing registry mutation."""

        return self._actions.get(_normalized_action_id(action_id))

    def validate_action(self, action: ActionRecord | str) -> ActionValidationResult:
        """Validate that an action descriptor or identifier is known and still inert."""

        if isinstance(action, ActionRecord):
            validation = self._validate_record(action)
            if validation is not None:
                reason_code, reason = validation
                return ActionValidationResult(
                    valid=False,
                    reason_code=reason_code,
                    reason=reason,
                    action_id=_normalized_action_id(action.action_id),
                )
            registered = self.get_action(action.action_id)
            if registered is None:
                return self._unknown_action(action.action_id)
            if registered != action:
                return ActionValidationResult(
                    valid=False,
                    reason_code="action_record_mismatch",
                    reason="The provided action descriptor does not match the registered immutable action record.",
                    action_id=action.action_id,
                    action=registered,
                )
            return self._valid_action(registered)

        action_id = _normalized_action_id(action)
        registered = self.get_action(action_id)
        return self._valid_action(registered) if registered is not None else self._unknown_action(action_id)

    def list_actions(self, category: ActionCategory | None = None) -> tuple[ActionRecord, ...]:
        """Return a deterministic immutable action tuple, optionally filtered by one typed category."""

        if category is not None and not isinstance(category, ActionCategory):
            return ()
        actions = self._actions.values()
        if category is not None:
            actions = (action for action in actions if action.category is category)
        return tuple(sorted(actions, key=lambda action: action.action_id))

    def list_categories(self) -> tuple[ActionCategory, ...]:
        """Return all closed action categories in deterministic declaration order."""

        return tuple(ActionCategory)

    def _validate_record(self, action: Any) -> tuple[str, str] | None:
        """Validate one action metadata record before it can be retained or trusted."""

        if not isinstance(action, ActionRecord):
            return ("invalid_action_record", "Action registration requires one typed ActionRecord.")
        action_id = _normalized_action_id(action.action_id)
        if not action_id or action_id != action.action_id or "." not in action_id:
            return ("invalid_action_id", "Action identifiers must be normalized category-qualified identifiers.")
        if not isinstance(action.category, ActionCategory) or not action_id.startswith(f"{action.category.value}."):
            return ("invalid_action_category", "Action identifiers must use the exact typed category prefix.")
        if not isinstance(action.title, str) or not action.title.strip() or not isinstance(action.description, str) or not action.description.strip():
            return ("action_description_required", "Action records require non-empty title and description metadata.")
        if action.requires_human_approval is not True:
            return ("human_approval_required", "Future actions must require explicit human approval.")
        if action.execution_enabled is not False:
            return ("action_execution_disabled", "The standalone action registry cannot register an execution-enabled action.")
        if not isinstance(action.metadata, Mapping):
            return ("invalid_action_metadata", "Action metadata must be a typed mapping.")
        return None

    def _valid_action(self, action: ActionRecord) -> ActionValidationResult:
        """Build one typed validation success for a registered inert action."""

        return ActionValidationResult(
            valid=True,
            reason_code="action_valid",
            reason="The action is registered, typed, approval-bound, and execution-disabled.",
            action_id=action.action_id,
            action=action,
        )

    def _unknown_action(self, action_id: str) -> ActionValidationResult:
        """Build one typed validation failure for an unknown action identifier."""

        return ActionValidationResult(
            valid=False,
            reason_code="unknown_action",
            reason="No registered future action matches this identifier.",
            action_id=action_id,
        )


__all__ = [
    "ActionCategory",
    "ActionRecord",
    "ActionRegistrationResult",
    "ActionRegistryService",
    "ActionValidationResult",
    "common_future_actions",
]
