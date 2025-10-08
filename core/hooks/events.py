from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Set, Dict, Any
import time
from datetime import datetime, timezone

# --- timing helpers ---
def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

def mono_ts() -> float:
    # Monotonic high-res timestamp (immune to system clock changes)
    return time.perf_counter()

# --- core enums ---
class EventType(Enum):
    """Top-level classifier for event routing and storage."""
    KEY = auto()
    MOUSE = auto()
    CLIPBOARD = auto()
    COMMAND = auto()
    FOCUS = auto()

class KeyAction(Enum):
    DOWN = "down"
    UP = "up"

class MouseAction(Enum):
    DOWN = "down"
    UP = "up"
    CLICK = "click"     # reserved for future double-click inference if needed
    SCROLL = "scroll"

# --- base event ---
@dataclass(frozen=True)
class BaseEvent:
    """Common shape for all events."""
    etype: EventType = field(init=False)         # auto-set by subclasses
    t_utc: Optional[str] = None                  # lazy; materialized on serialize
    t_mono: float = field(default_factory=mono_ts)
    app: Optional[str] = None                    # filled later (Stage 4)

    def to_record(self) -> Dict[str, Any]:
        t_utc_val = self.t_utc or utc_iso()
        return {
            "etype": self.etype.name,
            "t_utc": t_utc_val,
            "t_mono": self.t_mono,
            "app": self.app,
        }

# --- key event ---
@dataclass(frozen=True)
class KeyEvent(BaseEvent):
    """Low-level keystroke event (no plaintext content, only codes + timing)."""
    key: str = ""
    action: KeyAction = KeyAction.DOWN
    mods: Set[str] = field(default_factory=set)  # {"ctrl","shift","alt","cmd"}
    scan_code: Optional[int] = None              # platform-specific; normalize later

    def __post_init__(self):
        object.__setattr__(self, "etype", EventType.KEY)

    def to_record(self) -> Dict[str, Any]:
        base = super().to_record()
        base.update({
            "key": self.key,
            "action": self.action.value,
            "mods": sorted(self.mods),
            "scan_code": self.scan_code,
        })
        return base

# --- mouse event ---
@dataclass(frozen=True)
class MouseEvent(BaseEvent):
    """Mouse click/scroll event (used for context-menu inference)."""
    button: Optional[str] = None     # "left","right","middle"
    action: MouseAction = MouseAction.DOWN
    clicks: Optional[int] = None     # 1 / 2 for double, if inferred later
    x: Optional[int] = None
    y: Optional[int] = None

    def __post_init__(self):
        object.__setattr__(self, "etype", EventType.MOUSE)

    def to_record(self) -> Dict[str, Any]:
        base = super().to_record()
        base.update({
            "button": self.button,
            "action": self.action.value,
            "clicks": self.clicks,
            "x": self.x,
            "y": self.y,
        })
        return base

# --- clipboard / command enums ---
class ClipboardAction(Enum):
    CHANGE = "change"          # clipboard changed (length/metadata only)

class CommandType(Enum):
    COPY = "copy"
    CUT = "cut"
    PASTE = "paste"
    PASTE_CONTEXT = "paste_context"                # right-click menu paste inference
    PASTE_PRIMARY_POSSIBLE = "paste_primary_possible"  # Linux middle-click hint

# --- clipboard event ---
@dataclass(frozen=True)
class ClipboardEvent(BaseEvent):
    """Clipboard change snapshot: privacy-safe (length + optional session digest)."""
    action: ClipboardAction = ClipboardAction.CHANGE
    length: int = 0                     # chars for text; bytes for non-text if used later
    kind: str = "text"                  # "text" | "unknown"
    session_digest: Optional[str] = None  # optional, session-salted digest

    def __post_init__(self):
        object.__setattr__(self, "etype", EventType.CLIPBOARD)

    def to_record(self) -> Dict[str, Any]:
        base = super().to_record()
        base.update({
            "action": self.action.value,
            "length": self.length,
            "kind": self.kind,
            "session_digest": self.session_digest,
        })
        return base

# --- command event ---
@dataclass(frozen=True)
class CommandEvent(BaseEvent):
    """Normalized commands inferred from input patterns (COPY/CUT/PASTE...)."""
    command: CommandType = CommandType.PASTE
    source: str = "hotkey"    # "hotkey" | "context" | "primary"
    notes: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "etype", EventType.COMMAND)

    def to_record(self) -> Dict[str, Any]:
        base = super().to_record()
        base.update({
            "command": self.command.value,
            "source": self.source,
            "notes": self.notes,
        })
        return base
    

@dataclass(frozen=True)
class FocusEvent(BaseEvent):
    """Window/app focus transition. Emitted only when focus changes."""
    app_name: str = "unknown"       # normalized process/app label
    pid: Optional[int] = None
    title: Optional[str] = None     # active window title if available
    dwell_prev_s: Optional[float] = None  # how long previous app had focus

    def __post_init__(self):
        object.__setattr__(self, "etype", EventType.FOCUS)

    def to_record(self) -> Dict[str, Any]:
        base = super().to_record()
        base.update({
            "app_name": self.app_name,
            "pid": self.pid,
            "title": self.title,
            "dwell_prev_s": self.dwell_prev_s,
        })
        return base
    

class Severity(Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@dataclass(frozen=True)
class AnomalyEvent(BaseEvent):
    """Anomaly signal produced by the real-time engine."""
    severity: Severity = Severity.LOW
    rule_id: str = ""               # e.g., "idle_to_burst", "text_injection"
    rationale: str = ""             # human-readable 'why flagged'
    features: Dict[str, Any] = field(default_factory=dict)  # small feature snapshot

    def __post_init__(self):
        object.__setattr__(self, "etype", EventType.COMMAND)  # reuse channel for routing, or add EventType.ANOMALY if you prefer

    def to_record(self) -> Dict[str, Any]:
        base = super().to_record()
        base.update({
            "severity": self.severity.value,
            "rule_id": self.rule_id,
            "rationale": self.rationale,
            "features": self.features,
        })
        return base
