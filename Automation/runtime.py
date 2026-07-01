"""Runtime automation services and safe local implementations for NARVIS.

This module keeps the Automation package decoupled from any specific runtime by
providing constructor-injected services, workspace-safe file operations, and a
single dispatcher that higher-level modules can consume through the DI
container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from .automation import AutomationAction
from .clipboard import BaseClipboardManager, NullClipboardManager
from .files import BaseFileManager
from .folders import BaseFolderManager
from .keyboard import BaseKeyboardController, NullKeyboardController
from .mouse import BaseMouseController, MousePosition, NullMouseController
from .scheduler import BaseScheduler, ScheduledTask
from .tasks import InMemoryTaskQueue, TaskQueue
from .workflow import SequentialWorkflow, Workflow


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


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
    """Protocol for dependency-injection containers used by Automation."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class WorkspacePathPolicy:
    """Resolve file-system paths while keeping automation inside one workspace."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def resolve(self, path: str | Path) -> Path:
        """Return an absolute path and ensure it stays within the workspace root."""

        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as error:
            raise ValueError(f"Path '{resolved}' is outside the workspace root '{self.workspace_root}'") from error
        return resolved


class WorkspaceFileManager(BaseFileManager):
    """Perform text-file operations limited to the configured workspace."""

    def __init__(self, workspace_root: str | Path, logger: Any | None = None) -> None:
        self.logger = logger
        self._paths = WorkspacePathPolicy(workspace_root)

    def read_text(self, path: str | Path) -> str:
        """Read UTF-8 text from a workspace file."""

        resolved_path = self._paths.resolve(path)
        if not resolved_path.exists():
            return ""
        return resolved_path.read_text(encoding="utf-8")

    def write_text(self, path: str | Path, content: str) -> None:
        """Write UTF-8 text to a workspace file, creating parents as needed."""

        resolved_path = self._paths.resolve(path)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
        _emit_log(self.logger, "debug", "Wrote workspace file", path=str(resolved_path))

    def exists(self, path: str | Path) -> bool:
        """Return whether a workspace file exists."""

        return self._paths.resolve(path).exists()


class WorkspaceFolderManager(BaseFolderManager):
    """Perform directory operations limited to the configured workspace."""

    def __init__(self, workspace_root: str | Path, logger: Any | None = None) -> None:
        self.logger = logger
        self._paths = WorkspacePathPolicy(workspace_root)

    def create(self, path: str | Path) -> Path:
        """Create and return a workspace directory."""

        resolved_path = self._paths.resolve(path)
        resolved_path.mkdir(parents=True, exist_ok=True)
        _emit_log(self.logger, "debug", "Created workspace directory", path=str(resolved_path))
        return resolved_path

    def exists(self, path: str | Path) -> bool:
        """Return whether a workspace directory exists."""

        return self._paths.resolve(path).exists()


class InMemoryScheduler(BaseScheduler):
    """Keep scheduled tasks in memory for inspection and future execution."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger
        self._lock = RLock()
        self._tasks: dict[str, ScheduledTask] = {}

    def schedule(self, task: ScheduledTask) -> None:
        """Store a scheduled task in memory."""

        with self._lock:
            self._tasks[task.name] = task
        _emit_log(self.logger, "info", "Scheduled automation task", task=task.name, run_at=task.run_at.isoformat())

    def cancel(self, name: str) -> None:
        """Cancel a scheduled task by name."""

        with self._lock:
            self._tasks.pop(name, None)
        _emit_log(self.logger, "info", "Cancelled automation task", task=name)

    def list_tasks(self) -> tuple[ScheduledTask, ...]:
        """Return the scheduled tasks sorted by execution time."""

        with self._lock:
            return tuple(sorted(self._tasks.values(), key=lambda item: (item.run_at, item.name)))


@dataclass(slots=True, frozen=True)
class AutomationResult:
    """Represents the outcome of one automation dispatch."""

    action_name: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    executed_at: datetime = field(default_factory=utc_now)


