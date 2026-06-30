"""Reusable Tkinter widgets for the NARVIS dashboard."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

from .status import LogEntry, ModuleStatus


class MetricCard(ttk.LabelFrame):
    """Small labeled card used to display a single metric value."""

    def __init__(self, parent: tk.Misc, *, title: str) -> None:
        super().__init__(parent, text=title, padding=12)
        self.columnconfigure(0, weight=1)
        self._value_label = ttk.Label(self, text="--", style="DashboardMetricValue.TLabel")
        self._value_label.grid(row=0, column=0, sticky="w")
        self._subtitle_label = ttk.Label(self, text="", style="DashboardMetricSubtitle.TLabel")
        self._subtitle_label.grid(row=1, column=0, sticky="w", pady=(6, 0))

    def update_metric(self, value: str, subtitle: str = "") -> None:
        """Update the metric's displayed value and subtitle."""

        self._value_label.configure(text=value)
        self._subtitle_label.configure(text=subtitle)


class ActionBar(ttk.Frame):
    """Toolbar containing dashboard runtime action buttons."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_restart: Callable[[], None],
        on_test_modules: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._start_button = ttk.Button(self, text="Start", command=on_start)
        self._stop_button = ttk.Button(self, text="Stop", command=on_stop)
        self._restart_button = ttk.Button(self, text="Restart", command=on_restart)
        self._test_button = ttk.Button(self, text="Test Modules", command=on_test_modules)

        for index, button in enumerate(
            (self._start_button, self._stop_button, self._restart_button, self._test_button)
        ):
            button.grid(row=0, column=index, padx=(0, 8), sticky="ew")
            self.columnconfigure(index, weight=1)

    def update_for_runtime_state(self, runtime_state: str) -> None:
        """Enable or disable buttons to match the current runtime state."""

        is_running = runtime_state == "running"
        self._start_button.configure(state=tk.DISABLED if is_running else tk.NORMAL)
        self._stop_button.configure(state=tk.NORMAL if is_running else tk.DISABLED)
        self._restart_button.configure(state=tk.NORMAL if is_running else tk.DISABLED)
        self._test_button.configure(state=tk.NORMAL if is_running else tk.DISABLED)


class ModuleStatusTable(ttk.LabelFrame):
    """Table widget used to show module-level runtime status."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, text="Live Module Status", padding=12)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            self,
            columns=("module", "status", "description"),
            show="headings",
            height=10,
        )
        self._tree.heading("module", text="Module")
        self._tree.heading("status", text="Status")
        self._tree.heading("description", text="Description")
        self._tree.column("module", width=160, anchor="w")
        self._tree.column("status", width=120, anchor="center")
        self._tree.column("description", width=440, anchor="w")
        self._tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

    def update_statuses(self, statuses: Sequence[ModuleStatus]) -> None:
        """Replace the current table contents with the provided statuses."""

        for item_id in self._tree.get_children():
            self._tree.delete(item_id)

        for status in statuses:
            self._tree.insert(
                "",
                "end",
                values=(status.name, status.status.upper(), status.description),
            )


class LogConsole(ttk.LabelFrame):
    """Read-only text widget used to display runtime logs."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, text="Runtime Logs", padding=12)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._text = tk.Text(
            self,
            wrap="word",
            state=tk.DISABLED,
            height=14,
            font=("Consolas", 10),
            bg="#10151c",
            fg="#ecf3f9",
            insertbackground="#ecf3f9",
            relief="flat",
        )
        self._text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._text.configure(yscrollcommand=scrollbar.set)
        self._last_rendered_text = ""

    def update_logs(self, logs: Sequence[LogEntry]) -> None:
        """Render the provided log entries without allowing user edits."""

        rendered = "\n".join(self._format_entry(entry) for entry in logs)
        if rendered == self._last_rendered_text:
            return

        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        if rendered:
            self._text.insert("1.0", rendered)
        self._text.configure(state=tk.DISABLED)
        self._text.see(tk.END)
        self._last_rendered_text = rendered

    @staticmethod
    def _format_entry(entry: LogEntry) -> str:
        """Format a log entry for the text console."""

        timestamp = entry.timestamp.astimezone().strftime("%H:%M:%S")
        details = ""
        if entry.context:
            detail_text = ", ".join(f"{key}={value}" for key, value in sorted(entry.context.items()))
            details = f" | {detail_text}"
        return f"[{timestamp}] {entry.level:<8} {entry.source}: {entry.message}{details}"
