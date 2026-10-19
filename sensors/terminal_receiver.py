"""
Personal OS — Terminal Event Receiver.

A lightweight local HTTP server (127.0.0.1:8767) that receives structured
terminal command events from:

  • The extended VS Code extension (shell-integration hooks)
  • The PowerShell session hook (scripts/personal_os_ps_hook.ps1)
  • Any future IDE integration

Each POST to /v1/terminal-event must contain a JSON object. Sensitive data
is redacted before persistence. The receiver does NOT validate business logic —
it trusts well-formed JSON from localhost only.

Wire format (all fields optional unless marked *):
  {
    "command":         "*",        -- the executed command text
    "cwd":             "*",        -- working directory
    "exit_code":       0,          -- integer or null
    "output":          "...",      -- combined stdout/stderr
    "shell":           "powershell",
    "terminal_host":   "VS Code",
    "session_id":      "abc123",
    "start_time":      "ISO",
    "completion_time": "ISO",
    "status":          "completed" | "failed" | "running" | "unknown"
  }
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.privacy import sanitize_terminal_event
from core.project_association import resolve_project
from database.dev_store import create_dev_tables, save_terminal_event

DEFAULT_PORT = 8767
_ALLOWED_FIELDS = {
    "command", "cwd", "exit_code", "output", "shell",
    "terminal_host", "session_id", "start_time",
    "completion_time", "status", "source", "capture_note",
}
_MAX_BODY_BYTES = 128 * 1024  # 128 KB


class _State:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_event: dict | None = None
        self._updated_at: float = 0.0

    def record(self, payload: dict) -> None:
        with self._lock:
            self._last_event = payload
            self._updated_at = time.monotonic()

    def latest(self, max_age: float = 300) -> dict | None:
        with self._lock:
            if self._last_event is None or time.monotonic() - self._updated_at > max_age:
                return None
            return dict(self._last_event)


_state = _State()
_server_started = False
_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
_server_lock = threading.Lock()


class _RequestHandler(BaseHTTPRequestHandler):
    database_path: Path | str | None = None

    def do_POST(self):
        if self.path != "/v1/terminal-event":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0:
                self.send_error(400)
                return
            if size > _MAX_BODY_BYTES:
                try:
                    self.rfile.read(size)
                except Exception:
                    pass
                self.send_error(413)
                return
            raw = json.loads(self.rfile.read(size))
            if not isinstance(raw, dict):
                raise ValueError("Expected object")
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return

        # Filter to known fields
        payload = {k: v for k, v in raw.items() if k in _ALLOWED_FIELDS}

        # Sanitize secrets and enforce output limits
        payload = sanitize_terminal_event(payload)

        # Resolve project from cwd
        cwd = payload.get("cwd")
        payload["project_path"] = resolve_project(cwd, use_git=False)

        # Stamp with current time if no timestamp provided
        if "completion_time" not in payload or not payload["completion_time"]:
            payload["completion_time"] = datetime.now().isoformat(timespec="seconds")
        payload.setdefault("timestamp", payload["completion_time"])

        # Derive status from exit_code when not explicit
        exit_code = payload.get("exit_code")
        if payload.get("status") is None:
            if exit_code is None:
                payload["status"] = "unknown"
            elif exit_code == 0:
                payload["status"] = "completed"
            else:
                payload["status"] = "failed"

        _state.record(payload)
        save_terminal_event(payload, self.__class__.database_path)

        self.send_response(204)
        self.end_headers()

    def log_message(self, _format, *_args):
        """Suppress access logs to not pollute the terminal."""


def get_latest_terminal_event(max_age: float = 300) -> dict | None:
    """Return the most recently received terminal event, or None."""
    return _state.latest(max_age)


def start_terminal_receiver(
    port: int = DEFAULT_PORT,
    database_path: Path | str | None = None,
) -> None:
    """Start the terminal event receiver in a background daemon thread."""
    global _server_started, _server, _server_thread
    with _server_lock:
        if _server_started:
            return
        create_dev_tables(database_path)
        _RequestHandler.database_path = database_path
        _server = ThreadingHTTPServer(("127.0.0.1", port), _RequestHandler)
        _server_thread = threading.Thread(
            target=_server.serve_forever,
            name="terminal-event-receiver",
            daemon=True,
        )
        _server_thread.start()
        _server_started = True


def stop_terminal_receiver() -> None:
    """Stop the in-process terminal receiver, if it is running."""
    global _server_started, _server, _server_thread
    with _server_lock:
        server = _server
        thread = _server_thread
        _server_started = False
        _server = None
        _server_thread = None

    if server is None:
        return
    server.shutdown()
    server.server_close()
    if thread is not None:
        thread.join(timeout=5)