class AutomationService:
    """Dispatch automation actions through injected subsystem abstractions."""

    def __init__(
        self,
        *,
        clipboard_manager: BaseClipboardManager | None = None,
        keyboard_controller: BaseKeyboardController | None = None,
        mouse_controller: BaseMouseController | None = None,
        file_manager: BaseFileManager | None = None,
        folder_manager: BaseFolderManager | None = None,
        scheduler: BaseScheduler | None = None,
        task_queue: TaskQueue | None = None,
        workflow: Workflow | None = None,
        logger: Any | None = None,
    ) -> None:
        self.logger = logger
        self.clipboard_manager = clipboard_manager or NullClipboardManager()
        self.keyboard_controller = keyboard_controller or NullKeyboardController()
        self.mouse_controller = mouse_controller or NullMouseController()
        self.file_manager = file_manager
        self.folder_manager = folder_manager
        self.scheduler = scheduler
        self.task_queue = task_queue or InMemoryTaskQueue()
        self.workflow = workflow or SequentialWorkflow()
        self._history: list[AutomationResult] = []

    def execute(self, action: AutomationAction) -> AutomationResult:
        """Execute one automation action and return a structured result."""

        try:
            data = self._dispatch(action)
            result = AutomationResult(action_name=action.name, success=True, data=data)
            _emit_log(self.logger, "info", "Executed automation action", action=action.name)
        except Exception as error:
            result = AutomationResult(action_name=action.name, success=False, error=str(error))
            _emit_log(self.logger, "warning", "Automation action failed", action=action.name, error=str(error))
        self._history.append(result)
        return result

    def enqueue(self, action: AutomationAction) -> None:
        """Add an action to the queue."""

        self.task_queue.enqueue(action)
        _emit_log(self.logger, "debug", "Queued automation action", action=action.name)

    def drain_queue(self, limit: int | None = None) -> tuple[AutomationResult, ...]:
        """Execute queued actions in FIFO order."""

        results: list[AutomationResult] = []
        remaining = None if limit is None else max(limit, 0)
        while remaining is None or remaining > 0:
            action = self.task_queue.dequeue()
            if action is None:
                break
            results.append(self.execute(action))
            if remaining is not None:
                remaining -= 1
        return tuple(results)

    def run_workflow(self, actions: list[AutomationAction]) -> tuple[AutomationResult, ...]:
        """Run a workflow and execute each emitted action."""

        planned_actions = self.workflow.run(actions)
        return tuple(self.execute(action) for action in planned_actions)

    def schedule(self, task: ScheduledTask) -> None:
        """Schedule a task using the injected scheduler."""

        if self.scheduler is None:
            raise RuntimeError("No scheduler is configured")
        self.scheduler.schedule(task)

    def history(self, limit: int | None = None) -> tuple[AutomationResult, ...]:
        """Return recent automation results."""

        if limit is None:
            return tuple(self._history)
        return tuple(self._history[-max(limit, 0) :])

    def pending_action_count(self) -> int:
        """Return the number of queued actions that remain unprocessed."""

        queue = getattr(self.task_queue, "_queue", None)
        if queue is None:
            return 0
        return len(queue)

    def scheduled_task_count(self) -> int:
        """Return the number of stored scheduled tasks."""

        if not hasattr(self.scheduler, "list_tasks"):
            return 0
        return len(self.scheduler.list_tasks())

    def _dispatch(self, action: AutomationAction) -> dict[str, Any]:
        """Dispatch an action by name to the appropriate automation dependency."""

        payload = dict(action.payload)

        if action.name == "clipboard.read":
            return {"text": self.clipboard_manager.read()}
        if action.name == "clipboard.write":
            text = str(payload.get("text", ""))
            self.clipboard_manager.write(text)
            return {"text": text}
        if action.name == "keyboard.type":
            text = str(payload.get("text", ""))
            self.keyboard_controller.type_text(text)
            return {"text": text}
        if action.name == "keyboard.press":
            key = str(payload.get("key", ""))
            self.keyboard_controller.press_key(key)
            return {"key": key}
        if action.name == "mouse.move":
            position = MousePosition(x=int(payload.get("x", 0)), y=int(payload.get("y", 0)))
            self.mouse_controller.move(position)
            return {"x": position.x, "y": position.y}
        if action.name == "mouse.click":
            button = str(payload.get("button", "left"))
            self.mouse_controller.click(button=button)
            return {"button": button}
        if action.name == "file.read_text":
            if self.file_manager is None:
                raise RuntimeError("No file manager is configured")
            path = payload["path"]
            return {"path": str(path), "content": self.file_manager.read_text(path)}
        if action.name == "file.write_text":
            if self.file_manager is None:
                raise RuntimeError("No file manager is configured")
            path = payload["path"]
            content = str(payload.get("content", ""))
            self.file_manager.write_text(path, content)
            return {"path": str(path), "bytes_written": len(content.encode("utf-8"))}
        if action.name == "file.exists":
            if self.file_manager is None:
                raise RuntimeError("No file manager is configured")
            path = payload["path"]
            return {"path": str(path), "exists": self.file_manager.exists(path)}
        if action.name == "folder.create":
            if self.folder_manager is None:
                raise RuntimeError("No folder manager is configured")
            path = payload["path"]
            created = self.folder_manager.create(path)
            return {"path": str(created)}
        if action.name == "folder.exists":
            if self.folder_manager is None:
                raise RuntimeError("No folder manager is configured")
            path = payload["path"]
            return {"path": str(path), "exists": self.folder_manager.exists(path)}
        raise ValueError(f"Unsupported automation action: {action.name}")


