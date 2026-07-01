"""Tkinter user interface for the NARVIS dashboard."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable
from typing import TYPE_CHECKING

from .widgets import ActionBar, LogConsole, MetricCard, ModuleStatusTable

if TYPE_CHECKING:
    from .dashboard import DashboardModule


class DashboardUI:
    """Owns the Tkinter dashboard window and periodic refresh loop."""

    def __init__(self, dashboard: "DashboardModule", *, refresh_interval_ms: int = 1000) -> None:
        self._dashboard = dashboard
        self._refresh_interval_ms = refresh_interval_ms
        self._root: tk.Tk | None = None
        self._closing = False

        self._runtime_state_label: ttk.Label | None = None
        self._refreshed_label: ttk.Label | None = None
        self._cpu_card: MetricCard | None = None
        self._ram_card: MetricCard | None = None
        self._python_card: MetricCard | None = None
        self._narvis_card: MetricCard | None = None
        self._skills_card: MetricCard | None = None
        self._plugins_card: MetricCard | None = None
        self._memory_card: MetricCard | None = None
        self._queue_card: MetricCard | None = None
        self._actions: ActionBar | None = None
        self._status_table: ModuleStatusTable | None = None
        self._log_console: LogConsole | None = None

    def run(self) -> None:
        """Create the window, start refreshing, and enter the Tk main loop."""

        self._root = tk.Tk()
        self._root.title("NARVIS Dashboard")
        self._root.geometry("1180x760")
        self._root.minsize(980, 640)
        self._root.configure(bg="#edf3f8")
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_style()
        self._build_layout()
        self._refresh()
        self._root.mainloop()

    def _configure_style(self) -> None:
        """Configure the widget theme used by the dashboard."""

        assert self._root is not None

        style = ttk.Style(self._root)
        try:
            style.theme_use("clam")
        except tk.TclError:  # pragma: no cover - theme availability varies by platform
            pass

        style.configure("Dashboard.TFrame", background="#edf3f8")
        style.configure("DashboardHeader.TLabel", background="#edf3f8", font=("Segoe UI", 20, "bold"))
        style.configure("DashboardSubheader.TLabel", background="#edf3f8", foreground="#475569", font=("Segoe UI", 10))
        style.configure("DashboardMetricValue.TLabel", background="#edf3f8", font=("Segoe UI", 20, "bold"))
        style.configure("DashboardMetricSubtitle.TLabel", background="#edf3f8", foreground="#475569", font=("Segoe UI", 9))
        style.configure("TLabelframe", background="#edf3f8")
        style.configure("TLabelframe.Label", background="#edf3f8", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        """Create the full dashboard window layout."""

        assert self._root is not None

        container = ttk.Frame(self._root, padding=18, style="Dashboard.TFrame")
        container.grid(row=0, column=0, sticky="nsew")
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)

        container.columnconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)
        container.rowconfigure(6, weight=1)

        header = ttk.Frame(container, style="Dashboard.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="NARVIS Runtime Dashboard", style="DashboardHeader.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self._runtime_state_label = ttk.Label(header, text="Runtime: --", style="DashboardSubheader.TLabel")
        self._runtime_state_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._refreshed_label = ttk.Label(header, text="Last refresh: --", style="DashboardSubheader.TLabel")
        self._refreshed_label.grid(row=1, column=1, sticky="e", pady=(4, 0))

        metrics = ttk.Frame(container, style="Dashboard.TFrame")
        metrics.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)

        self._cpu_card = MetricCard(metrics, title="CPU Usage")
        self._cpu_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._ram_card = MetricCard(metrics, title="RAM Usage")
        self._ram_card.grid(row=0, column=1, sticky="ew", padx=8)
        self._python_card = MetricCard(metrics, title="Python Version")
        self._python_card.grid(row=0, column=2, sticky="ew", padx=8)
        self._narvis_card = MetricCard(metrics, title="NARVIS Version")
        self._narvis_card.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        insights = ttk.Frame(container, style="Dashboard.TFrame")
        insights.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            insights.columnconfigure(column, weight=1)

        self._skills_card = MetricCard(insights, title="Loaded Skills")
        self._skills_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._plugins_card = MetricCard(insights, title="Loaded Plugins")
        self._plugins_card.grid(row=0, column=1, sticky="ew", padx=8)
        self._memory_card = MetricCard(insights, title="Stored Memories")
        self._memory_card.grid(row=0, column=2, sticky="ew", padx=8)
        self._queue_card = MetricCard(insights, title="Queued Actions")
        self._queue_card.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        self._actions = ActionBar(
            container,
            on_start=lambda: self._run_action(self._dashboard.start_runtime),
            on_stop=lambda: self._run_action(self._dashboard.stop_runtime),
            on_restart=lambda: self._run_action(self._dashboard.restart_runtime),
            on_test_modules=lambda: self._run_action(self._dashboard.test_modules),
        )
        self._actions.grid(row=3, column=0, sticky="ew", pady=(18, 0))

        self._status_table = ModuleStatusTable(container)
        self._status_table.grid(row=5, column=0, sticky="nsew", pady=(18, 0))

        self._log_console = LogConsole(container)
        self._log_console.grid(row=6, column=0, sticky="nsew", pady=(18, 0))

    def _run_action(self, action: Callable[[], None]) -> None:
        """Run a dashboard action without blocking the Tk event loop."""

        threading.Thread(target=self._safe_action, args=(action,), daemon=True).start()

    def _safe_action(self, action: Callable[[], None]) -> None:
        """Execute an action and route failures back into the dashboard logs."""

        try:
            action()
        except Exception as error:  # pragma: no cover - defensive handling
            self._dashboard.record_ui_error(error)

    def _refresh(self) -> None:
        """Poll the dashboard service and redraw the UI."""

        if self._closing or self._root is None:
            return

        try:
            snapshot = self._dashboard.get_snapshot()
            assert self._runtime_state_label is not None
            assert self._refreshed_label is not None
            assert self._cpu_card is not None
            assert self._ram_card is not None
            assert self._python_card is not None
            assert self._narvis_card is not None
            assert self._skills_card is not None
            assert self._plugins_card is not None
            assert self._memory_card is not None
            assert self._queue_card is not None
            assert self._actions is not None
            assert self._status_table is not None
            assert self._log_console is not None

            self._runtime_state_label.configure(text=f"Runtime: {snapshot.runtime_state.upper()}")
            self._refreshed_label.configure(
                text=f"Last refresh: {snapshot.refreshed_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self._cpu_card.update_metric(f"{snapshot.metrics.cpu_percent:.1f}%", "Current host CPU load")
            self._ram_card.update_metric(
                f"{snapshot.metrics.ram_percent:.1f}%",
                f"{snapshot.metrics.ram_used_mb:.1f} MB / {snapshot.metrics.ram_total_mb:.1f} MB",
            )
            self._python_card.update_metric(snapshot.metrics.python_version, "Interpreter version")
            self._narvis_card.update_metric(snapshot.metrics.narvis_version, "Application version")
            self._skills_card.update_metric(str(snapshot.insights.loaded_skills), "Registered runtime skills")
            self._plugins_card.update_metric(str(snapshot.insights.loaded_plugins), "Loaded runtime plugins")
            self._memory_card.update_metric(str(snapshot.insights.stored_memories), "Persisted memory entries")
            self._queue_card.update_metric(str(snapshot.insights.queued_actions), "Pending automation actions")
            self._actions.update_for_runtime_state(snapshot.runtime_state)
            self._status_table.update_statuses(snapshot.modules)
            self._log_console.update_logs(snapshot.logs)
        except Exception as error:  # pragma: no cover - defensive handling
            self._dashboard.record_ui_error(error)

        self._root.after(self._refresh_interval_ms, self._refresh)

    def _on_close(self) -> None:
        """Close the dashboard window and stop future refreshes."""

        self._closing = True
        if self._root is not None:
            self._root.destroy()
