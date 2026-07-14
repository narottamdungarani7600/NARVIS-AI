"""Strongly typed, immutable models for desktop state inspection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


def _require_text(value: object, field_name: str) -> str:
    """Validate stable identifiers and names without normalizing input."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


def _validate_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")


def _validate_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")


def _optional_text(value: object, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _immutable_mapping(
    value: Mapping[str, Any],
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


class WindowState(str, Enum):
    """Observable window presentation states."""

    UNKNOWN = "unknown"
    NORMAL = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    FULLSCREEN = "fullscreen"
    HIDDEN = "hidden"


class MouseButton(str, Enum):
    """Mouse buttons that a provider may report as pressed."""

    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"
    X1 = "x1"
    X2 = "x2"


class ModifierKey(str, Enum):
    """Keyboard modifier keys represented by :class:`ModifierKeys`."""

    SHIFT = "shift"
    CONTROL = "control"
    ALT = "alt"
    META = "meta"


class Key(str, Enum):
    """Portable keys that may appear in an observed keyboard snapshot."""

    A = "a"
    B = "b"
    C = "c"
    D = "d"
    E = "e"
    F = "f"
    G = "g"
    H = "h"
    I = "i"
    J = "j"
    K = "k"
    L = "l"
    M = "m"
    N = "n"
    O = "o"
    P = "p"
    Q = "q"
    R = "r"
    S = "s"
    T = "t"
    U = "u"
    V = "v"
    W = "w"
    X = "x"
    Y = "y"
    Z = "z"
    NUMBER_0 = "0"
    NUMBER_1 = "1"
    NUMBER_2 = "2"
    NUMBER_3 = "3"
    NUMBER_4 = "4"
    NUMBER_5 = "5"
    NUMBER_6 = "6"
    NUMBER_7 = "7"
    NUMBER_8 = "8"
    NUMBER_9 = "9"
    ENTER = "enter"
    ESCAPE = "escape"
    SPACE = "space"
    TAB = "tab"
    BACKSPACE = "backspace"
    DELETE = "delete"
    INSERT = "insert"
    HOME = "home"
    END = "end"
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"
    ARROW_UP = "arrow_up"
    ARROW_DOWN = "arrow_down"
    ARROW_LEFT = "arrow_left"
    ARROW_RIGHT = "arrow_right"
    CAPS_LOCK = "caps_lock"
    NUM_LOCK = "num_lock"
    SCROLL_LOCK = "scroll_lock"
    SHIFT = "shift"
    CONTROL = "control"
    ALT = "alt"
    META = "meta"
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"
    F5 = "f5"
    F6 = "f6"
    F7 = "f7"
    F8 = "f8"
    F9 = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"


# A descriptive alias for consumers that prefer an explicit model name.
KeyboardKey = Key


@dataclass(slots=True, frozen=True)
class DisplayInfo:
    """Metadata for a physical or virtual display."""

    display_id: str
    name: str
    width: int
    height: int
    x: int = 0
    y: int = 0
    is_primary: bool = False
    is_virtual: bool = False
    scale_factor: float = 1.0
    refresh_rate_hz: float | None = None
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_text(self.display_id, "display id")
        _require_text(self.name, "display name")
        _validate_int(self.width, "display width")
        _validate_int(self.height, "display height")
        _validate_int(self.x, "display x")
        _validate_int(self.y, "display y")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("display width and height must be positive")
        _validate_bool(self.is_primary, "display is_primary")
        _validate_bool(self.is_virtual, "display is_virtual")
        if (
            not isinstance(self.scale_factor, (int, float))
            or isinstance(self.scale_factor, bool)
            or self.scale_factor <= 0
        ):
            raise ValueError("display scale_factor must be a positive number")
        if self.refresh_rate_hz is not None and (
            not isinstance(self.refresh_rate_hz, (int, float))
            or isinstance(self.refresh_rate_hz, bool)
            or self.refresh_rate_hz <= 0
        ):
            raise ValueError(
                "display refresh_rate_hz must be a positive number or None"
            )
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "display attributes"),
        )

    @property
    def id(self) -> str:
        """Return the stable provider display identifier."""

        return self.display_id

    @property
    def resolution(self) -> tuple[int, int]:
        """Return the display resolution as ``(width, height)``."""

        return (self.width, self.height)

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """Return virtual-desktop bounds as ``(x, y, width, height)``."""

        return (self.x, self.y, self.width, self.height)


@dataclass(slots=True, frozen=True)
class WindowInfo:
    """Metadata-only snapshot of one desktop window."""

    window_id: str
    title: str
    state: WindowState = WindowState.UNKNOWN
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    process_id: int | None = None
    application_name: str | None = None
    display_id: str | None = None
    is_visible: bool = True
    is_active: bool = False
    attributes: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        _require_text(self.window_id, "window id")
        if not isinstance(self.title, str):
            raise TypeError("window title must be a string")
        if not isinstance(self.state, WindowState):
            raise TypeError("window state must be a WindowState")
        for value, name in (
            (self.x, "window x"),
            (self.y, "window y"),
            (self.width, "window width"),
            (self.height, "window height"),
        ):
            _validate_int(value, name)
        if self.width < 0 or self.height < 0:
            raise ValueError("window width and height must be non-negative")
        if self.process_id is not None and (
            not isinstance(self.process_id, int)
            or isinstance(self.process_id, bool)
            or self.process_id < 0
        ):
            raise ValueError(
                "window process_id must be a non-negative integer or None"
            )
        if self.application_name is not None and not isinstance(
            self.application_name, str
        ):
            raise TypeError("window application_name must be a string or None")
        _optional_text(self.display_id, "window display_id")
        _validate_bool(self.is_visible, "window is_visible")
        _validate_bool(self.is_active, "window is_active")
        object.__setattr__(
            self,
            "attributes",
            _immutable_mapping(self.attributes, "window attributes"),
        )

    @property
    def id(self) -> str:
        """Return the stable provider window identifier."""

        return self.window_id

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """Return window bounds as ``(x, y, width, height)``."""

        return (self.x, self.y, self.width, self.height)

    @property
    def is_minimized(self) -> bool:
        return self.state is WindowState.MINIMIZED

    @property
    def is_maximized(self) -> bool:
        return self.state is WindowState.MAXIMIZED

    @property
    def is_fullscreen(self) -> bool:
        return self.state is WindowState.FULLSCREEN


