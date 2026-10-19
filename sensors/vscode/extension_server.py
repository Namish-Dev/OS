"""Local receiver for minimal VS Code extension context and development events."""

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 8766
FRESHNESS_SECONDS = 90
_ALLOWED_FIELDS = {"workspace_path", "workspace", "file_path", "language"}
_DEV_EVENT_FIELDS = {
    "event_type", "file_path", "language", "workspace", "workspace_path", "timestamp",
}


class _State:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict | None = None
        self._updated_at = 0.0

    def update(self, payload: dict) -> None:
        clean = {
            key: str(value)[:2048]
            for key, value in payload.items()
            if key in _ALLOWED_FIELDS and value is not None
        }
        with self._lock:
            self._data = clean
            self._updated_at = time.monotonic()

    def latest(self, max_age: float) -> dict | None:
        with self._lock:
            if self._data is None or time.monotonic() - self._updated_at > max_age:
                return None
            return dict(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data = None
            self._updated_at = 0.0


_state = _State()
_server_started = False


def update_latest_context(payload: dict) -> None:
    """Store an extension report; public for tests and local integrations."""
    if isinstance(payload, dict):
        _state.update(payload)


def get_latest_context(max_age: float = FRESHNESS_SECONDS) -> dict | None:
    return _state.latest(max_age)


def _handle_dev_event(payload: dict) -> None:
    """
    Persist a file dev-event (open/save/create/delete) from the VS Code extension.
    """
    try:
        from core.project_association import resolve_project
        from database.dev_store import save_file_change, create_dev_tables

        file_path = payload.get("file_path") or ""
        workspace_path = payload.get("workspace_path")
        project_path = workspace_path or resolve_project(file_path, use_git=False)

        ts = payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")
        record = {
            "timestamp": ts,
            "event_type": payload.get("event_type", "file_opened"),
            "project_path": project_path,
            "file_path": file_path,
            "file_name": Path(file_path).name if file_path else None,
            "capture_note": "Reported by VS Code extension (metadata only)",
        }
        create_dev_tables()
        save_file_change(record)
    except Exception:
        pass  # Never crash the receiver on persistence errors


class _RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/v1/context":
            self._handle_context()
        elif self.path == "/v1/dev-event":
            self._handle_dev_event_request()
        else:
            self.send_error(404)

    def _handle_context(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8192:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        update_latest_context(payload)
        self.send_response(204)
        self.end_headers()

    def _handle_dev_event_request(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 16384:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        clean = {k: v for k, v in payload.items() if k in _DEV_EVENT_FIELDS}
        _handle_dev_event(clean)
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format, *_args):
        """Do not write normal extension traffic to the terminal."""


def start_server_in_background(port: int = DEFAULT_PORT) -> None:
    global _server_started
    if _server_started:
        return
    server = ThreadingHTTPServer(("127.0.0.1", port), _RequestHandler)
    threading.Thread(target=server.serve_forever, name="vscode-context-server", daemon=True).start()
    _server_started = True
