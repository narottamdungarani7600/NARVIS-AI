"""Automation package for NARVIS.

This package provides reusable abstractions for mouse control, keyboard input,
clipboard operations, file and folder management, scheduled tasks, workflows,
and task queues without introducing platform-specific implementations.
"""

from .automation import AutomationAction, AutomationExecutor
from .clipboard import BaseClipboardManager, ClipboardManager, NullClipboardManager
from .files import BaseFileManager, FileManager, NullFileManager
from .folders import BaseFolderManager, FolderManager, NullFolderManager
from .keyboard import BaseKeyboardController, KeyboardController, NullKeyboardController
from .mouse import BaseMouseController, MouseController, MousePosition, NullMouseController
from .scheduler import BaseScheduler, NullScheduler, ScheduledTask, Scheduler
from .tasks import BaseTaskQueue, InMemoryTaskQueue, TaskQueue
from .workflow import BaseWorkflow, SequentialWorkflow, Workflow

__all__ = [
    "AutomationAction",
    "AutomationExecutor",
    "BaseClipboardManager",
    "BaseFileManager",
    "BaseFolderManager",
    "BaseKeyboardController",
    "BaseMouseController",
    "BaseScheduler",
    "BaseTaskQueue",
    "BaseWorkflow",
    "ClipboardManager",
    "FileManager",
    "FolderManager",
    "InMemoryTaskQueue",
    "KeyboardController",
    "MouseController",
    "MousePosition",
    "NullClipboardManager",
    "NullFileManager",
    "NullFolderManager",
    "NullKeyboardController",
    "NullMouseController",
    "NullScheduler",
    "ScheduledTask",
    "Scheduler",
    "SequentialWorkflow",
    "TaskQueue",
    "Workflow",
]
