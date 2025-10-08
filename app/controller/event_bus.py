# app/controller/event_bus.py
from __future__ import annotations
from queue import Queue

# A single queue shared across hooks and the controller.
# Later, we can shard by type or use asyncio; a Queue is enough now.
event_queue: Queue = Queue(maxsize=5000)
