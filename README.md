# PasteGuard Web

**PasteGuard Web** is a local-first Chrome/Chromium extension for controlled browser-based writing sessions. It detects paste behavior, large text insertions, idle-to-burst activity, repeated paste streaks, and macro-like typing cadence while avoiding full keystroke logging and avoiding storage of typed content by default.

This is the portfolio-ready browser version of the original Tkinter Anti-Paste Guard prototype. The desktop prototype monitored OS-level keyboard, mouse, clipboard, focus, and anomaly signals; this web version narrows scope to consent-based browser pages and captures metadata only.

## Product positioning

PasteGuard Web is a privacy-preserving controlled-writing integrity tool for assessments, interviews, writing tests, LMS forms, and internal review workflows.

It is not a spyware tool. Users start/stop a session manually, and the default mode stores event metadata rather than private text.

## What it detects

- Paste, copy, cut, and drop events
- Large text insertions
- Idle-to-burst writing behavior
- Repeated paste streaks
- Suspiciously uniform typing cadence
- Tab/domain where the event occurred
- Approximate field type: textarea, input, contenteditable, unknown

## What it does not do by default

- Does not store typed text
- Does not store clipboard contents
- Does not monitor native desktop apps
- Does not run a backend server
- Does not upload logs anywhere

## Folder structure

```text
pasteguard_web/
  extension/
    manifest.json
    background.js
    content.js
    popup.html
    popup.js
    popup.css
    dashboard.html
    dashboard.js
    dashboard.css
    options.html
    options.js
    options.css
  docs/
    LEGACY_NOTES.md
```

## Install locally

1. Open Chrome or Edge.
2. Go to `chrome://extensions`.
3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select the `pasteguard_web/extension` folder.
6. Pin the extension.
7. Open a page with a textarea/input/contenteditable editor.
8. Click the extension icon and start a controlled session.

## Demo scenario

1. Start a session.
2. Type normally for a few seconds.
3. Wait idle for 6+ seconds.
4. Paste a large paragraph.
5. Open Dashboard.
6. Review anomalies and export JSON/CSV.

## Privacy model

The default configuration stores only metadata such as event type, timing, length, URL origin, field type, and anomaly reasons. Optional snippet capture is disabled by default and should remain disabled for real assessment contexts unless explicitly consented to by all parties.

## Export formats

- JSON: complete session object with settings, event log, anomalies, risk score, and summary.
- CSV: event-level table suitable for review.

## Notes

Chrome extension Manifest V3 is used. No Node build step is required.
