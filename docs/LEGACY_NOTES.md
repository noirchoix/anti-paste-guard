# Legacy Desktop Prototype Notes

The original Anti-Paste Guard project was a Python/Tkinter desktop prototype with low-level keystroke/mouse tracking, clipboard monitoring, focus tracking, anomaly detection, and tamper-evident logging.

PasteGuard Web intentionally narrows the product scope:

- Browser-only controlled writing sessions
- User-started and user-visible monitoring
- Metadata-only capture by default
- No OS-wide keylogging
- No clipboard content retention
- No backend upload path

The preserved anomaly ideas are:

- idle_to_burst
- text_injection
- multi_paste_streak
- timing_uniformity
- paste/drop event tracking
- integrity export
