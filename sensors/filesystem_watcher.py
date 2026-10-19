"""
Personal OS — Git-Independent Filesystem Watcher Sensor.

Uses Python's watchdog library to monitor one or more project directories for
file creation, modification, deletion, and renaming.  Git is never required.

For each detected change on an eligible file:
  1. Read the new content (for text files within size limits).
  2. Compute a SHA-256 hash.
  3. If the hash matches the last known hash for that path, skip (no-op).
  4. Otherwise, generate a unified diff vs the previous snapshot and persist:
       a. A snapshot in dev_snapshots (deduplicated by hash).
       b. A record in dev_file_changes.
       c. An ActivityEvent in activity_events for cross-correlation.

Binary files, large files, sensitive files, and excluded directories are
handled per-policy without crashing the watcher.

Designed to survive application shutdown: the SQLite records written here
persist across restarts by design.
"""

from __future__ import annotations

import difflib
import threading
from datetime import datetime
from pathlib import Path

from watchdog.events import (
    FileClosedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from core.privacy import is_sensitive_file, truncate_output, DEFAULT_MAX_DIFF_CHARS
from core.project_association import resolve_project
from database.dev_store import (
    save_file_change,
    sha256_of_bytes,
    store_snapshot,
    get_snapshot_text,
    create_dev_tables,
)

# ──────────────────────────────────────────────────────────────────────────────
# Capture policy constants  (all configurable at construction time)
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_MAX_FILE_BYTES = 512 * 1024        # 512 KB — skip diff for larger files
DEFAULT_MAX_DIFF_CHARS_LOCAL = DEFAULT_MAX_DIFF_CHARS
DEFAULT_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".md", ".rst", ".txt", ".html", ".css", ".scss", ".sass",
    ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".psd1",
    ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".java", ".kt", ".swift",
    ".rb", ".php", ".lua",
    ".sql", ".graphql",
    ".xml", ".csv",
    ".dockerfile", "Dockerfile",
}
_DEFAULT_EXCLUDED_DIRS = {
    "database",
    ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", ".env",
    "node_modules", ".next", "dist", "build", ".dist",
    ".idea", ".vscode", ".vs",
}


