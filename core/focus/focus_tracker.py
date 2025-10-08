from __future__ import annotations
import sys
import threading
import time
from typing import Optional, Tuple, Callable
import structlog

from queue import Queue
from dataclasses import replace

from core.hooks.events import FocusEvent, EventType
from core.utils.queueing import safe_put

log = structlog.get_logger()

# Provider signature: returns (app_name, pid, title)
FocusProvider = Callable[[], Tuple[str, Optional[int], Optional[str]]]

# --- platform-specific providers ---

def _provider_windows() -> Tuple[str, Optional[int], Optional[str]]:
    try:
        import win32gui, win32process
        import psutil
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) if hwnd else ""
        tid, pid = win32process.GetWindowThreadProcessId(hwnd) if hwnd else (None, None)
        name = "unknown"
        if pid:
            try:
                name = psutil.Process(pid).name()
            except Exception:
                pass
        return (name or "unknown", pid, title or None)
    except Exception:
        return ("unknown", None, None)

def _provider_macos() -> Tuple[str, Optional[int], Optional[str]]:
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        name = str(app.localizedName()) if app else "unknown"
        pid = int(app.processIdentifier()) if app else None
        title = None  # getting window title is trickier; omit for now
        return (name.lower(), pid, title)
    except Exception:
        return ("unknown", None, None)

def _provider_linux() -> Tuple[str, Optional[int], Optional[str]]:
    # Portable fallback; getting active window reliably depends on WM/compositor.
    # You can extend this with python-xlib or wayland protocols if needed.
    try:
        # Best-effort: read from /proc or use wmctrl if installed (skipped here).
        return ("unknown", None, None)
    except Exception:
        return ("unknown", None, None)

def default_provider() -> FocusProvider:
    if sys.platform.startswith("win"):
        return _provider_windows
    if sys.platform == "darwin":
        return _provider_macos
    return _provider_linux

class FocusTracker:
    """
    Polls the active app focus; emits FocusEvent on change.
    Adaptive interval with jitter; no emissions if unchanged.
    """
    def __init__(self, out_q: Queue, provider: Optional[FocusProvider] = None, poll_sec: float = 0.25):
        self.out_q = out_q
        self.provider = provider or default_provider()
        self._thr: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._interval = poll_sec
        self._min_interval = poll_sec
        self._max_interval = 1.0
        self._unchanged_ticks = 0

        self._last: Tuple[str, Optional[int], Optional[str]] = ("", None, None)
        self._last_switch_mono = time.perf_counter()

    def start(self) -> None:
        if self._thr and self._thr.is_alive(): return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()
        log.info("focus.start")

    def stop(self) -> None:
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1.0)
            self._thr = None
        log.info("focus.stop")

    def _loop(self):
        import random
        while not self._stop.is_set():
            name, pid, title = self.provider()
            now = time.perf_counter()
            if (name, pid, title) != self._last:
                dwell_prev = now - self._last_switch_mono if self._last[0] else None
                self._last = (name, pid, title)
                self._last_switch_mono = now
                ev = FocusEvent(app_name=(name or "unknown").lower(), pid=pid, title=title, dwell_prev_s=dwell_prev)
                # etype is EventType.FOCUS via __post_init__
                safe_put(self.out_q, ev)
                # reset backoff
                self._interval = self._min_interval
                self._unchanged_ticks = 0
            else:
                self._unchanged_ticks += 1
                if self._interval < self._max_interval and self._unchanged_ticks % 5 == 0:
                    self._interval = min(self._interval * 1.5, self._max_interval)
            time.sleep(self._interval * (0.9 + random.random() * 0.2))