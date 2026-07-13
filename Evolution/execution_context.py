"""Standalone immutable execution-context snapshots for future Phase 10 work."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


def _normalized_text(value: Any) -> str:
    """Normalize one supplied identity field without reading from the host environment."""

    return " ".join(value.strip().split()) if isinstance(value, str) else ""


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    """Build one deterministic identifier from caller-supplied context data only."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return f"{prefix}-{sha256(encoded).hexdigest()[:16]}"


@dataclass(slots=True, frozen=True)
class ExecutionSession:
    """One deterministic future-execution session identity with no runtime connection."""

    session_id: str
    actor_id: str
    workspace_id: str
    desktop_id: str
    purpose: str


@dataclass(slots=True, frozen=True)
class DesktopContext:
    """One caller-supplied desktop fact set; no desktop inspection occurs here."""

    desktop_id: str
    platform_name: str
    is_available: bool


@dataclass(slots=True, frozen=True)
class WindowContext:
    """One caller-supplied active-window description with immutable geometry facts."""

    window_id: str
    application_id: str
    title: str
    is_focused: bool
    left: int
    top: int
    width: int
    height: int


@dataclass(slots=True, frozen=True)
class ApplicationContext:
    """One caller-supplied application description with no application control behavior."""

    application_id: str
    name: str
    version: str
    is_running: bool


@dataclass(slots=True, frozen=True)
class DisplayContext:
    """One caller-supplied display description used only for snapshot validation."""

    display_id: str
    desktop_id: str
    width: int
    height: int
    scale_percent: int = 100


@dataclass(slots=True, frozen=True)
class MouseContext:
    """One caller-supplied mouse position with no mouse-control capability."""

    display_id: str
    x: int
    y: int
    buttons_down: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class KeyboardContext:
    """One caller-supplied keyboard state with no keyboard-control capability."""

    layout: str
    pressed_keys: tuple[str, ...] = ()
    is_available: bool = True


@dataclass(slots=True, frozen=True)
class WorkspaceContext:
    """One workspace reference treated as opaque data, never resolved or accessed."""

    workspace_id: str
    label: str
    root_reference: str
    is_available: bool


@dataclass(slots=True, frozen=True)
class ExecutionContextSnapshot:
    """One immutable, caller-fed context snapshot with no executable behavior."""

    snapshot_id: str
    session: ExecutionSession
    desktop: DesktopContext
    window: WindowContext
    application: ApplicationContext
    display: DisplayContext
    mouse: MouseContext
    keyboard: KeyboardContext
    workspace: WorkspaceContext


@dataclass(slots=True, frozen=True)
class ExecutionContextBuildRequest:
    """One typed request to combine supplied context facts into an immutable snapshot."""

    session: ExecutionSession
    desktop: DesktopContext
    window: WindowContext
    application: ApplicationContext
    display: DisplayContext
    mouse: MouseContext
    keyboard: KeyboardContext
    workspace: WorkspaceContext


@dataclass(slots=True, frozen=True)
class ExecutionContextValidationResult:
    """One typed context validation result that never triggers host inspection or action."""

    valid: bool
    reason_code: str
    reason: str
    snapshot_id: str = ""
    snapshot: ExecutionContextSnapshot | None = None


@dataclass(slots=True, frozen=True)
class ExecutionContextBuildResult:
    """One typed snapshot-build outcome with no runtime side effects."""

    decision: str
    reason_code: str
    reason: str
    snapshot: ExecutionContextSnapshot | None = None

    @property
    def built(self) -> bool:
        """Return True only when an immutable typed snapshot was built."""

        return self.decision == "built" and self.snapshot is not None


