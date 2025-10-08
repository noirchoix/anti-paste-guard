from __future__ import annotations
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable, Tuple, Optional

@dataclass
class Verdict:
    allowed: bool
    reason: str

@dataclass
class WhitelistPolicy:
    allow: tuple[str, ...] = ("exam-app*",)
    deny: tuple[str, ...] = ("*browser*", "*chrome*", "*edge*", "*firefox*", "*safari*", "*notepad*", "*notes*")

    def decide(self, app_name: Optional[str]) -> Verdict:
        name = (app_name or "unknown").lower()
        for pat in self.deny:
            if fnmatch(name, pat):
                return Verdict(False, f"deny:{pat}")
        for pat in self.allow:
            if fnmatch(name, pat):
                return Verdict(True, f"allow:{pat}")
        # default policy: not explicitly allowed → flagged (you can flip this default)
        return Verdict(False, "default-deny")
