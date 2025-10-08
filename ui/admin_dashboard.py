from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from typing import Optional, Deque, List, Tuple, Callable, Mapping, TypedDict
from collections import deque, defaultdict
import time
import math
import subprocess, sys, threading, tempfile
import numpy as np

import matplotlib
matplotlib.use("TkAgg")

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

try:
    import pandas as pd
    HAVE_PANDAS = True
except Exception:
    HAVE_PANDAS = False


class MetricsDict(TypedDict, total=False):
    wpm: float
    cpm: float
    avg_delay_ms: float


@dataclass
class FeedRow:
    t_utc: str
    app: Optional[str]
    etype: str
    severity: Optional[str]
    why: Optional[str]

class AdminDashboard(ttk.Frame):
    """
    Tkinter admin dashboard:
      - Live feed (time, app, type, severity, why)
      - Metrics panel: WPM, CPM, avg delay ms, flags count
      - Timeline chart: per-minute flags + typing speed
      - Export CSV (current feed)
    """
    def __init__(self, parent: tk.Widget, max_rows: int = 1000):
        super().__init__(parent)
        self.max_rows = max_rows

        # --- model buffers ---
        self._ui_queue: Deque[FeedRow] = deque()
        self._feed: Deque[FeedRow] = deque(maxlen=max_rows)
        self._flags_count = 0

        # per-minute buckets (epoch minute -> (flags, keys))
        self._bucket_flags = defaultdict(int)
        self._bucket_keys = defaultdict(int)

        # metrics snapshot (updated by on_event on key events via upstream)
        self.wpm_var = tk.StringVar(value="WPM: —")
        self.cpm_var = tk.StringVar(value="CPM: —")
        self.delay_var = tk.StringVar(value="Avg delay: —")
        self.flags_var = tk.StringVar(value="Flags: 0")

        # --- layout ---
        self._build_widgets()

        # --- timers ---
        self.after(100, self._drain_ui_queue)       # apply live feed updates
        self.after(1000, self._refresh_metrics)     # poll metrics provider if bound
        self.after(1500, self._redraw_chart)        # redraw timeline

        # metrics provider (optional) – set by host
        self.metrics_provider: Optional[Callable[[], MetricsDict]] = None

    # Public API from host window
    def handle_event(self, ev_dict: dict) -> None:
        """
        Accepts normalized event dict:
          {
            "t_utc": "...",
            "app": "chrome.exe",
            "etype": "COMMAND"/"CLIPBOARD"/...,
            "severity": "low/medium/high" or None,
            "why": "rationale string" or None,
            "keys_inc": 1 (optional: for per-minute typing bucket)
          }
        """
        row = FeedRow(
            t_utc=ev_dict.get("t_utc", ""),
            app=ev_dict.get("app"),
            etype=ev_dict.get("etype", ""),
            severity=ev_dict.get("severity"),
            why=ev_dict.get("why"),
        )
        self._ui_queue.append(row)

        # update per-minute buckets
        now_min = int(time.time() // 60)
        if ev_dict.get("severity"):  # anomaly flagged
            self._bucket_flags[now_min] += 1
            self._flags_count += 1
            self.flags_var.set(f"Flags: {self._flags_count}")
        if ev_dict.get("keys_inc"):
            self._bucket_keys[now_min] += ev_dict["keys_inc"]

    # Optional: bind a metrics provider function
    def bind_metrics_provider(self, provider_callable):
        self.metrics_provider = provider_callable

    # --- UI build ---
    def _build_widgets(self):
        # Top: metrics panel
        metrics = ttk.Frame(self)
        metrics.pack(fill="x", padx=8, pady=6)

        ttk.Label(metrics, textvariable=self.wpm_var).pack(side="left", padx=(0, 12))
        ttk.Label(metrics, textvariable=self.cpm_var).pack(side="left", padx=(0, 12))
        ttk.Label(metrics, textvariable=self.delay_var).pack(side="left", padx=(0, 12))
        ttk.Label(metrics, textvariable=self.flags_var).pack(side="left")

        ttk.Button(metrics, text="Export CSV", command=self._export_csv).pack(side="right")
        ttk.Button(metrics, text="Verify DB", command=self._verify_db_clicked).pack(side="right", padx=(0,8))


        # Middle: live feed table
        feed = ttk.Frame(self)
        feed.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        cols = ("time", "app", "etype", "severity", "why")
        self.tree = ttk.Treeview(feed, columns=cols, show="headings", height=12)
        for c, w in [("time", 180), ("app", 180), ("etype", 100), ("severity", 90), ("why", 600)]:
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w, stretch=(c == "why"))
        self.tree.pack(side="left", fill="both", expand=True)

        yscroll = ttk.Scrollbar(feed, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")

        # Bottom: timeline chart
        chart = ttk.Frame(self)
        chart.pack(fill="both", expand=False, padx=8, pady=(0, 8))

        self.fig = Figure(figsize=(7.5, 2.8), dpi=100)
        self.ax_flags = self.fig.add_subplot(111)
        self.ax_flags.set_title("Per‑minute: Flags (bars) & Typing Speed CPM (line)")
        self.ax_flags.set_xlabel("Minute (relative)")
        self.ax_flags.set_ylabel("Count")

        self.canvas = FigureCanvasTkAgg(self.fig, master=chart)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # --- UI loops ---
    def _drain_ui_queue(self):
        # move rows from queue to table with a cap
        moved = 0
        while self._ui_queue and moved < 200:
            row = self._ui_queue.popleft()
            self._feed.appendleft(row)
            # insert at top
            self.tree.insert("", 0, values=(row.t_utc, row.app, row.etype, (row.severity or ""), (row.why or "")))
            # cap Treeview rows
            if len(self._feed) >= self.max_rows:
                # remove extra rows at end of view
                children = self.tree.get_children("")
                if len(children) > self.max_rows:
                    for iid in children[self.max_rows:]:
                        self.tree.delete(iid)
            moved += 1
        self.after(100, self._drain_ui_queue)

    def _refresh_metrics(self):
      provider = self.metrics_provider
      if provider is not None:
          try:
              m = provider()
              if m:
                  wpm = float(m.get("wpm", 0.0))
                  cpm = float(m.get("cpm", 0.0))
                  ad  = float(m.get("avg_delay_ms", float("nan")))
                  self.wpm_var.set(f"WPM: {wpm:.1f}")
                  self.cpm_var.set(f"CPM: {cpm:.1f}")
                  ad_str = f"{ad:.0f} ms" if not math.isnan(ad) else "—"
                  self.delay_var.set(f"Avg delay: {ad_str}")
          except Exception:
              # swallow UI update errors; keep dashboard responsive
              pass
      self.after(1000, self._refresh_metrics)

    def _redraw_chart(self):
        # Align buckets to last 30 minutes
        now_min = int(time.time() // 60)
        mins = np.arange(now_min - 29, now_min + 1)
        flags = np.array([self._bucket_flags.get(int(m), 0) for m in mins], dtype=float)
        keys = np.array([self._bucket_keys.get(int(m), 0) for m in mins], dtype=float)
        cpm = (keys / 60.0) * 60.0  # keys per minute ~ CPM proxy

        self.ax_flags.clear()
        self.ax_flags.bar(np.arange(len(mins)), flags, label="Flags/min")
        self.ax_flags.plot(np.arange(len(mins)), cpm, label="CPM", marker="o")
        self.ax_flags.set_title("Per‑minute: Flags (bars) & Typing Speed CPM (line)")
        self.ax_flags.set_xlabel("Last 30 minutes")
        self.ax_flags.set_ylabel("Count")
        self.ax_flags.legend(loc="upper left")
        self.canvas.draw_idle()

        self.after(1500, self._redraw_chart)

    def _export_csv(self):
        if not self._feed:
            messagebox.showinfo("Export CSV", "No data to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )
        if not path:
            return
        try:
            if HAVE_PANDAS:
                import pandas as pd
                df = pd.DataFrame([{
                    "time": r.t_utc,
                    "app": r.app,
                    "etype": r.etype,
                    "severity": r.severity,
                    "why": r.why
                } for r in reversed(self._feed)])  # chronological
                df.to_csv(path, index=False)
            else:
                # Manual CSV
                import csv
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["time", "app", "etype", "severity", "why"])
                    for r in reversed(self._feed):
                        w.writerow([r.t_utc, r.app or "", r.etype, r.severity or "", r.why or ""])
            messagebox.showinfo("Export CSV", f"Exported {len(self._feed)} rows to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export CSV", f"Failed to export: {e}")

    def _verify_db_clicked(self):
      import os, sys, threading, subprocess
      from tkinter import messagebox

      # Resolve DB and secrets paths (default: current working dir)
      db_path = os.path.abspath("apg_segments.sqlite3")
      secrets_dir = os.path.abspath("secrets")

      # Build the command differently for dev vs. packaged
      if getattr(sys, "frozen", False):
          # Running as a PyInstaller EXE: call the same EXE with CLI subcommand
          exe = sys.executable  # path to AntiPasteGuard.exe
          cmd = [exe, "verify", "--db", db_path, "--secrets", secrets_dir, "--verbose"]
      else:
          # Dev mode: run the CLI module directly with current Python
          py = sys.executable
          cli = os.path.join(os.path.abspath("."), "tools", "apg_cli.py")
          cmd = [py, cli, "verify", "--db", db_path, "--secrets", secrets_dir, "--verbose"]

      def worker():
          try:
              proc = subprocess.run(cmd, capture_output=True, text=True)
              out = (proc.stdout or "").strip()
              err = (proc.stderr or "").strip()

              # Helpful hints if verification fails due to missing files
              if proc.returncode != 0:
                  hints = []
                  if not os.path.exists(db_path):
                      hints.append(f"- DB not found at: {db_path}")
                  if not os.path.isdir(secrets_dir) or not os.path.exists(os.path.join(secrets_dir, "master.key")):
                      hints.append(f"- master.key not found under: {secrets_dir}")
                  hint_text = ("\n\nHints:\n" + "\n".join(hints)) if hints else ""
                  self._show_text_dialog("Verification Errors", (out + "\n\n" + err).strip() + hint_text or "Verification failed.")
              else:
                  self._show_text_dialog("Verification Result", out or "All checks passed.")
          except Exception as e:
              messagebox.showerror("Verify DB", f"Failed to run verifier:\n{e}")

      threading.Thread(target=worker, daemon=True).start()


    def _show_text_dialog(self, title: str, text: str):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("720x420")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="word")
        txt.pack(side="left", fill="both", expand=True)
        y = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        y.pack(side="right", fill="y")
        txt.configure(yscrollcommand=y.set)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

