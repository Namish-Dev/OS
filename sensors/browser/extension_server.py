"""
Personal OS — Local Extension Server.

A tiny local HTTP server that the Personal OS browser extension pushes
active-tab data to, whenever the user switches tabs or windows in any
Chromium-based browser (Chrome, Brave, Edge, ...).

This exists because the Chrome DevTools Protocol (CDP) only works
against a browser that was launched with --remote-debugging-port,
which the user's normal, everyday browser never is. The extension
approach works against the browser the user is actually using.

This module is platform-independent — it's a plain stdlib HTTP
server and has no Windows/Linux-specific code.

Endpoint:
    POST /tab
        Body (JSON): {"url": "...", "title": "...", "browser": "..."}
        Stores this as the latest known active tab, with a timestamp.

    GET /tab
        Returns the latest known active tab as JSON (mainly for
        manual debugging with a browser or curl).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 9333

# How long a reported tab is considered "fresh" before we treat it
# as stale (e.g. the extension was disabled, or the browser closed).
# Keep the last active-tab report available for heartbeat observations. Tab
# changes are reported immediately by the extension, so this does not merge
# tabs; it only avoids losing URL context between tracker polls.
FRESHNESS_SECONDS = 120.0


class _SharedTabState:
    """Thread-safe holder for the most recently reported active tab."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict | None = None
        self._received_at: float = 0.0

    def update(self, data: dict) -> None:
        with self._lock:
            self._data = data
            self._received_at = time.monotonic()

    def get_if_fresh(self, max_age: float = FRESHNESS_SECONDS) -> dict | None:
        with self._lock:
            if self._data is None:
                return None
            if time.monotonic() - self._received_at > max_age:
                return None
            return dict(self._data)


# Module-level singleton — one server, one shared state, per process.
_state = _SharedTabState()
_server_thread: threading.Thread | None = None
_server: ThreadingHTTPServer | None = None


class _TabRequestHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Silence default stderr request logging.
        pass

    def do_POST(self):
        if self.path != "/tab":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.send_response(400)
            self.end_headers()
            return

        if not isinstance(payload, dict) or "url" not in payload:
            self.send_response(400)
            self.end_headers()
            return

        _state.update(payload)

        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_OPTIONS(self):
        # Browser extensions issue a CORS preflight before POST.
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path != "/tab":
            self.send_response(404)
            self.end_headers()
            return

        data = _state.get_if_fresh() or {}
        body = json.dumps(data).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def start_server_in_background(port: int = DEFAULT_PORT) -> None:
    """
    Start the local extension server on a background daemon thread,
    if it isn't already running. Safe to call multiple times.
    """

    global _server_thread, _server

    if _server_thread is not None and _server_thread.is_alive():
        return

    _server = ThreadingHTTPServer(("127.0.0.1", port), _TabRequestHandler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def get_latest_tab_data(max_age: float = FRESHNESS_SECONDS) -> dict | None:
    """
    Return the most recently reported tab, if it was reported within
    `max_age` seconds. Returns None if nothing fresh is available —
    callers should fall back to CDP or page-title-only in that case.
    """

    return _state.get_if_fresh(max_age)
