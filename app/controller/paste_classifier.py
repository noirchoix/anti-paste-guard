# app/controller/paste_classifier.py
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional, Set, Callable
import structlog
from queue import Queue

from core.hooks.events import (
    BaseEvent, EventType, KeyEvent, MouseEvent,
    KeyAction, MouseAction,
    CommandEvent, CommandType
)
from core.utils.queueing import safe_put

log = structlog.get_logger()

@dataclass
class PasteClassifierConfig:
    context_window_sec: float = 1.0
    context_cooldown_sec: float = 0.3
    primary_hint: bool = True

class PasteClassifier:
    """
    Turns raw input patterns into normalized CommandEvent(s).
    - Hotkeys: Ctrl/Cmd+C/X/V
    - Context paste: right-click -> clipboard change within window (with cooldown)
    - Linux primary: optional hint on middle-click
    """
    def __init__(
        self,
        out_q: Queue,
        config: Optional[PasteClassifierConfig] = None,
        clock: Callable[[], float] = time.perf_counter,
        debug: bool = False,
    ):
        self.out_q = out_q
        self.cfg = config or PasteClassifierConfig()
        self.clock = clock
        self.debug = debug

        self._last_right_click_mono: Optional[float] = None
        self._last_clip_change_mono: Optional[float] = None
        self._last_context_emit_mono: Optional[float] = None

    def notify_clipboard_changed(self, t_mono: float) -> None:
        self._last_clip_change_mono = t_mono

    def process(self, ev: BaseEvent) -> None:
        now = self.clock()

        # Hotkey COPY/CUT/PASTE on key-down
        if ev.etype == EventType.KEY and isinstance(ev, KeyEvent) and ev.action == KeyAction.DOWN:
            m: Set[str] = ev.mods
            k = ev.key.lower()
            if "ctrl" in m or "cmd" in m:
                if k == "c":
                    self._emit(CommandType.COPY, "hotkey", f"mods={sorted(m)}")
                elif k == "x":
                    self._emit(CommandType.CUT, "hotkey", f"mods={sorted(m)}")
                elif k == "v":
                    self._emit(CommandType.PASTE, "hotkey", f"mods={sorted(m)}")

        # Mouse context and primary hints
        if ev.etype == EventType.MOUSE and isinstance(ev, MouseEvent):
            if ev.button == "right" and ev.action in (MouseAction.DOWN, MouseAction.UP):
                self._last_right_click_mono = ev.t_mono

            if self.cfg.primary_hint and ev.button == "middle" and ev.action == MouseAction.DOWN:
                self._emit(CommandType.PASTE_PRIMARY_POSSIBLE, "primary", "middle-click")

        # Clipboard correlation (context paste inference)
        if ev.etype == EventType.CLIPBOARD:
            self.notify_clipboard_changed(ev.t_mono)
            rc = self._last_right_click_mono
            if rc is not None and (ev.t_mono - rc) <= self.cfg.context_window_sec:
                if not self._last_context_emit_mono or (now - self._last_context_emit_mono) >= self.cfg.context_cooldown_sec:
                    self._emit(CommandType.PASTE_CONTEXT, "context", "right-click->clipboard change")
                    self._last_context_emit_mono = now

    def _emit(self, cmd: CommandType, source: str, notes: Optional[str] = None):
        ce = CommandEvent(command=cmd, source=source, notes=notes)
        safe_put(self.out_q, ce)
        if self.debug:
            log.debug("command.emit", cmd=cmd.value, source=source, notes=notes)
