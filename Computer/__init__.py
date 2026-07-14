"""Computer package for NARVIS.

This package provides desktop-oriented services for applications, windows,
clipboard access, keyboard and mouse control, and screenshot capture. Runtime
adapters are also exposed so the existing Automation and Vision abstractions
can consume these services through the shared dependency injection container.
"""

from .application_manager import ApplicationManager
from .application_resolver import ApplicationResolver
from .clipboard_manager import ClipboardManager
from .control import (
    DesktopControlResult,
    DesktopControlService,
    build_desktop_control_service,
    register_computer_services,
)
from .keyboard_controller import KeyboardController
from .mouse_controller import MouseController, MousePosition
from .runtime import (
    ClipboardAutomationAdapter,
    ComputerServices,
    KeyboardAutomationAdapter,
    MouseAutomationAdapter,
    ScreenshotVisionAdapter,
)
from .services import (
    ApplicationDiscoveryProvider,
    ApplicationService,
    ClipboardProvider,
    ClipboardService,
    FileSystemProvider,
    FileSystemService,
    InstalledApplicationProvider,
    ProcessProvider,
    ProcessService,
    RunningApplicationProvider,
)
from .screenshot_manager import ScreenshotManager
from .universal_open import (
    DriveAndShellOpenProvider,
    InstalledApplicationOpenProvider,
    KnownFolderOpenProvider,
    UniversalOpenLauncher,
    UniversalOpenResolution,
    UniversalOpenResolver,
    UniversalOpenTarget,
    WebsiteOpenProvider,
    WindowsSettingsOpenProvider,
    WindowsSystemToolProvider,
)
from .window_manager import WindowInfo, WindowManager

__all__ = [
    "ApplicationDiscoveryProvider",
    "ApplicationManager",
    "ApplicationResolver",
    "ApplicationService",
    "ClipboardAutomationAdapter",
    "ClipboardManager",
    "ClipboardProvider",
    "ClipboardService",
    "ComputerServices",
    "DesktopControlResult",
    "DesktopControlService",
    "DriveAndShellOpenProvider",
    "FileSystemProvider",
    "FileSystemService",
    "InstalledApplicationOpenProvider",
    "InstalledApplicationProvider",
    "KeyboardAutomationAdapter",
    "KeyboardController",
    "KnownFolderOpenProvider",
    "MouseAutomationAdapter",
    "MouseController",
    "MousePosition",
    "ProcessProvider",
    "ProcessService",
    "RunningApplicationProvider",
    "ScreenshotManager",
    "ScreenshotVisionAdapter",
    "UniversalOpenLauncher",
    "UniversalOpenResolution",
    "UniversalOpenResolver",
    "UniversalOpenTarget",
    "WebsiteOpenProvider",
    "WindowsSettingsOpenProvider",
    "WindowsSystemToolProvider",
    "WindowInfo",
    "WindowManager",
    "build_desktop_control_service",
    "register_computer_services",
]