class ExecutionContextService:
    """Build, validate, and enumerate in-memory immutable context snapshots only."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ExecutionContextSnapshot] = {}

    def create_session(
        self,
        *,
        actor_id: str,
        workspace_id: str,
        desktop_id: str,
        purpose: str,
    ) -> ExecutionSession:
        """Create one deterministic session identity from explicit caller-provided fields."""

        normalized_actor_id = _normalized_text(actor_id)
        normalized_workspace_id = _normalized_text(workspace_id)
        normalized_desktop_id = _normalized_text(desktop_id)
        normalized_purpose = _normalized_text(purpose)
        if not all((normalized_actor_id, normalized_workspace_id, normalized_desktop_id, normalized_purpose)):
            raise ValueError("Execution sessions require non-empty actor, workspace, desktop, and purpose fields.")
        session_payload = {
            "actor_id": normalized_actor_id,
            "workspace_id": normalized_workspace_id,
            "desktop_id": normalized_desktop_id,
            "purpose": normalized_purpose,
        }
        return ExecutionSession(
            session_id=_stable_id("execution_session", session_payload),
            **session_payload,
        )

    def build_snapshot(self, request: ExecutionContextBuildRequest) -> ExecutionContextBuildResult:
        """Validate supplied facts and retain one immutable snapshot without host interaction."""

        if not isinstance(request, ExecutionContextBuildRequest):
            return self._reject("invalid_context_build_request", "Context snapshots require one typed ExecutionContextBuildRequest.")
        validation = self._validate_components(
            session=request.session,
            desktop=request.desktop,
            window=request.window,
            application=request.application,
            display=request.display,
            mouse=request.mouse,
            keyboard=request.keyboard,
            workspace=request.workspace,
        )
        if validation is not None:
            reason_code, reason = validation
            return self._reject(reason_code, reason)

        snapshot_id = self._snapshot_id(request)
        snapshot = ExecutionContextSnapshot(
            snapshot_id=snapshot_id,
            session=request.session,
            desktop=request.desktop,
            window=request.window,
            application=request.application,
            display=request.display,
            mouse=request.mouse,
            keyboard=request.keyboard,
            workspace=request.workspace,
        )
        existing = self._snapshots.get(snapshot_id)
        if existing is not None:
            return ExecutionContextBuildResult(
                decision="built",
                reason_code="snapshot_already_known",
                reason="The supplied immutable context facts map to an existing deterministic snapshot.",
                snapshot=existing,
            )
        self._snapshots[snapshot_id] = snapshot
        return ExecutionContextBuildResult(
            decision="built",
            reason_code="snapshot_built",
            reason="The supplied context facts were captured as an immutable in-memory snapshot.",
            snapshot=snapshot,
        )

    def validate_snapshot(self, snapshot: ExecutionContextSnapshot) -> ExecutionContextValidationResult:
        """Validate one immutable snapshot against its typed fields and deterministic identifier."""

        if not isinstance(snapshot, ExecutionContextSnapshot):
            return ExecutionContextValidationResult(
                valid=False,
                reason_code="invalid_context_snapshot",
                reason="Snapshot validation requires one typed ExecutionContextSnapshot.",
            )
        validation = self._validate_components(
            session=snapshot.session,
            desktop=snapshot.desktop,
            window=snapshot.window,
            application=snapshot.application,
            display=snapshot.display,
            mouse=snapshot.mouse,
            keyboard=snapshot.keyboard,
            workspace=snapshot.workspace,
        )
        if validation is not None:
            reason_code, reason = validation
            return ExecutionContextValidationResult(
                valid=False,
                reason_code=reason_code,
                reason=reason,
                snapshot_id=snapshot.snapshot_id,
            )
        expected_snapshot_id = self._snapshot_id(
            ExecutionContextBuildRequest(
                session=snapshot.session,
                desktop=snapshot.desktop,
                window=snapshot.window,
                application=snapshot.application,
                display=snapshot.display,
                mouse=snapshot.mouse,
                keyboard=snapshot.keyboard,
                workspace=snapshot.workspace,
            )
        )
        if snapshot.snapshot_id != expected_snapshot_id:
            return ExecutionContextValidationResult(
                valid=False,
                reason_code="snapshot_identifier_mismatch",
                reason="The snapshot identifier does not match the immutable typed context facts.",
                snapshot_id=snapshot.snapshot_id,
            )
        return ExecutionContextValidationResult(
            valid=True,
            reason_code="context_snapshot_valid",
            reason="The immutable context snapshot is internally consistent and contains no execution capability.",
            snapshot_id=snapshot.snapshot_id,
            snapshot=snapshot,
        )

    def get_snapshot(self, snapshot_id: str) -> ExecutionContextSnapshot | None:
        """Return one retained snapshot by opaque identifier without observing the host."""

        return self._snapshots.get(_normalized_text(snapshot_id))

    def list_snapshots(self) -> tuple[ExecutionContextSnapshot, ...]:
        """Return retained snapshots in deterministic immutable order."""

        return tuple(sorted(self._snapshots.values(), key=lambda snapshot: snapshot.snapshot_id))

    def _validate_components(
        self,
        *,
        session: Any,
        desktop: Any,
        window: Any,
        application: Any,
        display: Any,
        mouse: Any,
        keyboard: Any,
        workspace: Any,
    ) -> tuple[str, str] | None:
        """Validate supplied context relationships without querying external state."""

        if not all(
            (
                isinstance(session, ExecutionSession),
                isinstance(desktop, DesktopContext),
                isinstance(window, WindowContext),
                isinstance(application, ApplicationContext),
                isinstance(display, DisplayContext),
                isinstance(mouse, MouseContext),
                isinstance(keyboard, KeyboardContext),
                isinstance(workspace, WorkspaceContext),
            )
        ):
            return ("invalid_context_component", "Context snapshots require all typed immutable context components.")
        if not all(
            (
                _normalized_text(session.session_id),
                _normalized_text(session.actor_id),
                _normalized_text(session.workspace_id),
                _normalized_text(session.desktop_id),
                _normalized_text(session.purpose),
                _normalized_text(desktop.desktop_id),
                _normalized_text(desktop.platform_name),
                _normalized_text(window.window_id),
                _normalized_text(window.application_id),
                _normalized_text(window.title),
                _normalized_text(application.application_id),
                _normalized_text(application.name),
                _normalized_text(display.display_id),
                _normalized_text(display.desktop_id),
                _normalized_text(mouse.display_id),
                _normalized_text(keyboard.layout),
                _normalized_text(workspace.workspace_id),
                _normalized_text(workspace.label),
                _normalized_text(workspace.root_reference),
            )
        ):
            return ("context_identity_required", "Context snapshot fields require complete non-empty supplied identities.")
        expected_session_id = _stable_id(
            "execution_session",
            {
                "actor_id": session.actor_id,
                "workspace_id": session.workspace_id,
                "desktop_id": session.desktop_id,
                "purpose": session.purpose,
            },
        )
        if session.session_id != expected_session_id:
            return ("session_identifier_mismatch", "The execution session identifier does not match its deterministic identity fields.")
        if session.desktop_id != desktop.desktop_id or display.desktop_id != desktop.desktop_id:
            return ("desktop_binding_mismatch", "Session and display context must bind to the same supplied desktop identifier.")
        if session.workspace_id != workspace.workspace_id:
            return ("workspace_binding_mismatch", "Session and workspace context must bind to the same supplied workspace identifier.")
        if window.application_id != application.application_id:
            return ("application_binding_mismatch", "Window context must bind to the supplied application identifier.")
        if mouse.display_id != display.display_id:
            return ("display_binding_mismatch", "Mouse context must bind to the supplied display identifier.")
        if not all(isinstance(value, bool) for value in (desktop.is_available, window.is_focused, application.is_running, keyboard.is_available, workspace.is_available)):
            return ("invalid_context_state", "Context availability and focus fields must be typed booleans.")
        if not all(isinstance(value, int) for value in (window.left, window.top, window.width, window.height, display.width, display.height, display.scale_percent, mouse.x, mouse.y)):
            return ("invalid_context_geometry", "Context geometry fields must be typed integers.")
        if window.width <= 0 or window.height <= 0 or display.width <= 0 or display.height <= 0 or not 25 <= display.scale_percent <= 500:
            return ("invalid_context_geometry", "Window and display dimensions must be positive with a bounded display scale.")
        if mouse.x < 0 or mouse.y < 0 or mouse.x >= display.width or mouse.y >= display.height:
            return ("mouse_position_out_of_bounds", "Mouse coordinates must remain inside the supplied display bounds.")
        if not isinstance(mouse.buttons_down, tuple) or not all(_normalized_text(button) for button in mouse.buttons_down):
            return ("invalid_mouse_context", "Mouse button state must be a typed tuple of non-empty labels.")
        if not isinstance(keyboard.pressed_keys, tuple) or not all(_normalized_text(key) for key in keyboard.pressed_keys):
            return ("invalid_keyboard_context", "Keyboard state must be a typed tuple of non-empty key labels.")
        return None

    def _snapshot_id(self, request: ExecutionContextBuildRequest) -> str:
        """Return the deterministic identifier for one fully typed caller-provided snapshot request."""

        return _stable_id(
            "execution_context_snapshot",
            {
                "session": {
                    "session_id": request.session.session_id,
                    "actor_id": request.session.actor_id,
                    "workspace_id": request.session.workspace_id,
                    "desktop_id": request.session.desktop_id,
                    "purpose": request.session.purpose,
                },
                "desktop": {
                    "desktop_id": request.desktop.desktop_id,
                    "platform_name": request.desktop.platform_name,
                    "is_available": request.desktop.is_available,
                },
                "window": {
                    "window_id": request.window.window_id,
                    "application_id": request.window.application_id,
                    "title": request.window.title,
                    "is_focused": request.window.is_focused,
                    "left": request.window.left,
                    "top": request.window.top,
                    "width": request.window.width,
                    "height": request.window.height,
                },
                "application": {
                    "application_id": request.application.application_id,
                    "name": request.application.name,
                    "version": request.application.version,
                    "is_running": request.application.is_running,
                },
                "display": {
                    "display_id": request.display.display_id,
                    "desktop_id": request.display.desktop_id,
                    "width": request.display.width,
                    "height": request.display.height,
                    "scale_percent": request.display.scale_percent,
                },
                "mouse": {
                    "display_id": request.mouse.display_id,
                    "x": request.mouse.x,
                    "y": request.mouse.y,
                    "buttons_down": request.mouse.buttons_down,
                },
                "keyboard": {
                    "layout": request.keyboard.layout,
                    "pressed_keys": request.keyboard.pressed_keys,
                    "is_available": request.keyboard.is_available,
                },
                "workspace": {
                    "workspace_id": request.workspace.workspace_id,
                    "label": request.workspace.label,
                    "root_reference": request.workspace.root_reference,
                    "is_available": request.workspace.is_available,
                },
            },
        )

    def _reject(self, reason_code: str, reason: str) -> ExecutionContextBuildResult:
        """Build one typed rejected build result without any host interaction."""

        return ExecutionContextBuildResult(
            decision="rejected",
            reason_code=reason_code,
            reason=reason,
        )


__all__ = [
    "ApplicationContext",
    "DesktopContext",
    "DisplayContext",
    "ExecutionContextBuildRequest",
    "ExecutionContextBuildResult",
    "ExecutionContextService",
    "ExecutionContextSnapshot",
    "ExecutionContextValidationResult",
    "ExecutionSession",
    "KeyboardContext",
    "MouseContext",
    "WindowContext",
    "WorkspaceContext",
]
