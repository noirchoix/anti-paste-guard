# tests/test_anomaly_engine.py
# How to run:
#   pytest -q
#
# Verifies:
#   - Idle -> burst paste emits HIGH anomaly
#   - Multi-paste streak emits MEDIUM/HIGH
#   - Text injection emits HIGH
#
# Notes:
#   AnomalyEngine signature in your repo: AnomalyEngine(out_q, config=...)
#   We feed events and then drain the queue for AnomalyEvent.

import time, queue
from app.analytics.anomaly_engine import AnomalyEngine
from core.hooks.events import (
    KeyEvent, CommandEvent, ClipboardEvent,
    KeyAction, CommandType
)

def drain(q: queue.Queue):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:
            break
    return out

def test_idle_to_burst_emits_high():
    q = queue.Queue()
    eng = AnomalyEngine(q)

    # Simulate idle by moving internal clock backward (if engine reads perf_counter, we simulate via metrics)
    # We can't touch private fields portably, so instead: wait briefly, then simulate a big paste
    time.sleep(0.05)
    eng.process(CommandEvent(command=CommandType.PASTE, source="hotkey"))
    eng.process(ClipboardEvent(length=120, kind="text"))

    events = drain(q)
    anomalies = [e for e in events if getattr(e, "severity", None)]
    assert anomalies, f"Expected an anomaly, saw: {[type(e).__name__ for e in events]}"
    assert anomalies[-1].severity.name in ("HIGH", "CRITICAL")

def test_multi_paste_streak_medium_or_higher():
    q = queue.Queue()
    eng = AnomalyEngine(q)

    for _ in range(3):
        eng.process(CommandEvent(command=CommandType.PASTE, source="hotkey"))

    events = drain(q)
    streaks = [e for e in events if "multi_paste_streak" in getattr(e, "rule_id", "")]
    assert streaks, "Expected multi_paste_streak anomaly"
    assert streaks[-1].severity.name in ("MEDIUM", "HIGH", "CRITICAL")

def test_text_injection_high():
    q = queue.Queue()
    eng = AnomalyEngine(q)

    # Few keys followed by large clipboard delta
    for _ in range(2):
        eng.process(KeyEvent(key="a", action=KeyAction.DOWN))
    eng.process(ClipboardEvent(length=200, kind="text"))

    events = drain(q)
    inj = [e for e in events if "text_injection" in getattr(e, "rule_id", "")]
    assert inj, "Expected text_injection anomaly"
    assert inj[-1].severity.name in ("HIGH", "CRITICAL")
