# app/analytics/anomaly_engine.py
from __future__ import annotations
import time
from collections import deque
from typing import Deque, Tuple, Optional, Set

from core.hooks.events import (
    BaseEvent, EventType, KeyEvent, ClipboardEvent, CommandEvent,
    KeyAction, CommandType, AnomalyEvent, Severity
)
from app.analytics.metrics import MetricsTracker
from app.analytics.config import AnomalyConfig
from core.utils.queueing import safe_put

class AnomalyEngine:
    """
    Consumes events, updates metrics, and emits AnomalyEvent based on rules:
      - idle→burst
      - Δtext ≫ Δkeys
      - multi-paste streaks
      - timing entropy (uniform inter-key intervals)
    """
    def __init__(self, out_q, config: Optional[AnomalyConfig] = None):
        self.out_q = out_q
        self.cfg = config or AnomalyConfig()
        self.metrics = MetricsTracker(
            wpm_window_s=self.cfg.wpm_window_s,
            cpm_window_s=self.cfg.cpm_window_s,
            entropy_window_s=self.cfg.entropy_window_s,
        )
        # For Δtext≫Δkeys: track recent key DOWNs timestamped
        self._recent_keys: Deque[float] = deque()
        # For multi-paste streaks
        self._paste_times: Deque[float] = deque()
        # For idle→burst
        self._last_idle_start: Optional[float] = None
        self._last_non_idle_t: float = time.perf_counter()

    def process(self, ev: BaseEvent) -> None:
        now = ev.t_mono

        # Update idle tracking / metrics with key events
        if ev.etype == EventType.KEY and isinstance(ev, KeyEvent):
            if ev.action == KeyAction.DOWN:
                self._recent_keys.append(now)
                self._last_non_idle_t = now
            self.metrics.observe_key(ev)

        # Clipboard change events (length only)
        if ev.etype == EventType.CLIPBOARD and isinstance(ev, ClipboardEvent):
            # Rule: idle -> burst
            self._idle_to_burst(now, ev.length)

            # Rule: Δtext ≫ Δkeys
            self._text_injection_without_typing(now, ev.length)

        # Command events for pastes (hotkey/context/primary hint)
        if ev.etype == EventType.COMMAND and isinstance(ev, CommandEvent):
            if ev.command in (CommandType.PASTE, CommandType.PASTE_CONTEXT):
                self._note_paste(now)
                self._multi_paste_streaks(now)

        # Timing entropy rule can be checked periodically or on keystrokes
        if ev.etype == EventType.KEY:
            self._timing_entropy_check()

        # GC old timestamps
        self._gc(now)

    # ---- Rules ----

    def _idle_to_burst(self, now: float, clip_len: int) -> None:
        idle_s = now - self._last_non_idle_t
        if idle_s >= self.cfg.idle_threshold_s and clip_len >= self.cfg.burst_min_len:
            rationale = f"idle {idle_s:.1f}s → clipboard insertion {clip_len} chars"
            features = {"idle_s": round(idle_s, 3), "clip_len": clip_len}
            ev = AnomalyEvent(severity=Severity.HIGH, rule_id="idle_to_burst", rationale=rationale, features=features)
            safe_put(self.out_q, ev)

    def _text_injection_without_typing(self, now: float, clip_len: int) -> None:
        # count keys in the last keys_window_s
        cutoff = now - self.cfg.keys_window_s
        recent_count = sum(1 for t in self._recent_keys if t >= cutoff)
        if clip_len >= self.cfg.text_insertion_min and recent_count <= self.cfg.keys_small_max:
            rationale = f"clipboard {clip_len} chars with {recent_count} key(s) in last {self.cfg.keys_window_s:.1f}s"
            features = {"clip_len": clip_len, "keys_recent": recent_count, "window_s": self.cfg.keys_window_s}
            ev = AnomalyEvent(severity=Severity.HIGH, rule_id="text_injection", rationale=rationale, features=features)
            safe_put(self.out_q, ev)

    def _note_paste(self, now: float) -> None:
        self._paste_times.append(now)

    def _multi_paste_streaks(self, now: float) -> None:
        cutoff = now - self.cfg.paste_window_s
        while self._paste_times and self._paste_times[0] < cutoff:
            self._paste_times.popleft()
        if len(self._paste_times) >= self.cfg.paste_streak_n:
            rationale = f"{len(self._paste_times)} pastes in {self.cfg.paste_window_s:.0f}s"
            features = {"count": len(self._paste_times), "window_s": self.cfg.paste_window_s}
            ev = AnomalyEvent(severity=Severity.MEDIUM, rule_id="multi_paste_streak", rationale=rationale, features=features)
            safe_put(self.out_q, ev)

    def _timing_entropy_check(self) -> None:
        cv = self.metrics.interkey_uniformity_cv()
        if cv is None:
            return
        # smaller CV = more uniform (potential automation)
        if cv <= self.cfg.uniform_cv_threshold and len(self.metrics._intervals) >= self.cfg.min_interkey_samples:
            rationale = f"uniform inter-key timing (cv={cv:.3f} ≤ {self.cfg.uniform_cv_threshold:.3f})"
            features = {"cv": round(cv, 4), "samples": len(self.metrics._intervals)}
            ev = AnomalyEvent(severity=Severity.MEDIUM, rule_id="timing_uniformity", rationale=rationale, features=features)
            safe_put(self.out_q, ev)

    def _gc(self, now: float) -> None:
        # keys window
        cutoff = now - self.cfg.keys_window_s
        while self._recent_keys and self._recent_keys[0] < cutoff:
            self._recent_keys.popleft()
        # paste window handled in _multi_paste_streaks
