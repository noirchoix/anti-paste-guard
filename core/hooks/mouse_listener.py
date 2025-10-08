# core/hooks/mouse_listener.py
from __future__ import annotations
from typing import Optional
import threading
from queue import Queue
from pynput import mouse
import structlog

from .events import MouseEvent, MouseAction
from core.utils.queueing import safe_put

log = structlog.get_logger()

def _btn_to_str(btn: Optional[mouse.Button]) -> Optional[str]:
    if btn is None:
        return None
    name = str(btn).split(".")[-1]
    if name in {"left", "right", "middle"}:
        return name
    return name

class MouseHook:
    """Background pynput mouse listener emitting MouseEvent into a queue."""
    def __init__(self, out_q: Queue):
        self.out_q = out_q
        self._listener: Optional[mouse.Listener] = None
        self._stop_evt = threading.Event()

    def start(self) -> None:
        if self._listener and self._listener.running:
            return
        self._stop_evt.clear()
        self._listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll
        )
        self._listener.daemon = True
        self._listener.start()
        log.info("mouse.start")

    def stop(self) -> None:
        self._stop_evt.set()
        if self._listener:
            self._listener.stop()
            self._listener = None
        log.info("mouse.stop")

    def _on_click(self, x, y, button, pressed):
        ev = MouseEvent(
            button=_btn_to_str(button),
            action=MouseAction.DOWN if pressed else MouseAction.UP,
            clicks=None,
            x=int(x), y=int(y),
        )
        safe_put(self.out_q, ev)

    def _on_scroll(self, x, y, dx, dy):
        ev = MouseEvent(
            button=None,
            action=MouseAction.SCROLL,
            x=int(x), y=int(y),
        )
        safe_put(self.out_q, ev)
