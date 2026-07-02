"""Application launching and process-management services for NARVIS."""

from __future__ import annotations

import logging
import platform
import subprocess

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None


class ApplicationManager:
    """Manages application launching and management."""

    def __init__(self) -> None:
        """Initialize the application manager."""
        self.logger = logging.getLogger(__name__)
        self.os_type = platform.system()
        self.logger.info(f"Application manager initialized for {self.os_type}")

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
            
            self.logger.info(f"Opened application: {app_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to open application: {e}")
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
                aliases = {
                    "calculator": "calc.exe",
                    "calc": "calc.exe",
                    "notepad": "notepad.exe",
                    "paint": "mspaint.exe",
                    "mspaint": "mspaint.exe",
                    "cmd": "cmd.exe",
                    "command prompt": "cmd.exe",
                    "explorer": "explorer.exe",
                    "file explorer": "explorer.exe",
                    "task manager": "taskmgr.exe",
                    "control panel": "control.exe",
                    "registry editor": "regedit.exe",
                }
                resolved = aliases.get(app_name.lower(), app_name)
                subprocess.Popen(resolved)
            else:
                subprocess.Popen(["open", "-a", app_name])
            
            self.logger.info(f"Opened application: {app_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to open application by name: {e}")
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
                self.logger.warning("psutil is not available; cannot close applications by name")
                return False

            for proc in psutil.process_iter(["pid", "name"]):
                if app_name.lower() in proc.info['name'].lower():
                    proc.kill()
                    self.logger.info(f"Closed application: {app_name}")
                    return True
            
            self.logger.warning(f"Application not found: {app_name}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to close application: {e}")
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
                self.logger.warning("psutil is not available; cannot inspect running applications")
                return False

            for proc in psutil.process_iter(["pid", "name"]):
                if app_name.lower() in proc.info['name'].lower():
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to check if application is running: {e}")
            return False

    def get_running_processes(self) -> list[dict[str, str | int]]:
        """
        Get list of running processes.
        
        Returns:
            List of process information
        """
        try:
            if psutil is None:
                self.logger.warning("psutil is not available; cannot enumerate processes")
                return []

            processes: list[dict[str, str | int]] = []
            for proc in psutil.process_iter(["pid", "name", "status"]):
                processes.append({
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "status": proc.info["status"],
                })
            self.logger.debug(f"Found {len(processes)} running processes")
            return processes
        except Exception as e:
            self.logger.error(f"Failed to get running processes: {e}")
            return []

    def shutdown(self) -> None:
        """Shutdown application manager."""
        self.logger.info("Application manager shutdown")
