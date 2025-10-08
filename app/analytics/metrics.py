# app/analytics/metrics.py
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Deque, Tuple, List, Optional
import time
import numpy as np

from core.hooks.events import KeyEvent, KeyAction

@dataclass
class MetricsSnapshot:
    wpm: float
    cpm: float
    avg_delay_ms: float
    idle_s: float

class MetricsTracker:
    """
    Maintains sliding windows for keystrokes and inter-key intervals to compute:
    - WPM/CPM
    - average inter-key delay
    - current idle time
    """
    def __init__(self, wpm_window_s: float = 60.0, cpm_window_s: float = 60.0, entropy_window_s: float = 20.0):
        self.wpm_window_s = wpm_window_s
        self.cpm_window_s = cpm_window_s
        self.entropy_window_s = entropy_window_s

        # (t_mono, key) for KEY DOWNs
        self._keys_window: Deque[Tuple[float, str]] = deque()

        # Inter-key intervals as (end_time, dt_seconds), recorded on KEY DOWN
        self._intervals: Deque[Tuple[float, float]] = deque()

        self._last_key_down_t: Optional[float] = None
        self._last_event_t: float = time.perf_counter()

    def observe_key(self, ev: KeyEvent) -> None:
        now = ev.t_mono
        self._last_event_t = now
        if ev.action == KeyAction.DOWN:
            # record interval ending at 'now'
            if self._last_key_down_t is not None:
                dt = now - self._last_key_down_t
                if dt > 0:
                    self._intervals.append((now, dt))
            self._last_key_down_t = now
            # record key in sliding window
            self._keys_window.append((now, ev.key))
        self._gc(now)

    def _gc(self, now: float) -> None:
        # Trim key events by CPM/WPM windows
        cut_w = now - max(self.wpm_window_s, self.cpm_window_s)
        while self._keys_window and self._keys_window[0][0] < cut_w:
            self._keys_window.popleft()

        # Trim intervals by entropy window using interval end_time
        cut_e = now - self.entropy_window_s
        while self._intervals and self._intervals[0][0] < cut_e:
            self._intervals.popleft()

    def snapshot(self) -> MetricsSnapshot:
        now = time.perf_counter()

        # Compute CPM/WPM from key downs (approx: 5 chars = 1 word)
        keys_recent = [k for t, k in self._keys_window if now - t <= self.cpm_window_s]
        cpm = (len(keys_recent) / max(1.0, self.cpm_window_s)) * 60.0
        wpm = cpm / 5.0

        # Average inter-key delay (ms)
        if self._intervals:
            dts = np.array([dt for (_t, dt) in self._intervals], dtype=float)
            avg_delay_ms = float(dts.mean() * 1000.0)
        else:
            avg_delay_ms = 0.0  

        idle_s = now - self._last_event_t
        return MetricsSnapshot(wpm=wpm, cpm=cpm, avg_delay_ms=avg_delay_ms, idle_s=idle_s)

    def interkey_uniformity_cv(self) -> Optional[float]:
        """
        Returns coefficient of variation (std/mean) for inter-key intervals
        over the current entropy window, or None if insufficient samples.
        """
        if len(self._intervals) < 2:
            return None
        dts = np.array([dt for (_t, dt) in self._intervals], dtype=float)
        mean = float(dts.mean())
        if mean <= 0:
            return None
        std = float(dts.std(ddof=1)) if dts.size > 1 else 0.0
        return std / mean
