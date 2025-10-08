# tests/test_paste_classifier.py
# How to run:
#   1) Activate your venv:
#        - Windows: .venv\Scripts\activate
#        - macOS/Linux: source .venv/bin/activate
#   2) From repo root: pytest -q
#
# What this covers:
#   - Hotkey paste detection via Ctrl/Cmd+V (emits CommandEvent(PASTE, source="hotkey"))
#   - Context menu paste inference: right-click followed by clipboard change within window
#   - Primary selection hint (Linux-style): middle-click emits PASTE_PRIMARY_POSSIBLE when enabled

import queue
from time import perf_counter, sleep

from app.controller.paste_classifier import PasteClassifier, PasteClassifierConfig
from core.hooks.events import (
    KeyEvent, MouseEvent,
    KeyAction, MouseAction,
    CommandEvent, CommandType,
    EventType,
)
from core.hooks.events import ClipboardEvent, ClipboardAction  # if defined in your events module


def _drain(q: queue.Queue):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:
            break
    return out


def test_hotkey_paste_detection_via_ctrl_v():
    q = queue.Queue()
    pc = PasteClassifier(out_q=q, config=PasteClassifierConfig(context_window_sec=1.0, primary_hint=False))

    # Simulate Ctrl+V keydown then keyup
    pc.process(KeyEvent(key="v", action=KeyAction.DOWN, mods={"ctrl"}))
    pc.process(KeyEvent(key="v", action=KeyAction.UP, mods={"ctrl"}))

    events = _drain(q)
    cmds = [e for e in events if isinstance(e, CommandEvent)]
    assert cmds, f"Expected CommandEvent; got: {[type(e).__name__ for e in events]}"
    assert cmds[-1].command == CommandType.PASTE
    assert getattr(cmds[-1], "source", "hotkey") in ("hotkey", "keyboard")


def test_context_menu_paste_inference_right_click_then_clipboard_change():
    q = queue.Queue()
    # Use a small window & zero cooldown so the test is fast and deterministic
    pc = PasteClassifier(out_q=q, config=PasteClassifierConfig(context_window_sec=0.5, context_cooldown_sec=0.0, primary_hint=False))

    # Right-click event (DOWN is enough; your code tracks DOWN/UP)
    rc = MouseEvent(button="right", action=MouseAction.DOWN, x=100, y=200)
    pc.process(rc)

    # Now a clipboard change event within the context window -> should infer context paste
    # ClipboardEvent must carry t_mono close to right-click; we use the default constructor timing,
    # but the classifier uses ev.t_mono, which is set in BaseEvent default via perf_counter()
    ce = ClipboardEvent(action=ClipboardAction.CHANGE, length=42, kind="text")
    
    pc.process(ce)

    events = _drain(q)
    cmds = [e for e in events if isinstance(e, CommandEvent)]
    assert cmds, f"Expected CommandEvent; got: {[type(e).__name__ for e in events]}"
    assert cmds[-1].command == CommandType.PASTE_CONTEXT
    assert cmds[-1].source in ("context", "context_menu")


def test_primary_selection_hint_middle_click_when_enabled():
    q = queue.Queue()
    pc = PasteClassifier(out_q=q, config=PasteClassifierConfig(primary_hint=True))

    mid = MouseEvent(button="middle", action=MouseAction.DOWN, x=10, y=10)
    pc.process(mid)

    events = _drain(q)
    cmds = [e for e in events if isinstance(e, CommandEvent)]
    assert cmds, "Expected CommandEvent for primary hint"
    assert cmds[-1].command == CommandType.PASTE_PRIMARY_POSSIBLE
    assert cmds[-1].source == "primary"
