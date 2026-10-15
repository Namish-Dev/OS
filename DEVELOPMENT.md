# Personal OS development status

## Current direction

The system records minimal local activity facts first, then derives project,
learning, and entertainment narratives from those facts. A foreground app is
evidence, not automatic proof that every later browser activity belongs to the
same project.

## Implemented foundation

- Standard activity event model and SQLite event/context store.
- Window-title context extraction for VS Code, Obsidian, file managers and
  Chromium browsers.
- Browser enrichment through an optional local extension or CDP.
- Rule-based project matching and review/learning queue.
- Windows foreground collector retained for development.
- Hyprland foreground collector using local `hyprctl -j activewindow` IPC.
- Permission-controlled Hyprland tools: focus workspace, toggle fullscreen,
  toggle tiled/floating state, and confirmed close-window.
- Heartbeat observations plus factual daily intervals. The local model labels
  fixed blocks but cannot invent their durations or timestamps.
- Read-only Git context collector for trusted project paths; it records branch
  and aggregate status only, never source contents or command history.
- A local VS Code bridge that provides the trusted workspace path required for
  Git enrichment; it sends workspace/file metadata only, never document text.
- User-confirmed topic rules: unknown websites remain unclassified until you
  teach a topic/category; no domain is assumed to be entertainment or learning.
- Clean AI daily report at `python activity/daily_report.py`; it aggregates
  filenames into project/topic totals and lists websites as resources.
- Manual CachyOS/Omarchy validation steps are in `docs/MANUAL_TEST.md`.
- CachyOS deployment template and installer for a user-level systemd tracker
  service; it needs no root access.

## Important limitations

- The active Hyprland collector must be tested in the user's CachyOS session;
  this Windows workspace can validate parsing but cannot call Hyprland IPC.
- Full URLs, terminal command capture, app launch allow-lists, Git context,
  and persistent project/topic attribution are not complete yet.
- `pytest` is declared in `requirements-dev.txt` but was absent from the
  existing virtual environment during this pass.

## Next milestone

1. Store source metadata and privacy settings with each event.
2. Add Git, terminal and VS Code project collectors for Hyprland.
3. Persist daily project/topic attribution and add a current-context view.
4. Add configured application launch and further Hyprland actions through the
   permission gate.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe activity\activity_tracker.py
```

On CachyOS, use `python3` (preferably in a virtual environment) and start the
tracker inside the active Hyprland session so `hyprctl` can access its IPC.
