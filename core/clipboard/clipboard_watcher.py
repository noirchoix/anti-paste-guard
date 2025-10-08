# core/clipboard/clipboard_watcher.py
from __future__ import annotations
import threading
import time
from typing import Optional, Callable, Tuple
import structlog
import pyperclip
from blake3 import blake3
from queue import Queue

from core.hooks.events import ClipboardEvent, ClipboardAction
from core.utils.queueing import safe_put

log = structlog.get_logger()

class ClipboardWatcher:
    """
    Polls the system clipboard and emits ClipboardEvent with length + session digest.
    - No plaintext content is stored or retained.
    - Adaptive polling with backoff + jitter to reduce CPU when idle.
    - read_clipboard is injectable for tests or platform-specific providers.
    """
    def __init__(
        self,
        out_q: Queue,
        poll_sec: float = 0.2,
        enable_session_digest: bool = True,
        session_salt: Optional[bytes] = None,
        read_clipboard: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.out_q = out_q
        self.enable_session_digest = enable_session_digest
        self.session_salt = session_salt or blake3(str(time.time()).encode()).digest()

        self.read_clipboard = read_clipboard or self._safe_read

        # Adaptive timing
        self._interval = poll_sec
        self._min_interval = poll_sec
        self._max_interval = 1.0
        self._unchanged_ticks = 0

        self._thr: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_sig: Optional[Tuple[int, str]] = None  # (length, digest_hex_or_empty)

    def start(self) -> None:
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()
        log.info("clipboard.start")

    def stop(self) -> None:
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1.0)
            self._thr = None
        log.info("clipboard.stop")

    def _safe_read(self) -> Optional[str]:
        try:
            return pyperclip.paste()
        except Exception as e:
            # On some platforms without clipboard providers, this may fail.
            log.debug("clipboard.read.error", err=str(e))
            return None

    def _loop(self):
        import random
        while not self._stop.is_set():
            txt = self.read_clipboard()
            if txt is not None:
                length = len(txt)
                digest_hex = ""
                if self.enable_session_digest:
                    h = blake3()
                    h.update(self.session_salt)
                    h.update(txt.encode(errors="ignore"))
                    digest_hex = h.hexdigest()

                # Drop plaintext immediately (privacy)
                txt = None

                sig = (length, digest_hex)
                if sig != self._last_sig:
                    self._last_sig = sig
                    ev = ClipboardEvent(
                        action=ClipboardAction.CHANGE,
                        length=length,
                        kind="text",
                        session_digest=digest_hex or None,
                    )
                    safe_put(self.out_q, ev)
                    # Reset adaptive timer
                    self._interval = self._min_interval
                    self._unchanged_ticks = 0
                else:
                    # No change: backoff gradually
                    self._unchanged_ticks += 1
                    if self._interval < self._max_interval and self._unchanged_ticks % 5 == 0:
                        self._interval = min(self._interval * 1.5, self._max_interval)

            # Jitter +/- 20% to avoid lockstep with UI actions
            sleep_for = self._interval * (0.9 + random.random() * 0.2)
            time.sleep(sleep_for)
