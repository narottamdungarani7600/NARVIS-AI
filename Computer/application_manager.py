"""Application launching and process-management services for NARVIS."""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None

from .application_resolver import ApplicationResolver


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


class ApplicationManager:
    """Manages application launching and management."""

    def __init__(
        self,
        *,
        resolver: ApplicationResolver | None = None,
        logger: Any | None = None,
        os_type: str | None = None,
    ) -> None:
        """Initialize the application manager."""
        self.logger = logger or logging.getLogger(__name__)
        self.os_type = os_type or platform.system()
        self.resolver = resolver or ApplicationResolver(os_type=self.os_type, logger=self.logger)
        _emit_log(self.logger, "info", "Application manager initialized", os_type=self.os_type)

    def open_application(self, app_path: str, args: list[str] | None = None) -> bool:
        """
        Open application by path.
        
        Args:
            app_path: Path to application
            args: Command line arguments
            
        Returns:
            True if successful
        """
        try:
            if args is None:
                args = []

            subprocess.Popen([app_path] + args)

            _emit_log(self.logger, "info", "Opened application", path=app_path)
            return True
        except Exception as error:
            _emit_log(self.logger, "error", "Failed to open application", path=app_path, error=str(error))
            return False

    def open_app_by_name(self, app_name: str) -> bool:
        """
        Open application by name (Windows only).
        
        Args:
            app_name: Application name (e.g., "notepad", "chrome")
            
        Returns:
            True if successful
        """
        try:
            if self.os_type == "Windows":
                resolved = self.resolver.resolve(app_name)
                if resolved is None:
                    _emit_log(self.logger, "warning", "Unable to resolve application by name", app_name=app_name)
                    return False
                _emit_log(self.logger, "info", "Resolved application by name", app_name=app_name, path=resolved)
                return self.open_application(resolved)

            subprocess.Popen(["open", "-a", app_name])
            _emit_log(self.logger, "info", "Opened application by name", app_name=app_name)
            return True
        except Exception as error:
            _emit_log(self.logger, "error", "Failed to open application by name", app_name=app_name, error=str(error))
            return False

    def close_application(self, app_name: str) -> bool:
        """
        Close application by name.
        
        Args:
            app_name: Application name or PID
            
        Returns:
            True if successful
        """
        try:
            if psutil is None:
                _emit_log(self.logger, "warning", "psutil is not available; cannot close applications by name")
                return False

            for proc in psutil.process_iter(["pid", "name"]):
                if app_name.lower() in proc.info['name'].lower():
                    proc.kill()
                    _emit_log(self.logger, "info", "Closed application", app_name=app_name)
                    return True

            _emit_log(self.logger, "warning", "Application not found", app_name=app_name)
            return False
        except Exception as error:
            _emit_log(self.logger, "error", "Failed to close application", app_name=app_name, error=str(error))
            return False

    def is_running(self, app_name: str) -> bool:
        """
        Check if application is running.
        
        Args:
            app_name: Application name
            
        Returns:
            True if running
        """
        try:
            if psutil is None:
                _emit_log(self.logger, "warning", "psutil is not available; cannot inspect running applications")
                return False

            for proc in psutil.process_iter(["pid", "name"]):
                if app_name.lower() in proc.info['name'].lower():
                    return True
            return False
        except Exception as error:
            _emit_log(self.logger, "error", "Failed to check if application is running", app_name=app_name, error=str(error))
            return False

    def get_running_processes(self) -> list[dict[str, str | int]]:
        """
        Get list of running processes.
        
        Returns:
            List of process information
        """
        try:
            if psutil is None:
                _emit_log(self.logger, "warning", "psutil is not available; cannot enumerate processes")
                return []

            processes: list[dict[str, str | int]] = []
            for proc in psutil.process_iter(["pid", "name", "status"]):
                processes.append({
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "status": proc.info["status"],
                })
            _emit_log(self.logger, "debug", "Enumerated running processes", count=len(processes))
            return processes
        except Exception as error:
            _emit_log(self.logger, "error", "Failed to get running processes", error=str(error))
            return []

    def shutdown(self) -> None:
        """Shutdown application manager."""
        _emit_log(self.logger, "info", "Application manager shutdown")
