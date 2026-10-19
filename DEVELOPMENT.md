# Personal OS — Raw Activity Tracking & Work Evidence System

## Objective

A reliable, lightweight observation and tracking layer that records raw user activity and development evidence on the computer with timestamps and persists it in a local SQLite database (`database/personal_os.db`).

All downstream interpretation (AI agents, LLM analysis, session grouping, project continuity, productivity scoring) has been stripped out. The system focuses exclusively on factual, observable activity collection and concrete work evidence (file modifications, deduplicated snapshots, terminal executions, active window focus).

## Architecture

```
                                  [ User Activity & Development Sources ]
                                                     │
     ┌──────────────────────┬────────────────────────┼────────────────────────┬──────────────────────┐
     ▼                      ▼                        ▼                        ▼                      ▼
OS Foreground Sensors   Browser Extensions / CDP  VS Code Extension       PowerShell Hook    Filesystem Watcher
 (Windows / Hyprland)   (HTTP :9333 / CDP :9222) (HTTP :8766 Context)   (HTTP :8767 Term)   (Watchdog monitor)
     │                      │                        │                        │                      │
     │                      │                 ┌──────┴──────┐                 │                      │
     │                      │                 │             │                 │                      │
     │                      │           Editor Context   Terminal/Dev         │                      │
     │                      │                 │             │                 │                      │
     └──────────────┬───────┘                 │             └────────┬────────┘                      │
                    ▼                         ▼                      ▼                               ▼
          ActivityEngine & Debounce     Context Enriched     Terminal Receiver (HTTP :8767)   Hash Deduplication & Diffs
                    │                         │                      │                               │
                    │                         │             Privacy Redaction Engine                 │
                    │                         │             (Tokens, Secrets, Head/Tail)             │
                    ▼                         ▼                      │                               │
            activity_events & activity_context                       ▼                               ▼
                            │                               dev_terminal_events & dev_file_changes & dev_snapshots
                            └───────────────────────────────┬────────────────────────────────┘
                                                            ▼
                                           SQLite Database (database/personal_os.db)
```

---

## Components

### 1. OS Foreground & Window Sensors
- **Windows Foreground Sensor** (`sensors/windows/foreground_sensor.py`): Detects active foreground application, process name, process ID (PID), window title, and Win32 window class.
- **Linux Hyprland Sensor** (`sensors/linux/hyprland_sensor.py`): Reads active window title, initial class, address, and workspace via local `hyprctl -j activewindow`.
- **Sensor Factory** (`sensors/factory.py`): Instantiates the appropriate platform foreground sensor based on host OS.

### 2. Browser Tracking & Normalization
- **Extension Server** (`sensors/browser/extension_server.py`): Background HTTP receiver (`http://127.0.0.1:9333/tab`) for the browser extension.
- **Extension Adapter** (`sensors/browser/extension_adapter.py`): Reads the latest active tab reported by the browser extension.
- **Chrome CDP Adapter** (`sensors/browser/chrome_adapter.py` / `cdp_adapter.py`): Fallback via Chrome DevTools Protocol on port 9222.
- **Cascading Browser Adapter** (`sensors/browser/cascading_adapter.py`): Combines extension reporting, CDP fallback, and stripped window titles.
- **URL Privacy & Sanitization** (`core/context_extractors.py`): Strips sensitive authentication tokens, session IDs, and secrets from URLs. Set `OS_STRIP_URL_QUERY=1` to remove all query parameters entirely.

### 3. VS Code Bridge & IDE Integration
- **Context & Dev Event Server** (`sensors/vscode/extension_server.py`):
  - `POST http://127.0.0.1:8766/v1/context`: Receives active workspace name, workspace path, file path, and language.
  - `POST http://127.0.0.1:8766/v1/dev-event`: Receives text document lifecycle events (`file_opened`, `file_saved`, `file_created`, `file_deleted`).
- **VS Code Extension** (`vscode_extension/extension.js`):
  - Automatically reports active editor and workspace changes to `:8766/v1/context`.
  - Captures document lifecycle events and forwards to `:8766/v1/dev-event`.
  - Hooks terminal shell executions via VS Code 1.93+ Shell Integration API (`onDidStartTerminalShellExecution` / `onDidEndTerminalShellExecution`) and streams captured commands, exit codes, working directory, and outputs to `:8767/v1/terminal-event`. Degrades gracefully when shell integration is unavailable.

### 4. Git-Independent Work Evidence System
- **Filesystem Watcher** (`sensors/filesystem_watcher.py`):
  - Monitors project directories using Python's `watchdog` library.
  - Tracks file creation, modification, deletion, and renaming without requiring a Git repository.
  - Computes SHA-256 hashes of file contents to deduplicate snapshots—unchanged files trigger no redundant storage.
  - Computes unified diffs against previous snapshots for text files.
  - Safely handles binary files, skips files exceeding configurable limits (default 512 KB), and excludes build/cache directories (`node_modules`, `.venv`, `__pycache__`, `.git`, etc.).
- **Terminal Event Receiver** (`sensors/terminal_receiver.py`):
  - Lightweight HTTP receiver (`http://127.0.0.1:8767/v1/terminal-event`).
  - Ingests command executions from both the VS Code extension and the standalone PowerShell session hook.
  - Automatically records command text, working directory, exit code, execution timestamps, session ID, terminal host, and combined output.
- **PowerShell Session Hook** (`scripts/personal_os_ps_hook.ps1`):
  - Compatible with PowerShell 7+ and Windows PowerShell 5.1.
  - Wraps the shell prompt and `PSConsoleHostReadLine` to intercept completed commands, working directories, and exit codes (`$LASTEXITCODE` / `$?`).
  - Asynchronously posts events to the terminal receiver with fire-and-forget requests so shell responsiveness is never hindered.

