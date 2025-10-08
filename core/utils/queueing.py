# core/utils/queueing.py
from __future__ import annotations
from queue import Queue, Full, Empty

def safe_put(q: Queue, item) -> None:
    """
    Put without blocking; if the queue is full, drop the oldest item and retry.
    Prevents producer threads from stalling and caps memory growth.
    """
    try:
        q.put_nowait(item)
    except Full:
        try:
            q.get_nowait()  # drop oldest
        except Empty:
            pass
        q.put_nowait(item)
