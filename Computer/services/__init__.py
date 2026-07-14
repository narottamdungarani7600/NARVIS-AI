"""Safe read-only information services for the Computer integration layer."""

from .applications import (
    ApplicationDiscoveryProvider,
    ApplicationService,
    InstalledApplicationProvider,
    RunningApplicationProvider,
)
from .clipboard import ClipboardProvider, ClipboardService
from .filesystem import FileSystemProvider, FileSystemService
from .processes import ProcessProvider, ProcessService

__all__ = [
    "ApplicationDiscoveryProvider",
    "ApplicationService",
    "ClipboardProvider",
    "ClipboardService",
    "FileSystemProvider",
    "FileSystemService",
    "InstalledApplicationProvider",
    "ProcessProvider",
    "ProcessService",
    "RunningApplicationProvider",
]
