from __future__ import annotations
import threading
from typing import Optional
import structlog
from dataclasses import replace

from core.hooks.keyboard_listener import KeyboardHook
from core.hooks.mouse_listener import MouseHook
from core.clipboard.clipboard_watcher import ClipboardWatcher
from core.focus.focus_tracker import FocusTracker
from app.controller.event_bus import event_queue
from app.controller.paste_classifier import PasteClassifier, PasteClassifierConfig
from app.controller.context_state import ContextState
from app.policy.whitelist import WhitelistPolicy
from core.hooks.events import BaseEvent, FocusEvent, AnomalyEvent
from app.analytics.anomaly_engine import AnomalyEngine
from app.analytics.config import AnomalyConfig
from core.crypto.segment_store import SegmentStore, SegmentWriter


log = structlog.get_logger()

class HookRuntime:
    """Starts/stops hooks; annotates events with current app; delegates to classifier."""
    def __init__(self, on_event=None):
        self.kbd = KeyboardHook(event_queue)
        self.mouse = MouseHook(event_queue)
        self.clip = ClipboardWatcher(event_queue, poll_sec=0.2, enable_session_digest=True)
        self.focus = FocusTracker(event_queue, poll_sec=0.25)
        self.anomaly = AnomalyEngine(event_queue, config=AnomalyConfig())
        self.store = SegmentStore()
        self.seg_writer = SegmentWriter(self.store, flush_sec=60, max_events=500)
        self.ctx = ContextState()
        self.policy = WhitelistPolicy()

        self.classifier = PasteClassifier(
            event_queue,
            config=PasteClassifierConfig(context_window_sec=1.0, context_cooldown_sec=0.3, primary_hint=True),
            debug=False,
        )
        self._consumer_thr: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._on_event = on_event

    def start(self) -> None:
        self._stop_evt.clear()
        self.kbd.start()
        self.mouse.start()
        self.clip.start()
        self.focus.start()
        self.seg_writer.start()
        self._consumer_thr = threading.Thread(target=self._consume_loop, daemon=True)
        self._consumer_thr.start()
        log.info("hooks.runtime.start")

    def stop(self) -> None:
        self.kbd.stop()
        self.mouse.stop()
        self.clip.stop()
        self.focus.stop()
        self._stop_evt.set()
        if self._consumer_thr:
            self._consumer_thr.join(timeout=1.0)
        self.seg_writer.stop()
        log.info("hooks.runtime.stop")

    def _consume_loop(self):
        count = 0
        while not self._stop_evt.is_set():
            try:
                ev: BaseEvent = event_queue.get(timeout=0.5)
            except Exception:
                continue

            # Focus update / attach app (unchanged)
            if isinstance(ev, FocusEvent):
                self.ctx.update(ev.app_name, ev.pid, ev.title, ev.t_mono)
            else:
                curr = self.ctx.get_current()
                from dataclasses import replace
                try:
                    ev = replace(ev, app=curr.app_name)
                except Exception:
                    pass

            # Paste classifier
            try:
                self.classifier.process(ev)
            except Exception as e:
                log.warning("classifier.error", err=str(e))

            # Anomaly engine
            try:
                self.anomaly.process(ev)
            except Exception as e:
                log.warning("anomaly.error", err=str(e))

            # 👇 persist every event (including AnomalyEvent) into encrypted segments
            try:
                self.seg_writer.add_event(ev)
            except Exception as e:
                log.warning("segment_writer.error", err=str(e))

            # optional: log anomalies
            if isinstance(ev, AnomalyEvent):
                log.info("anomaly.flag", rule=ev.rule_id, severity=ev.severity.value, why=ev.rationale, features=ev.features, app=getattr(ev, "app", None))


            count += 1
            if self._on_event:
                try:
                    self._on_event(ev, count)
                except Exception as e:
                    log.warning("hooks.runtime.on_event.error", err=str(e))