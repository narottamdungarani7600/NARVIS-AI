"""Comprehensive tests for Phase 10 Desktop Integration Layer Sprint 3."""

from __future__ import annotations

import unittest

from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Computer.core import (
    ComputerCapability,
    ComputerHealth,
    ComputerProviderInfo,
    ComputerStatus,
)
from Computer.desktop import (
    DesktopProvider,
    DisplayInfo,
    DisplayManager,
    DisplayProvider,
    DisplayRequestError,
    Key,
    KeyboardInterface,
    KeyboardProvider,
    KeyboardRequestError,
    KeyboardState,
    ModifierKey,
    ModifierKeys,
    MouseButton,
    MouseButtons,
    MouseInterface,
    MousePosition,
    MouseProvider,
    MouseRequestError,
    PointerState,
    WindowInfo,
    WindowManager,
    WindowProvider,
    WindowRequestError,
    WindowState,
)


class _CapturingLogger:
    """Core-compatible logger that records structured desktop requests."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _FailingLogger:
    def log(self, level: LogLevel, message: str, **context: object) -> None:
        raise RuntimeError("logger unavailable")


class _FailingEventBus:
    def publish(self, event: object) -> None:
        raise RuntimeError("event bus unavailable")


class _DesktopTestProvider(DesktopProvider):
    """In-memory desktop provider that cannot perform desktop actions."""

    def __init__(self, name: str = "desktop.test") -> None:
        super().__init__(
            ComputerProviderInfo(
                name,
                version="1.2.0",
                attributes={"kind": "interface-test"},
            )
        )
        self.displays: object = (
            DisplayInfo(
                "virtual",
                "Virtual",
                1280,
                720,
                x=1920,
                is_virtual=True,
            ),
            DisplayInfo(
                "primary",
                "Primary",
                1920,
                1080,
                is_primary=True,
                refresh_rate_hz=60.0,
            ),
        )
        self.windows: object = (
            WindowInfo(
                "window-2",
                "Terminal",
                WindowState.MINIMIZED,
                process_id=20,
            ),
            WindowInfo(
                "window-1",
                "Editor",
                WindowState.NORMAL,
                width=1200,
                height=800,
                process_id=10,
                display_id="primary",
                is_active=True,
            ),
            WindowInfo("window-3", "editor", WindowState.HIDDEN),
        )
        self.position_result: object = MousePosition(100, 200, "primary")
        self.buttons_result: object = MouseButtons(left=True, x1=True)
        self.keyboard_result: object = KeyboardState(
            frozenset({Key.A, Key.ENTER}),
            ModifierKeys(shift=True, control=True),
        )
        self.fail_operation: str | None = None
        self.calls: list[str] = []

    def initialize(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def health(self) -> ComputerHealth:
        return ComputerHealth(ComputerStatus.HEALTHY)

    def capabilities(self) -> tuple[ComputerCapability, ...]:
        return (
            ComputerCapability("desktop.inspect", "Desktop metadata only"),
        )

    def _record(self, operation: str) -> None:
        self.calls.append(operation)
        if self.fail_operation == operation:
            raise RuntimeError(f"{operation} unavailable")

    def enumerate_displays(self) -> tuple[DisplayInfo, ...]:
        self._record("enumerate_displays")
        return self.displays  # type: ignore[return-value]

    def enumerate_windows(self) -> tuple[WindowInfo, ...]:
        self._record("enumerate_windows")
        return self.windows  # type: ignore[return-value]

    def get_mouse_position(self) -> MousePosition:
        self._record("get_mouse_position")
        return self.position_result  # type: ignore[return-value]

    def get_mouse_buttons(self) -> MouseButtons:
        self._record("get_mouse_buttons")
        return self.buttons_result  # type: ignore[return-value]

    def get_keyboard_state(self) -> KeyboardState:
        self._record("get_keyboard_state")
        return self.keyboard_result  # type: ignore[return-value]


class _IncompleteDesktopProvider(DesktopProvider):
    def initialize(self) -> None:
        return None


class DesktopModelTests(unittest.TestCase):
    """Verify immutable display, window, mouse, and keyboard models."""

    def test_display_models_include_physical_and_virtual_metadata(self) -> None:
        attributes = {"connector": "test"}
        display = DisplayInfo(
            "display-1",
            "Primary",
            1920,
            1080,
            x=-1920,
            is_primary=True,
            is_virtual=True,
            scale_factor=1.25,
            refresh_rate_hz=144,
            attributes=attributes,
        )
        attributes["connector"] = "changed"

        self.assertEqual(display.id, "display-1")
        self.assertEqual(display.resolution, (1920, 1080))
        self.assertEqual(display.bounds, (-1920, 0, 1920, 1080))
        self.assertEqual(display.attributes["connector"], "test")
        with self.assertRaises(TypeError):
            display.attributes["new"] = True  # type: ignore[index]

    def test_display_models_reject_invalid_metadata(self) -> None:
        with self.assertRaises(ValueError):
            DisplayInfo("", "Display", 1920, 1080)
        with self.assertRaises(ValueError):
            DisplayInfo("display", "Display", 0, 1080)
        with self.assertRaises(ValueError):
            DisplayInfo("display", "Display", 1920, 1080, scale_factor=0)
        with self.assertRaises(ValueError):
            DisplayInfo("display", "Display", 1920, 1080, refresh_rate_hz=-1)
        with self.assertRaises(TypeError):
            DisplayInfo("display", "Display", True, 1080)  # type: ignore[arg-type]

    def test_window_models_expose_state_and_detached_metadata(self) -> None:
        attributes = {"workspace": 2}
        window = WindowInfo(
            "window",
            "Editor",
            WindowState.MAXIMIZED,
            x=-20,
            y=10,
            width=800,
            height=600,
            process_id=0,
            application_name="Editor",
            display_id="display",
            is_active=True,
            attributes=attributes,
        )
        attributes["workspace"] = 3

        self.assertEqual(window.id, "window")
        self.assertEqual(window.bounds, (-20, 10, 800, 600))
        self.assertTrue(window.is_maximized)
        self.assertFalse(window.is_minimized)
        self.assertEqual(window.attributes["workspace"], 2)

    def test_window_models_reject_invalid_state_and_dimensions(self) -> None:
        with self.assertRaises(TypeError):
            WindowInfo("window", "Title", "normal")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            WindowInfo("window", "Title", width=-1)
        with self.assertRaises(ValueError):
            WindowInfo("window", "Title", process_id=-1)
        with self.assertRaises(TypeError):
            WindowInfo("window", 42)  # type: ignore[arg-type]

    def test_mouse_models_support_negative_coordinates_and_button_state(self) -> None:
        position = MousePosition(-10, 30, "virtual")
        buttons = MouseButtons(left=True, middle=True)
        state = PointerState(position, buttons)

        self.assertEqual(position.coordinates, (-10, 30))
        self.assertEqual(
            buttons.pressed,
            frozenset({MouseButton.LEFT, MouseButton.MIDDLE}),
        )
        self.assertTrue(buttons.is_pressed(MouseButton.LEFT))
        self.assertIs(state.position, position)

    def test_mouse_models_reject_untyped_coordinates_and_buttons(self) -> None:
        with self.assertRaises(TypeError):
            MousePosition(True, 1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            MouseButtons(left=1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            MouseButtons().is_pressed("left")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            PointerState(MousePosition(0, 0), object())  # type: ignore[arg-type]

    def test_keyboard_models_are_typed_immutable_snapshots(self) -> None:
        keys = {Key.A, Key.F12}
        modifiers = ModifierKeys(shift=True, meta=True)
        state = KeyboardState(keys, modifiers)  # type: ignore[arg-type]
        keys.add(Key.B)

        self.assertEqual(state.pressed_keys, frozenset({Key.A, Key.F12}))
        self.assertTrue(state.is_pressed(Key.A))
        self.assertEqual(
            modifiers.active,
            frozenset({ModifierKey.SHIFT, ModifierKey.META}),
        )
        self.assertFalse(modifiers.ctrl)

    def test_keyboard_models_reject_invalid_and_inconsistent_state(self) -> None:
        with self.assertRaises(TypeError):
            KeyboardState(frozenset({"a"}))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            KeyboardState(modifiers=object())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            KeyboardState(frozenset({Key.A}), is_available=False)
        with self.assertRaises(TypeError):
            ModifierKeys(alt=1)  # type: ignore[arg-type]


class DesktopProviderTests(unittest.TestCase):
    """Verify the composite provider and its narrow structural contracts."""

    def test_provider_is_abstract_until_every_contract_is_implemented(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteDesktopProvider(ComputerProviderInfo("incomplete"))

        provider = _DesktopTestProvider()
        self.assertIsInstance(provider, DisplayProvider)
        self.assertIsInstance(provider, WindowProvider)
        self.assertIsInstance(provider, MouseProvider)
        self.assertIsInstance(provider, KeyboardProvider)
        self.assertEqual(provider.info.version, "1.2.0")

    def test_provider_contract_exposes_no_desktop_control_operations(self) -> None:
        provider = _DesktopTestProvider()
        for operation in (
            "capture_screen",
            "activate_window",
            "move_window",
            "resize_window",
            "move_mouse",
            "click",
            "press_key",
            "type_text",
        ):
            self.assertFalse(hasattr(provider, operation))


class DisplayManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = _DesktopTestProvider()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(DisplayManager.ENUMERATED_EVENT, self.events.append)
        self.manager = DisplayManager(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_enumeration_metadata_primary_and_virtual_requests_publish(self) -> None:
        displays = self.manager.enumerate_displays()
        metadata = self.manager.display_metadata("virtual")
        primary = self.manager.get_primary_display()
        virtual = self.manager.virtual_displays()

        self.assertEqual(
            [display.display_id for display in displays],
            ["primary", "virtual"],
        )
        self.assertEqual(metadata, self.provider.displays[0])  # type: ignore[index]
        self.assertEqual(primary, self.provider.displays[1])  # type: ignore[index]
        self.assertEqual(virtual, (self.provider.displays[0],))  # type: ignore[index]
        self.assertEqual(len(self.events), 4)
        self.assertEqual(self.events[0].payload["count"], 2)
        self.assertEqual(self.events[0].payload["primary_display_id"], "primary")
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Desktop display request"
        ]
        self.assertEqual(len(request_logs), 4)

    def test_empty_provider_supports_no_primary_or_metadata(self) -> None:
        self.provider.displays = ()

        self.assertEqual(self.manager.list_displays(), ())
        self.assertIsNone(self.manager.get_display("missing"))
        self.assertIsNone(self.manager.primary_display())
        self.assertEqual(self.manager.enumerate_virtual_displays(), ())
        self.assertTrue(all(event.payload["count"] == 0 for event in self.events))

    def test_provider_failure_and_invalid_results_are_typed(self) -> None:
        self.provider.fail_operation = "enumerate_displays"
        with self.assertRaises(DisplayRequestError) as raised:
            self.manager.enumerate_displays()
        self.assertEqual(raised.exception.provider_name, "desktop.test")

        self.provider.fail_operation = None
        self.provider.displays = [DisplayInfo("id", "Display", 1, 1)]
        with self.assertRaises(DisplayRequestError):
            self.manager.enumerate_displays()

        duplicate = DisplayInfo("same", "Display", 1, 1)
        self.provider.displays = (duplicate, duplicate)
        with self.assertRaises(DisplayRequestError):
            self.manager.enumerate_displays()


class WindowManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = _DesktopTestProvider()
        self.logger = _CapturingLogger()
        self.events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(WindowManager.ENUMERATED_EVENT, self.events.append)
        self.manager = WindowManager(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_enumeration_id_title_and_general_lookup_publish(self) -> None:
        windows = self.manager.enumerate_windows()
        metadata = self.manager.window_metadata("window-2")
        by_title = self.manager.find_by_title("EDITOR")
        lookup = self.manager.lookup_window("Terminal")

        self.assertEqual(
            [window.window_id for window in windows],
            ["window-1", "window-2", "window-3"],
        )
        self.assertEqual(metadata, self.provider.windows[0])  # type: ignore[index]
        self.assertEqual(
            [window.window_id for window in by_title],
            ["window-1", "window-3"],
        )
        self.assertEqual(lookup, self.provider.windows[0])  # type: ignore[index]
        self.assertEqual(len(self.events), 4)
        self.assertEqual(self.events[0].payload["active_count"], 1)
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Desktop window request"
        ]
        self.assertEqual(len(request_logs), 4)

    def test_empty_provider_returns_empty_and_missing_results(self) -> None:
        self.provider.windows = ()

        self.assertEqual(self.manager.list_windows(), ())
        self.assertIsNone(self.manager.find_by_id("missing"))
        self.assertEqual(self.manager.find_by_title("missing"), ())
        self.assertIsNone(self.manager.lookup("missing"))

    def test_provider_failure_and_duplicate_ids_are_typed(self) -> None:
        self.provider.fail_operation = "enumerate_windows"
        with self.assertRaises(WindowRequestError):
            self.manager.enumerate_windows()

        self.provider.fail_operation = None
        duplicate = WindowInfo("same", "Window")
        self.provider.windows = (duplicate, duplicate)
        with self.assertRaises(WindowRequestError):
            self.manager.enumerate_windows()

    def test_manager_has_no_window_control_operations(self) -> None:
        for operation in ("activate", "focus", "move", "resize", "close"):
            self.assertFalse(hasattr(self.manager, operation))


class InputStateInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = _DesktopTestProvider()
        self.logger = _CapturingLogger()
        self.mouse_events: list[SystemEvent] = []
        self.keyboard_events: list[SystemEvent] = []
        event_bus = EventBus()
        event_bus.subscribe(
            MouseInterface.STATE_REQUESTED_EVENT,
            self.mouse_events.append,
        )
        event_bus.subscribe(
            KeyboardInterface.STATE_REQUESTED_EVENT,
            self.keyboard_events.append,
        )
        self.mouse = MouseInterface(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )
        self.keyboard = KeyboardInterface(
            self.provider,
            logger=self.logger,
            event_bus=event_bus,
        )

    def test_mouse_state_requests_are_logged_and_published(self) -> None:
        position = self.mouse.position()
        buttons = self.mouse.buttons()
        state = self.mouse.state()

        self.assertEqual(position, MousePosition(100, 200, "primary"))
        self.assertEqual(buttons.pressed, frozenset({MouseButton.LEFT, MouseButton.X1}))
        self.assertEqual(state, PointerState(position, buttons))
        self.assertEqual(len(self.mouse_events), 3)
        self.assertEqual(self.mouse_events[0].payload["x"], 100)
        self.assertEqual(self.mouse_events[1].payload["pressed_count"], 2)
        request_logs = [
            entry
            for entry in self.logger.entries
            if entry[1] == "Desktop mouse state request"
        ]
        self.assertEqual(len(request_logs), 3)

    def test_keyboard_state_is_logged_and_event_contains_metadata_only(self) -> None:
        state = self.keyboard.keyboard_state()

        self.assertTrue(state.is_pressed(Key.A))
        self.assertTrue(state.modifiers.control)
        self.assertEqual(len(self.keyboard_events), 1)
        self.assertEqual(self.keyboard_events[0].payload["pressed_key_count"], 2)
        self.assertNotIn("pressed_keys", self.keyboard_events[0].payload)
        self.assertTrue(
            any(
                message == "Desktop keyboard state request"
                for _, message, _ in self.logger.entries
            )
        )

    def test_empty_input_states_are_supported(self) -> None:
        self.provider.position_result = MousePosition(0, 0)
        self.provider.buttons_result = MouseButtons()
        self.provider.keyboard_result = KeyboardState()

        self.assertEqual(self.mouse.get_position().coordinates, (0, 0))
        self.assertFalse(self.mouse.get_buttons().pressed)
        self.assertFalse(self.keyboard.get_state().pressed_keys)

    def test_provider_failures_and_invalid_states_are_typed(self) -> None:
        self.provider.fail_operation = "get_mouse_position"
        with self.assertRaises(MouseRequestError):
            self.mouse.get_position()

        self.provider.fail_operation = None
        self.provider.buttons_result = "invalid"
        with self.assertRaises(MouseRequestError):
            self.mouse.get_buttons()

        self.provider.keyboard_result = "invalid"
        with self.assertRaises(KeyboardRequestError):
            self.keyboard.get_state()

    def test_interfaces_have_no_input_injection_operations(self) -> None:
        for operation in ("move", "click", "drag", "scroll"):
            self.assertFalse(hasattr(self.mouse, operation))
        for operation in ("press", "type", "inject", "key_down", "key_up"):
            self.assertFalse(hasattr(self.keyboard, operation))

    def test_logging_and_event_failures_do_not_change_state_results(self) -> None:
        mouse = MouseInterface(
            self.provider,
            logger=_FailingLogger(),
            event_bus=_FailingEventBus(),
        )
        keyboard = KeyboardInterface(
            self.provider,
            logger=_FailingLogger(),
            event_bus=_FailingEventBus(),
        )

        self.assertEqual(mouse.get_position(), self.provider.position_result)
        self.assertEqual(keyboard.get_state(), self.provider.keyboard_result)


if __name__ == "__main__":
    unittest.main()
