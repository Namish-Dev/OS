"""Local receiver for minimal VS Code extension context."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8766
FRESHNESS_SECONDS = 90
_ALLOWED_FIELDS = {"workspace_path", "workspace", "file_path", "language"}


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


class _RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/context":
            self.send_error(404)
            return
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

    def log_message(self, _format, *_args):
        """Do not write normal extension traffic to the terminal."""


def start_server_in_background(port: int = DEFAULT_PORT) -> None:
    global _server_started
    if _server_started:
        return
    server = ThreadingHTTPServer(("127.0.0.1", port), _RequestHandler)
    threading.Thread(target=server.serve_forever, name="vscode-context-server", daemon=True).start()
    _server_started = True