### 5. Privacy, Redaction & Project Association
- **Privacy & Redaction Engine** (`core/privacy.py`):
  - Pattern-based redaction of secrets: OpenAI API keys (`sk-...`), GitHub PATs (`ghp_...`, `github_pat_...`), AWS access keys (`AKIA...`), Bearer tokens, passwords embedded in URLs/connection strings, common key-value credential pairs, and PEM private keys.
  - Exclusion of sensitive files: Never captures contents of `.env*`, `id_rsa*`, `id_ed25519*`, `*.pem`, `*.key`, `credentials.json`, or `secrets.json`.
  - Head/tail output truncation (`truncate_output`): Preserves both beginning and ending of large command outputs and diffs so error messages and stack traces remain visible while enforcing character limits.
- **Project Association** (`core/project_association.py`):
  - Resolves canonical project roots deterministically without requiring Git.
  - Resolution precedence:
    1. Exact match in user-defined project registry (`config/project_paths.json`).
    2. Longest registered workspace path prefix.
    3. Ancestor search for project marker files (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `setup.py`, `pom.xml`, etc.).
    4. Git repository root (optional supplementary signal).
    5. Returns `None` (unassigned) rather than guessing.

### 6. Event Normalization, Engine & Debounce
- **Activity Event Model** (`core/event_model.py`): Unified `ActivityEvent` dataclass with factory helpers (`create`, `create_terminal_event`, `create_file_event`).
- **Context Extractors** (`core/context_extractors.py`): Pure functions parsing window titles for VS Code, Antigravity IDE, Obsidian, and File Explorer.
- **Activity Engine** (`core/activity_engine.py`): Enriches foreground observations with browser, IDE, and window context, producing normalized events.
- **Debounce & Tracker Loop** (`activity/activity_tracker.py`):
  - Filters transient window flickers using candidate debouncing (default 1.5s).
  - Emits heartbeat events (default 60s) for prolonged uninterrupted focus.
  - Coordinates concurrent background services: Browser Extension Receiver (:9333), VS Code Extension Server (:8766), Terminal Event Receiver (:8767), and Filesystem Watcher.

---

## Database Schema & Storage

The system uses a single SQLite database at `database/personal_os.db` managed via `database/database.py` and `database/dev_store.py`. All table creations and migrations are idempotent and non-destructive.

### Core Activity Tables
- **`activity_events`**:
  - Columns: `id`, `timestamp`, `application`, `process`, `pid`, `window_title`, `event_type`, `sensor`.
  - Indexes: `idx_activity_events_timestamp`.
- **`activity_context`**:
  - Columns: `id`, `activity_event_id`, `application`, `workspace`, `workspace_path`, `file`, `file_path`, `note`, `vault`, `domain`, `url`, `page_title`, `path`, `metadata_json`.
  - Indexes: `idx_activity_context_event_id`.

### Development Evidence Tables
- **`dev_file_changes`**:
  - Columns: `id`, `timestamp`, `event_type` (`created`|`modified`|`deleted`|`renamed`), `project_path`, `file_path`, `file_name`, `old_path`, `content_hash`, `diff_text`, `is_binary`, `is_sensitive`, `capture_note`.
  - Indexes: `idx_dev_file_changes_ts`, `idx_dev_file_changes_proj`, `idx_dev_file_changes_path`.
- **`dev_snapshots`**:
  - Columns: `content_hash` (PRIMARY KEY), `captured_at`, `file_path`, `size_bytes`, `content_text`.
- **`dev_terminal_events`**:
  - Columns: `id`, `timestamp`, `start_time`, `completion_time`, `session_id`, `terminal_host`, `shell`, `cwd`, `project_path`, `command`, `exit_code`, `output`, `status` (`completed`|`failed`|`running`|`unknown`), `source`, `capture_note`.
  - Indexes: `idx_dev_terminal_ts`, `idx_dev_terminal_proj`, `idx_dev_terminal_sess`.

---

## Privacy & Safety

- **Strictly Local**: All data remains in `database/personal_os.db`. No telemetry, analytics, or remote transmission.
- **Keystroke & Input Safety**: Keystrokes, passwords, and arbitrary typing are never logged.
- **Secret Redaction**: API keys (OpenAI, AWS, GitHub), bearer tokens, and credentials in URLs or commands are sanitized prior to storage.
- **File Content Protection**: Sensitive configuration files (`.env`, private keys, secrets) have their modifications tracked by filename only; file contents and diffs are never stored.
- **Output Bounds**: Command outputs and diffs are bounded to prevent database bloat while maintaining head/tail diagnostic context.

---

## Commands & Usage

### 1. Install Dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 2. Run Test Suite

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

### 3. Start the Activity Tracker

Starts the foreground sensor, browser receiver (:9333), VS Code context server (:8766), terminal receiver (:8767), and filesystem watcher:

```powershell
.\.venv\Scripts\python.exe activity\activity_tracker.py
```

### 4. Enable PowerShell Session Hook (Optional)

To capture terminal commands directly from PowerShell:

```powershell
# For the current session:
. .\scripts\personal_os_ps_hook.ps1

# Or add to your PowerShell $PROFILE for automatic capture:
Add-Content $PROFILE '. E:\OS\scripts\personal_os_ps_hook.ps1'
```

### 5. Inspect Stored Events

```powershell
# View 20 most recent raw activity events
.\.venv\Scripts\python.exe activity\view.py --limit 20

# Query activity events within a specific time range
.\.venv\Scripts\python.exe activity\view.py --from 2026-10-19T10:00:00 --to 2026-10-19T16:00:00
```

