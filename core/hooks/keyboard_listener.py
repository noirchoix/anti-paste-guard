# core/hooks/keyboard_listener.py
from __future__ import annotations
from typing import Set, Optional
import threading
from queue import Queue
from pynput import keyboard
import structlog

from .events import KeyEvent, KeyAction
from core.utils.queueing import safe_put

log = structlog.get_logger()

MOD_KEYS = {
    keyboard.Key.shift: "shift",
    keyboard.Key.shift_r: "shift",
    keyboard.Key.shift_l: "shift",
    keyboard.Key.ctrl: "ctrl",
    keyboard.Key.ctrl_l: "ctrl",
    keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.alt: "alt",
    keyboard.Key.alt_l: "alt",
    keyboard.Key.alt_r: "alt",
    keyboard.Key.cmd: "cmd",      # macOS / some Linux
    keyboard.Key.cmd_l: "cmd",
    keyboard.Key.cmd_r: "cmd",
    # keyboard.Key.super: "cmd",
}

def _key_to_str(k: keyboard.Key | keyboard.KeyCode) -> str:
    try:
        if isinstance(k, keyboard.KeyCode):
            return k.char if k.char else f"keycode_{k.vk or 'unknown'}"
        return str(k).split(".")[-1]
    except Exception:
        return "unknown"

class KeyboardHook:
    """Background pynput keyboard listener emitting KeyEvent into a queue."""
    def __init__(self, out_q: Queue):
        self.out_q = out_q
        self._mods: Set[str] = set()
        self._listener: Optional[keyboard.Listener] = None
        self._stop_evt = threading.Event()

    def start(self) -> None:
        if self._listener and self._listener.running:
            return
        self._stop_evt.clear()
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False
        )
        self._listener.daemon = True
        self._listener.start()
        log.info("kbd.start")

    def stop(self) -> None:
        self._stop_evt.set()
        if self._listener:
            self._listener.stop()
            self._listener = None
        log.info("kbd.stop")

    def _on_press(self, key):
        name = _key_to_str(key)
        if key in MOD_KEYS:
            self._mods.add(MOD_KEYS[key])
        ev = KeyEvent(key=name, action=KeyAction.DOWN, mods=set(self._mods))
        safe_put(self.out_q, ev)

    def _on_release(self, key):
        name = _key_to_str(key)
        if key in MOD_KEYS:
            self._mods.discard(MOD_KEYS[key])
        ev = KeyEvent(key=name, action=KeyAction.UP, mods=set(self._mods))
        safe_put(self.out_q, ev)