class _FileWatcherHandler(FileSystemEventHandler):
    """
    Watchdog event handler that captures file changes with deduplication,
    diffs, and privacy enforcement.
    """

    def __init__(
        self,
        watch_paths: list[str | Path],
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS_LOCAL,
        text_extensions: set[str] | None = None,
        excluded_dirs: set[str] | None = None,
        database_path: Path | str | None = None,
        on_event_callback=None,
    ):
        super().__init__()
        self._watch_paths = [str(Path(p).resolve()) for p in watch_paths]
        self._max_file_bytes = max_file_bytes
        self._max_diff_chars = max_diff_chars
        self._text_extensions = text_extensions or DEFAULT_TEXT_EXTENSIONS
        self._excluded_dirs = excluded_dirs or _DEFAULT_EXCLUDED_DIRS
        self._database_path = database_path
        self._on_event_callback = on_event_callback  # called with record dict
        # path -> last known content_hash (in-memory, rebuilt from DB on restart)
        self._last_hash: dict[str, str] = {}
        self._lock = threading.Lock()

    # ── Watchdog entry points ────────────────────────────────────────────────

    def on_created(self, event):
        if not event.is_directory:
            self._handle("created", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            # on_modified fires both for content changes and metadata (e.g. atime)
            # We deduplicate via content hash, so both are safe to handle.
            self._handle("modified", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._handle("deleted", event.src_path, is_delete=True)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle("renamed", event.dest_path, old_path=event.src_path)

    # ── Core processing ──────────────────────────────────────────────────────

    def _handle(
        self,
        event_type: str,
        file_path: str,
        old_path: str | None = None,
        is_delete: bool = False,
    ) -> dict | None:
        """Process one filesystem event and return the persisted record (or None)."""
        path = Path(file_path)

        if self._is_excluded(path):
            return None

        # Resolve project
        project_path = resolve_project(path, use_git=True)
        now = datetime.now().isoformat(timespec="seconds")

        record: dict = {
            "timestamp": now,
            "event_type": event_type,
            "project_path": project_path,
            "file_path": str(path),
            "file_name": path.name,
            "old_path": old_path,
            "is_binary": False,
            "is_sensitive": False,
            "content_hash": None,
            "diff_text": None,
            "capture_note": None,
        }

        if is_delete:
            with self._lock:
                self._last_hash.pop(str(path), None)
            save_file_change(record, self._database_path)
            self._fire_callback(record)
            return record

        if is_sensitive_file(path):
            record["is_sensitive"] = True
            record["capture_note"] = "Sensitive file — content not captured"
            save_file_change(record, self._database_path)
            self._fire_callback(record)
            return record

        # Try to read the file
        try:
            raw_bytes = path.read_bytes()
        except (OSError, PermissionError) as exc:
            record["capture_note"] = f"Read error: {exc}"
            save_file_change(record, self._database_path)
            self._fire_callback(record)
            return record

        size = len(raw_bytes)
        content_hash = sha256_of_bytes(raw_bytes)

        # Deduplication: if hash unchanged since last capture, skip
        with self._lock:
            if self._last_hash.get(str(path)) == content_hash:
                return None  # truly no change
            self._last_hash[str(path)] = content_hash

        record["content_hash"] = content_hash

        # Binary / oversized detection
        is_text = self._is_text_file(path, raw_bytes, size)
        record["is_binary"] = not is_text

        if not is_text:
            record["capture_note"] = (
                f"File size {size} bytes exceeds limit" if size > self._max_file_bytes
                else "Binary file — content not captured"
            )
            save_file_change(record, self._database_path)
            # Still store a snapshot by hash so we know the file existed
            store_snapshot(content_hash, str(path), size, None, self._database_path)
            self._fire_callback(record)
            return record

        # Text file — decode and diff
        try:
            content_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            content_text = None

        # Store deduplicated snapshot
        store_snapshot(content_hash, str(path), size, content_text, self._database_path)

        # Generate unified diff against previous snapshot
        if content_text is not None:
            record["diff_text"] = self._generate_diff(str(path), content_text)

        save_file_change(record, self._database_path)
        self._fire_callback(record)
        return record

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _is_excluded(self, path: Path) -> bool:
        """True if the path is inside an excluded directory."""
        for part in path.parts:
            if part in self._excluded_dirs:
                return True
        if is_sensitive_file(path):
            return False  # let _handle record it as sensitive but not fully exclude
        return False

    def _is_text_file(self, path: Path, raw_bytes: bytes, size: int) -> bool:
        """Heuristic: check extension and absence of null bytes."""
        if size > self._max_file_bytes:
            return False
        suffix = path.suffix.lower()
        if suffix in self._text_extensions or path.name in self._text_extensions:
            return True
        # No extension hint — check for null bytes (binary indicator)
        if b"\x00" in raw_bytes[:8192]:
            return False
        return True  # assume text if no null bytes found

    def _generate_diff(self, file_path: str, current_text: str) -> str | None:
        """Generate a unified diff between the previous snapshot and current content."""
        # Find the previous snapshot text for this path from last known hash
        with self._lock:
            prev_hashes = [
                h for p, h in self._last_hash.items()
                if p == file_path
            ]
        # self._last_hash already updated to current before we get here
        # so we need the *previous* hash; we get it from the DB via prior record
        from database.dev_store import get_file_changes
        prev_records = get_file_changes(
            database_path=self._database_path
        )
        prev_hash: str | None = None
        for r in reversed(prev_records):
            if r.get("file_path") == file_path and r.get("content_hash") and r.get("content_hash") != self._last_hash.get(file_path):
                prev_hash = r["content_hash"]
                break

        prev_text: str = ""
        if prev_hash:
            stored = get_snapshot_text(prev_hash, self._database_path)
            if stored is not None:
                prev_text = stored

        diff_lines = list(
            difflib.unified_diff(
                prev_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile=f"a/{Path(file_path).name}",
                tofile=f"b/{Path(file_path).name}",
                lineterm="",
            )
        )
        if not diff_lines:
            return None
        diff_text = "".join(diff_lines)
        return truncate_output(diff_text, self._max_diff_chars)

    def _fire_callback(self, record: dict) -> None:
        if self._on_event_callback:
            try:
                self._on_event_callback(record)
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

class FilesystemWatcher:
    """
    Manages watchdog observers for one or more project directories.

    Usage:
        watcher = FilesystemWatcher(watch_paths=["E:/projects/my-app"])
        watcher.start()
        # ... runs in background threads
        watcher.stop()
    """

    def __init__(
        self,
        watch_paths: list[str | Path],
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS_LOCAL,
        text_extensions: set[str] | None = None,
        excluded_dirs: set[str] | None = None,
        database_path: Path | str | None = None,
        on_event_callback=None,
    ):
        create_dev_tables(database_path)
        self._watch_paths = [str(Path(p).resolve()) for p in watch_paths]
        self._handler = _FileWatcherHandler(
            watch_paths=watch_paths,
            max_file_bytes=max_file_bytes,
            max_diff_chars=max_diff_chars,
            text_extensions=text_extensions,
            excluded_dirs=excluded_dirs,
            database_path=database_path,
            on_event_callback=on_event_callback,
        )
        self._observer = Observer()
        self._started = False

    def start(self) -> None:
        """Start watching all configured paths in background threads."""
        if self._started:
            return
        for path in self._watch_paths:
            if Path(path).exists():
                self._observer.schedule(self._handler, path, recursive=True)
        self._observer.start()
        self._started = True

    def stop(self) -> None:
        """Stop all observers cleanly."""
        if not self._started:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._started = False

    def add_path(self, path: str | Path) -> None:
        """Add a new directory to watch at runtime."""
        resolved = str(Path(path).resolve())
        if resolved not in self._watch_paths and Path(resolved).exists():
            self._watch_paths.append(resolved)
            self._observer.schedule(self._handler, resolved, recursive=True)

    @property
    def is_running(self) -> bool:
        return self._started and self._observer.is_alive()