@dataclass(slots=True, frozen=True)
class MousePosition:
    """Pointer coordinates in the provider's virtual desktop space."""

    x: int
    y: int
    display_id: str | None = None

    def __post_init__(self) -> None:
        _validate_int(self.x, "mouse x")
        _validate_int(self.y, "mouse y")
        _optional_text(self.display_id, "mouse display_id")

    @property
    def coordinates(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass(slots=True, frozen=True)
class MouseButtons:
    """Pressed-state snapshot for portable mouse buttons."""

    left: bool = False
    middle: bool = False
    right: bool = False
    x1: bool = False
    x2: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.left, "mouse left"),
            (self.middle, "mouse middle"),
            (self.right, "mouse right"),
            (self.x1, "mouse x1"),
            (self.x2, "mouse x2"),
        ):
            _validate_bool(value, name)

    @property
    def pressed(self) -> frozenset[MouseButton]:
        """Return the set of currently pressed buttons."""

        states = (
            (MouseButton.LEFT, self.left),
            (MouseButton.MIDDLE, self.middle),
            (MouseButton.RIGHT, self.right),
            (MouseButton.X1, self.x1),
            (MouseButton.X2, self.x2),
        )
        return frozenset(button for button, is_pressed in states if is_pressed)

    def is_pressed(self, button: MouseButton) -> bool:
        """Return whether one strongly typed button is pressed."""

        if not isinstance(button, MouseButton):
            raise TypeError("button must be a MouseButton")
        return button in self.pressed


@dataclass(slots=True, frozen=True)
class PointerState:
    """Combined pointer position and button snapshot."""

    position: MousePosition
    buttons: MouseButtons = field(default_factory=MouseButtons)

    def __post_init__(self) -> None:
        if not isinstance(self.position, MousePosition):
            raise TypeError("pointer position must be MousePosition")
        if not isinstance(self.buttons, MouseButtons):
            raise TypeError("pointer buttons must be MouseButtons")


@dataclass(slots=True, frozen=True)
class ModifierKeys:
    """Pressed-state snapshot for keyboard modifier keys."""

    shift: bool = False
    control: bool = False
    alt: bool = False
    meta: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.shift, "modifier shift"),
            (self.control, "modifier control"),
            (self.alt, "modifier alt"),
            (self.meta, "modifier meta"),
        ):
            _validate_bool(value, name)

    @property
    def ctrl(self) -> bool:
        """Return the control-key state using its common short name."""

        return self.control

    @property
    def active(self) -> frozenset[ModifierKey]:
        """Return the set of active modifiers."""

        states = (
            (ModifierKey.SHIFT, self.shift),
            (ModifierKey.CONTROL, self.control),
            (ModifierKey.ALT, self.alt),
            (ModifierKey.META, self.meta),
        )
        return frozenset(modifier for modifier, is_active in states if is_active)

    def is_active(self, modifier: ModifierKey) -> bool:
        if not isinstance(modifier, ModifierKey):
            raise TypeError("modifier must be a ModifierKey")
        return modifier in self.active


def _immutable_keys(value: Iterable[Key]) -> frozenset[Key]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError("keyboard pressed_keys must be an iterable of Key values")
    keys = frozenset(value)
    if not all(isinstance(key, Key) for key in keys):
        raise TypeError("keyboard pressed_keys must contain only Key values")
    return keys


@dataclass(slots=True, frozen=True)
class KeyboardState:
    """Observed keyboard state without any key-injection capability."""

    pressed_keys: frozenset[Key] = field(default_factory=frozenset)
    modifiers: ModifierKeys = field(default_factory=ModifierKeys)
    is_available: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "pressed_keys", _immutable_keys(self.pressed_keys))
        if not isinstance(self.modifiers, ModifierKeys):
            raise TypeError("keyboard modifiers must be ModifierKeys")
        _validate_bool(self.is_available, "keyboard is_available")
        if not self.is_available and (self.pressed_keys or self.modifiers.active):
            raise ValueError("an unavailable keyboard cannot report pressed keys")

    def is_pressed(self, key: Key) -> bool:
        """Return whether one strongly typed key is pressed."""

        if not isinstance(key, Key):
            raise TypeError("key must be a Key")
        return key in self.pressed_keys


__all__ = [
    "DisplayInfo",
    "Key",
    "KeyboardKey",
    "KeyboardState",
    "ModifierKey",
    "ModifierKeys",
    "MouseButton",
    "MouseButtons",
    "MousePosition",
    "PointerState",
    "WindowInfo",
    "WindowState",
]
