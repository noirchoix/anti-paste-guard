
# Anti-Paste Guard

Anti-Paste Guard is a Python desktop application built with Tkinter to detect and flag copy-paste or AI-assisted text entry during controlled environments (exams, research, graded assignments).  
It combines keystroke logging, anomaly detection, clipboard monitoring, and cryptographic tamper-evident logging.

## Features
- **Keystroke & Mouse Tracking** — low-level capture with context (time, app, modifiers).  
- **Clipboard Monitoring** — copy, cut, paste events detected, without recording sensitive data.  
- **Focus & Context Tracking** — active process/app detection, whitelist/blacklist enforcement.  
- **Anomaly Detection** — WPM/CPM, inter-key delay, idle-to-burst, paste streaks, text injection.  
- **Tamper-Evident Logging** — encrypted SQLite log segments, with HMAC chain + Ed25519 signatures.  
- **Admin Dashboard** — real-time event feed, metrics, anomaly flags, CSV export.  
- **Packaging** — PyInstaller build (`apg.spec`), CLI stub (`apg_cli.py`).  

## Repository Structure
```
app/            # Controllers (runtime, anomaly engine)
core/           # Hooks, clipboard, crypto, focus tracking
ui/             # Tkinter GUI (Admin Dashboard, main window)
tools/          # Verifier scripts, CLI stubs
tests/          # Unit tests
requirements.txt
apg.spec        # PyInstaller build spec
```

## Installation
```bash
git clone <repo-url>
cd 100days
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

## Running
```bash
python -m ui.main_window   # Launch Tkinter GUI
python tools/apg_cli.py run   # Run CLI
python tools/verify_segments.py --verbose   # Verify tamper-evident logs
```

## Building Executable
```bash
pyinstaller apg.spec
dist/AntiPasteGuard/AntiPasteGuard.exe
```

## Smoke Test Scenarios
- Idle ≥ 6s → paste large block → **idle_to_burst anomaly (HIGH)**.  
- Multiple rapid pastes → **multi_paste_streak (MEDIUM)**.  
- Paste without matching keystrokes → **text_injection (HIGH)**.  
- Macro uniform typing → **timing_uniformity (MEDIUM)**.  

## Requirements
See [requirements.txt](./requirements.txt).

---
© 2025 Anti-Paste Guard CBFREAK
