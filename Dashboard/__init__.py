"""Dashboard package for the NARVIS runtime."""

from .dashboard import (
    DashboardLogBuffer,
    DashboardLogger,
    DashboardModule,
    DashboardRuntimeHook,
    DashboardServices,
    attach_dashboard_log_handler,
    build_dashboard_services,
    register_dashboard_services,
)
from .status import (
    DashboardRuntimeActions,
    DashboardSnapshot,
    LogEntry,
    MetricsProvider,
    ModuleStatus,
    PlatformSystemMetricsProvider,
    RuntimeInsights,
    SystemMetrics,
    utc_now,
)

__all__ = [
    "DashboardLogBuffer",
    "DashboardLogger",
    "DashboardModule",
    "DashboardRuntimeActions",
    "DashboardRuntimeHook",
    "DashboardServices",
    "DashboardSnapshot",
    "LogEntry",
    "MetricsProvider",
    "ModuleStatus",
    "PlatformSystemMetricsProvider",
    "RuntimeInsights",
    "SystemMetrics",
    "attach_dashboard_log_handler",
    "build_dashboard_services",
    "register_dashboard_services",
    "utc_now",
]