@dataclass(slots=True)
class AutomationServices:
    """Container for runtime automation services and dependencies."""

    automation_service: AutomationService
    clipboard_manager: BaseClipboardManager
    keyboard_controller: BaseKeyboardController
    mouse_controller: BaseMouseController
    file_manager: BaseFileManager
    folder_manager: BaseFolderManager
    scheduler: BaseScheduler
    task_queue: TaskQueue
    workflow: Workflow


def build_automation_services(
    *,
    workspace_root: str | Path,
    clipboard_manager: BaseClipboardManager | None = None,
    keyboard_controller: BaseKeyboardController | None = None,
    mouse_controller: BaseMouseController | None = None,
    file_manager: BaseFileManager | None = None,
    folder_manager: BaseFolderManager | None = None,
    scheduler: BaseScheduler | None = None,
    task_queue: TaskQueue | None = None,
    workflow: Workflow | None = None,
    logger: Any | None = None,
) -> AutomationServices:
    """Build the runtime automation services using constructor injection."""

    resolved_file_manager = file_manager or WorkspaceFileManager(workspace_root=workspace_root, logger=logger)
    resolved_folder_manager = folder_manager or WorkspaceFolderManager(workspace_root=workspace_root, logger=logger)
    resolved_scheduler = scheduler or InMemoryScheduler(logger=logger)
    resolved_task_queue = task_queue or InMemoryTaskQueue()
    resolved_workflow = workflow or SequentialWorkflow()
    resolved_clipboard = clipboard_manager or NullClipboardManager()
    resolved_keyboard = keyboard_controller or NullKeyboardController()
    resolved_mouse = mouse_controller or NullMouseController()
    automation_service = AutomationService(
        clipboard_manager=resolved_clipboard,
        keyboard_controller=resolved_keyboard,
        mouse_controller=resolved_mouse,
        file_manager=resolved_file_manager,
        folder_manager=resolved_folder_manager,
        scheduler=resolved_scheduler,
        task_queue=resolved_task_queue,
        workflow=resolved_workflow,
        logger=logger,
    )
    _emit_log(logger, "info", "Built automation services", workspace_root=str(Path(workspace_root).resolve()))
    return AutomationServices(
        automation_service=automation_service,
        clipboard_manager=resolved_clipboard,
        keyboard_controller=resolved_keyboard,
        mouse_controller=resolved_mouse,
        file_manager=resolved_file_manager,
        folder_manager=resolved_folder_manager,
        scheduler=resolved_scheduler,
        task_queue=resolved_task_queue,
        workflow=resolved_workflow,
    )


def register_automation_services(
    container: DependencyRegistrar,
    services: AutomationServices,
    *,
    logger: Any | None = None,
) -> AutomationServices:
    """Register runtime automation services in the dependency container."""

    container.register_instance("automation_service", services.automation_service)
    container.register_instance("clipboard_manager", services.clipboard_manager)
    container.register_instance("keyboard_controller", services.keyboard_controller)
    container.register_instance("mouse_controller", services.mouse_controller)
    container.register_instance("file_manager", services.file_manager)
    container.register_instance("folder_manager", services.folder_manager)
    container.register_instance("scheduler", services.scheduler)
    container.register_instance("task_queue", services.task_queue)
    container.register_instance("workflow", services.workflow)
    _emit_log(logger, "info", "Registered automation services in container")
    return services


__all__ = [
    "AutomationResult",
    "AutomationService",
    "AutomationServices",
    "InMemoryScheduler",
    "WorkspaceFileManager",
    "WorkspaceFolderManager",
    "build_automation_services",
    "register_automation_services",
    "utc_now",
]
