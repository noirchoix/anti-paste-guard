from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Optional

@dataclass
class AppContext:
    app_name: str = "unknown"
    pid: Optional[int] = None
    title: Optional[str] = None
    since_mono: float = 0.0

class ContextState:
    def __init__(self):
        self._lock = threading.RLock()
        self._current = AppContext()

    def update(self, app_name: str, pid: Optional[int], title: Optional[str], since_mono: float) -> None:
        with self._lock:
            self._current = AppContext(app_name=app_name, pid=pid, title=title, since_mono=since_mono)

    def get_current(self) -> AppContext:
        with self._lock:
            return self._current