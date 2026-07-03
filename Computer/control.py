"""Desktop-control orchestration services for the NARVIS Computer package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .runtime import ComputerServices


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Computer."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


@dataclass(slots=True, frozen=True)
class DesktopControlResult:
    """Represents the outcome of one desktop-control action."""

    action: str
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class DesktopControlService:
    """Provide one runtime-friendly facade over desktop capabilities."""

    def __init__(self, services: ComputerServices, logger: Any | None = None) -> None:
        self.services = services
        self.logger = logger

    def capture_screenshot(self, filename: str | None = None) -> DesktopControlResult:
        """Capture a screenshot using the configured screenshot manager."""

        try:
            path = self.services.screenshot_manager.take_screenshot(filename=filename)
            if path is None:
                return DesktopControlResult(
                    action="capture_screenshot",
                    success=False,
                    message="Screenshot capture backend is unavailable.",
                )
            return DesktopControlResult(
                action="capture_screenshot",
                success=True,
                message=f"Screenshot saved to {path}",
                data={"path": str(path)},
            )
        except Exception as error:
            return self._failure("capture_screenshot", error)

    def read_clipboard(self) -> DesktopControlResult:
        """Read the current clipboard text."""

        try:
            text = self.services.clipboard_manager.paste()
            return DesktopControlResult(
                action="read_clipboard",
                success=True,
                message="Clipboard read successfully.",
                data={"text": text},
            )
        except Exception as error:
            return self._failure("read_clipboard", error)

    def write_clipboard(self, text: str) -> DesktopControlResult:
        """Write text to the clipboard."""

        try:
            self.services.clipboard_manager.copy(text)
            return DesktopControlResult(
                action="write_clipboard",
                success=True,
                message="Clipboard updated successfully.",
                data={"text": text},
            )
        except Exception as error:
            return self._failure("write_clipboard", error)

    def type_text(self, text: str) -> DesktopControlResult:
        """Type text with the configured keyboard controller."""

        try:
            self.services.keyboard_controller.type(text)
            return DesktopControlResult(
                action="type_text",
                success=True,
                message="Typed text successfully.",
                data={"text": text},
            )
        except Exception as error:
            return self._failure("type_text", error)

    def press_key(self, key: str) -> DesktopControlResult:
        """Press one key with the configured keyboard controller."""

        try:
            self.services.keyboard_controller.press(key)
            return DesktopControlResult(
                action="press_key",
                success=True,
                message=f"Pressed key '{key}'.",
                data={"key": key},
            )
        except Exception as error:
            return self._failure("press_key", error)

    def move_mouse(self, x: int, y: int) -> DesktopControlResult:
        """Move the mouse pointer to the supplied coordinates."""

        try:
            self.services.mouse_controller.move(x, y)
            return DesktopControlResult(
                action="move_mouse",
                success=True,
                message=f"Moved mouse to ({x}, {y}).",
                data={"x": x, "y": y},
            )
        except Exception as error:
            return self._failure("move_mouse", error)

    def click_mouse(self, button: str = "left") -> DesktopControlResult:
        """Click a mouse button at the current pointer position."""

        try:
            self.services.mouse_controller.click(button=button)
            return DesktopControlResult(
                action="click_mouse",
                success=True,
                message=f"Clicked the {button} mouse button.",
                data={"button": button},
            )
        except Exception as error:
            return self._failure("click_mouse", error)

    def open_application(self, app_name: str) -> DesktopControlResult:
        """Launch an application by name."""

        try:
            success = self.services.application_manager.open_app_by_name(app_name)
            if success:
                return DesktopControlResult(
                    action="open_application",
                    success=True,
                    message=f"Opened application '{app_name}'.",
                    data={"application": app_name},
                )
            return DesktopControlResult(
                action="open_application",
                success=False,
                message=f"Unable to open application '{app_name}'.",
                data={"application": app_name},
            )
        except Exception as error:
            return self._failure("open_application", error)

    def close_application(self, app_name: str) -> DesktopControlResult:
        """Close an application by name."""

        try:
            success = self.services.application_manager.close_application(app_name)
            if success:
                return DesktopControlResult(
                    action="close_application",
                    success=True,
                    message=f"Closed application '{app_name}'.",
                    data={"application": app_name},
                )
            return DesktopControlResult(
                action="close_application",
                success=False,
                message=f"Application '{app_name}' is not running or cannot be closed.",
                data={"application": app_name},
            )
        except Exception as error:
            return self._failure("close_application", error)

    def list_windows(self) -> DesktopControlResult:
        """Return basic window information for open windows."""

        try:
            windows = self.services.window_manager.get_all_windows()
            payload = [
                {
                    "title": window.title,
                    "x": window.x,
                    "y": window.y,
                    "width": window.width,
                    "height": window.height,
                    "is_active": window.is_active,
                }
                for window in windows
            ]
            return DesktopControlResult(
                action="list_windows",
                success=True,
                message=f"Found {len(payload)} window(s).",
                data={"windows": payload},
            )
        except Exception as error:
            return self._failure("list_windows", error)

    def focus_window(self, title: str) -> DesktopControlResult:
        """Focus a window by its title."""

        try:
            success = self.services.window_manager.focus_window(title)
            if success:
                return DesktopControlResult(
                    action="focus_window",
                    success=True,
                    message=f"Focused window '{title}'.",
                    data={"title": title},
                )
            return DesktopControlResult(
                action="focus_window",
                success=False,
                message=f"Window '{title}' was not found.",
                data={"title": title},
            )
        except Exception as error:
            return self._failure("focus_window", error)

    def runtime_status(self) -> dict[str, Any]:
        """Return a lightweight runtime status payload for desktop services."""

        windows_result = self.list_windows()
        processes = self.services.application_manager.get_running_processes()
        return {
            "windows": len(windows_result.data.get("windows", [])) if windows_result.success else 0,
            "running_processes": len(processes),
            "window_backend_available": bool(windows_result.success),
            "clipboard_available": True,
        }

    def _failure(self, action: str, error: Exception) -> DesktopControlResult:
        """Build a standardized failure result and log it."""

        _emit_log(self.logger, "warning", "Desktop action failed", action=action, error=str(error))
        return DesktopControlResult(action=action, success=False, message=str(error))


def build_desktop_control_service(
    services: ComputerServices,
    *,
    logger: Any | None = None,
) -> DesktopControlService:
    """Build the desktop-control facade for a concrete computer service bundle."""

    _emit_log(logger, "info", "Built desktop control service")
    return DesktopControlService(services=services, logger=logger)


def register_computer_services(
    container: DependencyRegistrar,
    *,
    services: ComputerServices,
    desktop_control: DesktopControlService,
    logger: Any | None = None,
) -> ComputerServices:
    """Register concrete computer services and desktop control in the container."""

    container.register_instance("computer_services", services)
    container.register_instance("desktop_control", desktop_control)
    container.register_instance("desktop_control_service", desktop_control)
    application_resolver = getattr(services.application_manager, "resolver", None)
    if application_resolver is not None:
        container.register_instance("application_resolver", application_resolver)
        container.register_instance("computer_application_resolver", application_resolver)
    universal_open_resolver = getattr(services.application_manager, "universal_open_resolver", None)
    if universal_open_resolver is not None:
        container.register_instance("universal_open_resolver", universal_open_resolver)
        container.register_instance("computer_universal_open_resolver", universal_open_resolver)
    universal_open_launcher = getattr(services.application_manager, "universal_open_launcher", None)
    if universal_open_launcher is not None:
        container.register_instance("universal_open_launcher", universal_open_launcher)
        container.register_instance("computer_universal_open_launcher", universal_open_launcher)
    container.register_instance("application_manager", services.application_manager)
    container.register_instance("window_manager", services.window_manager)
    container.register_instance("screenshot_manager", services.screenshot_manager)
    container.register_instance("computer_application_manager", services.application_manager)
    container.register_instance("computer_clipboard_manager", services.clipboard_manager)
    container.register_instance("computer_keyboard_controller", services.keyboard_controller)
    container.register_instance("computer_mouse_controller", services.mouse_controller)
    container.register_instance("computer_screenshot_manager", services.screenshot_manager)
    container.register_instance("computer_window_manager", services.window_manager)
    _emit_log(logger, "info", "Registered computer services in container")
    return services


__all__ = [
    "DesktopControlResult",
    "DesktopControlService",
    "build_desktop_control_service",
    "register_computer_services",
]
