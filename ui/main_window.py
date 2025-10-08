from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Optional

from app.controller.runner import HookRuntime
from ui.admin_dashboard import AdminDashboard
from core.hooks.events import (
    BaseEvent, AnomalyEvent, CommandEvent, KeyEvent
)

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Anti‑Paste Guard — Exam Mode: OFF")
        self.geometry("1000x680")
        self.minsize(820, 480)

        # Root content
        self._content = ttk.Frame(self, padding=12)
        self._content.pack(fill="both", expand=True)

        # Top bar: start/stop + event count (kept from your version)
        topbar = ttk.Frame(self._content)
        topbar.pack(side="top", fill="x", pady=(0, 8))

        self.event_count_var = tk.StringVar(value="Events: 0")
        ttk.Label(topbar, textvariable=self.event_count_var).pack(side="left")

        self.toggle_btn_var = tk.StringVar(value="Start Capture")
        self.toggle_btn = ttk.Button(topbar, textvariable=self.toggle_btn_var, command=self._toggle_capture)
        self.toggle_btn.pack(side="right")

        # Dashboard area (replaces the old Listbox)
        self.dashboard = AdminDashboard(self._content, max_rows=1000)
        self.dashboard.pack(fill="both", expand=True)

        # Status bar (kept)
        self.status_var = tk.StringVar(value="Ready")
        self._status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(8, 4))
        self._status.pack(side="bottom", fill="x")

        # Hook runtime (Stage 2+) with callback into this window
        self._runtime = HookRuntime(on_event=self._on_event)
        self._capturing = False

        # Bind metrics provider so dashboard can pull WPM/CPM/avg delay
        def _metrics_provider():
            m = self._runtime.anomaly.metrics.snapshot()
            return {"wpm": m.wpm, "cpm": m.cpm, "avg_delay_ms": m.avg_delay_ms}
        self.dashboard.bind_metrics_provider(_metrics_provider)

        # Graceful stop on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Optional staged status demo (kept)
        self.after(600, self._demo_state_progress)

    # --- Controls ---
    def _toggle_capture(self):
        if not self._capturing:
            self._runtime.start()
            self._capturing = True
            self.toggle_btn_var.set("Stop Capture")
            self.set_status("Capture: ON")
        else:
            self._runtime.stop()
            self._capturing = False
            self.toggle_btn_var.set("Start Capture")
            self.set_status("Capture: OFF")

    # --- Event callback from runner ---
    def _on_event(self, ev: BaseEvent, count: int):
        # Keep your counter
        self.event_count_var.set(f"Events: {count}")

        # Normalize for dashboard (thread‑safe: dashboard queues internally)
        ev_dict = {
            "t_utc": getattr(ev, "t_utc", ""),
            "app": getattr(ev, "app", None),
            "etype": getattr(getattr(ev, "etype", None), "name", "UNKNOWN"),
        }

        # Count typing for per‑minute CPM proxy
        if isinstance(ev, KeyEvent) and getattr(ev, "action", None) and ev.action.name == "DOWN":
            ev_dict["keys_inc"] = 1

        # If anomaly, add severity/why; otherwise surface commands for context
        if isinstance(ev, AnomalyEvent):
            ev_dict["severity"] = ev.severity.value
            ev_dict["why"] = ev.rationale
        elif isinstance(ev, CommandEvent):
            ev_dict["severity"] = None
            ev_dict["why"] = f"cmd={ev.command.value} src={ev.source}"

        self.dashboard.handle_event(ev_dict)

    # --- Status helpers (kept) ---
    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self._status.update_idletasks()

    def _demo_state_progress(self) -> None:
        steps = ["Initializing…", "Configuring logging…", "Loading modules…", "Ready"]
        def stepper(i=0):
            if i < len(steps):
                self.set_status(steps[i])
                self.after(300, lambda: stepper(i + 1))
        stepper()

    def _on_close(self):
        try:
            if self._capturing:
                self._runtime.stop()
        finally:
            self.destroy()
