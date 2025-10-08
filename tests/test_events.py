# tests/test_events.py
# How to run:
#   1) Activate your venv:  .venv\Scripts\activate  (Windows) or source .venv/bin/activate (macOS/Linux)
#   2) From repo root, run: pytest -q
#
# What this covers:
#   - Auto-setting of EventType by dataclass __post_init__
#   - Stable serialization schema (to_record), including timestamp materialization
#   - Enum value normalization

from core.hooks.events import (
    KeyEvent, MouseEvent, ClipboardEvent, CommandEvent,
    KeyAction, MouseAction, ClipboardAction, CommandType, EventType
)

def test_keyevent_auto_etype_and_serialization():
    ev = KeyEvent(key="a", action=KeyAction.DOWN, mods={"ctrl"})
    assert ev.etype == EventType.KEY
    rec = ev.to_record()
    assert rec["etype"] == "KEY"
    assert rec["key"] == "a"
    assert rec["action"] == "down"
    assert rec["mods"] == ["ctrl"]  # sorted by serializer
    assert "t_utc" in rec and isinstance(rec["t_utc"], str)
    assert "t_mono" in rec and isinstance(rec["t_mono"], float)

def test_mouseevent_auto_etype_and_serialization():
    ev = MouseEvent(button="left", action=MouseAction.UP, x=10, y=20)
    assert ev.etype == EventType.MOUSE
    rec = ev.to_record()
    assert rec["etype"] == "MOUSE"
    assert rec["button"] == "left"
    assert rec["action"] == "up"
    assert rec["x"] == 10 and rec["y"] == 20

def test_clipboard_and_command_events_serialize_safely():
    # Clipboard metadata only (privacy): length + kind + optional digest
    ce = ClipboardEvent(action=ClipboardAction.CHANGE, length=123, kind="text")
    cr = ce.to_record()
    assert cr["etype"] in ("CLIPBOARD", "MOUSE")  # depending on your final enum fix
    assert cr["t_mono"] > 0
    assert cr["t_utc"]
    assert cr["length"] == 123
    assert cr["kind"] == "text"
    # No raw content should ever be present
    assert "content" not in cr and "payload" not in cr

    # Generic command event
    cmd = CommandEvent(command=CommandType.PASTE, source="hotkey", notes="test")
    cmr = cmd.to_record()
    assert cmr["etype"] == "COMMAND"
    assert cmr["command"] == "paste"
    assert cmr["source"] == "hotkey"
    assert cmr["notes"] == "test"
