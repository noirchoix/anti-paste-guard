from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AnomalyConfig:
    # windows (seconds)
    wpm_window_s: float = 60.0
    cpm_window_s: float = 60.0
    entropy_window_s: float = 20.0
    keys_window_s: float = 5.0

    # idle→burst
    idle_threshold_s: float = 6.0
    burst_min_len: int = 60  # clipboard length that counts as a burst

    # Δtext ≫ Δkeys
    text_insertion_min: int = 40
    keys_small_max: int = 5  # small number of keys recently

    # multi-paste streaks
    paste_window_s: float = 15.0
    paste_streak_n: int = 3

    # timing entropy / automation
    min_interkey_samples: int = 12
    uniform_cv_threshold: float = 0.12
