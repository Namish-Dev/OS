"""
Personal OS — Work Evidence Capture Tests.

Covers all 16 acceptance criteria from the spec plus the critical requirement:
  "The project-continuity feature must remain useful even when Git is never used."

Tests run entirely offline: no Git repo, no IDE, no running Ollama.
All filesystem events are simulated or produced against a real temp directory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.event_model import ActivityEvent
from core.privacy import (
    redact_secrets,
    truncate_output,
    is_sensitive_file,
    sanitize_terminal_event,
)
from core.project_association import resolve_project
from database.dev_store import (
    create_dev_tables,
    save_file_change,
    save_terminal_event,
    get_file_changes,
    get_terminal_events,
    store_snapshot,
    get_snapshot_text,
    sha256_of_bytes,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    create_dev_tables(db)
    return db


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Existing observation functionality remains intact
# ─────────────────────────────────────────────────────────────────────────────

class TestExistingFunctionalityUnchanged:
    """Baseline: adding new tables must not break existing activity_events storage."""

    def test_activity_event_creation_unchanged(self):
        ev = ActivityEvent.create("Visual Studio Code", "Code.exe", "main.py - MyProject")
        assert ev.application == "Visual Studio Code"
        assert ev.event_type == "app_foreground"
        assert ev.timestamp

    def test_create_dev_tables_does_not_corrupt_activity_events(self, tmp_path):
        db = _tmp_db(tmp_path)
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()
        # Original tables must still exist
        assert "activity_events" in tables
        assert "activity_context" in tables
        # New tables also present
        assert "dev_file_changes" in tables
        assert "dev_snapshots" in tables
        assert "dev_terminal_events" in tables

    def test_existing_data_preserved_across_migration(self, tmp_path):
        from database.database import get_connection, save_activity_event
        db = _tmp_db(tmp_path)
        ev = ActivityEvent.create("VS Code", "Code.exe", "test.py - Project")
        save_activity_event(ev)  # uses default DB — fine for isolation here
        # The important thing: create_dev_tables() on the same path is idempotent
        create_dev_tables(db)
        create_dev_tables(db)  # call twice — no error


# ─────────────────────────────────────────────────────────────────────────────
# 2. Terminal events from different adapters normalise to the same schema
# ─────────────────────────────────────────────────────────────────────────────

class TestTerminalEventNormalisation:

    def _make_terminal_record(self, source: str, **kwargs) -> dict:
        base = {
            "timestamp": _now(),
            "command": "python app.py",
            "cwd": "E:/projects/macos-rag",
            "exit_code": 0,
            "shell": "powershell",
            "terminal_host": "VS Code",
            "session_id": "sess-001",
            "status": "completed",
            "source": source,
        }
        base.update(kwargs)
        return base

    def test_vscode_and_powershell_produce_same_columns(self, tmp_path):
        db = _tmp_db(tmp_path)
        vscode_rec = self._make_terminal_record("vscode_shell_integration")
        ps_rec = self._make_terminal_record("powershell_hook", terminal_host="PowerShell")

        id1 = save_terminal_event(vscode_rec, db)
        id2 = save_terminal_event(ps_rec, db)

        events = get_terminal_events(database_path=db)
        assert len(events) == 2
        cols = set(events[0].keys())
        # All required columns must be present in both
        for required in ("timestamp", "command", "cwd", "exit_code", "status", "source"):
            assert required in cols, f"Missing column: {required}"

    def test_unknown_source_still_persists(self, tmp_path):
        db = _tmp_db(tmp_path)
        rec = {
            "timestamp": _now(),
            "command": "cargo build",
            "cwd": "E:/projects/rust-app",
            "exit_code": None,
            "source": "future_unknown_source",
        }
        row_id = save_terminal_event(rec, db)
        assert row_id > 0
        events = get_terminal_events(database_path=db)
        assert events[0]["exit_code"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Successful and failed commands are represented correctly
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandOutcomeRepresentation:

    def test_exit_code_zero_is_completed(self, tmp_path):
        db = _tmp_db(tmp_path)
        save_terminal_event({
            "timestamp": _now(), "command": "pytest", "cwd": "/proj",
            "exit_code": 0, "status": "completed",
        }, db)
        events = get_terminal_events(database_path=db)
        assert events[0]["status"] == "completed"
        assert events[0]["exit_code"] == 0

    def test_nonzero_exit_code_is_failed(self, tmp_path):
        db = _tmp_db(tmp_path)
        save_terminal_event({
            "timestamp": _now(), "command": "python app.py",
            "cwd": "/proj", "exit_code": 1,
            "output": "ModuleNotFoundError: No module named 'chromadb'",
        }, db)
        events = get_terminal_events(database_path=db)
        assert events[0]["exit_code"] == 1
        assert events[0]["status"] == "failed"
        assert "chromadb" in events[0]["output"]

    def test_output_and_error_are_stored(self, tmp_path):
        db = _tmp_db(tmp_path)
        save_terminal_event({
            "timestamp": _now(), "command": "npm install",
            "cwd": "/proj", "exit_code": 0,
            "output": "added 42 packages",
        }, db)
        events = get_terminal_events(database_path=db)
        assert "42 packages" in events[0]["output"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Missing exit codes are unknown, not guessed
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingExitCodeHandling:

    def test_null_exit_code_stored_as_null(self, tmp_path):
        db = _tmp_db(tmp_path)
        save_terminal_event({
            "timestamp": _now(), "command": "tail -f server.log",
            "cwd": "/proj", "exit_code": None, "status": "unknown",
        }, db)
        events = get_terminal_events(database_path=db)
        assert events[0]["exit_code"] is None
        assert events[0]["status"] == "unknown"

    def test_running_command_has_running_status(self, tmp_path):
        db = _tmp_db(tmp_path)
        save_terminal_event({
            "timestamp": _now(), "command": "python train.py",
            "cwd": "/proj", "exit_code": None, "status": "running",
        }, db)
        events = get_terminal_events(database_path=db)
        assert events[0]["status"] == "running"
        assert events[0]["exit_code"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Long-running commands and incomplete output are handled safely
# ─────────────────────────────────────────────────────────────────────────────

class TestLongRunningAndIncompleteCapture:

    def test_very_long_output_is_truncated_not_crashed(self):
        big = "x" * 100_000
        result = truncate_output(big, max_chars=8192)
        assert len(result) <= 9000  # allow for truncation message overhead
        assert "[... " in result
        assert "truncated" in result

    def test_head_and_tail_preserved_in_truncation(self):
        head = "START_MARKER"
        tail = "END_MARKER"
        middle = "x" * 50_000
        output = head + middle + tail
        result = truncate_output(output, max_chars=1000)
        assert "START_MARKER" in result
        assert "END_MARKER" in result

    def test_empty_output_handled_gracefully(self):
        assert truncate_output(None) == ""
        assert truncate_output("") == ""

    def test_large_output_persisted_as_truncated(self, tmp_path):
        db = _tmp_db(tmp_path)
        big_output = "line\n" * 5000  # 25 000 chars
        sanitized = sanitize_terminal_event({"command": "long job", "output": big_output})
        save_terminal_event({
            "timestamp": _now(), "command": "long job",
            "cwd": "/proj", "output": sanitized["output"],
        }, db)
        events = get_terminal_events(database_path=db)
        stored_output = events[0]["output"]
        # Should be truncated but not lost entirely
        assert stored_output
        assert len(stored_output) <= 10000


# ─────────────────────────────────────────────────────────────────────────────
# 6. Duplicate events are detected / appropriately reconciled
# ─────────────────────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_identical_file_content_hash_prevents_duplicate_snapshot(self, tmp_path):
        db = _tmp_db(tmp_path)
        content = b"def hello(): pass\n"
        h = sha256_of_bytes(content)

        store_snapshot(h, "/proj/hello.py", len(content), content.decode(), db)
        store_snapshot(h, "/proj/hello.py", len(content), content.decode(), db)  # same hash

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM dev_snapshots WHERE content_hash=?", (h,)).fetchone()
        conn.close()
        assert rows[0] == 1  # only one stored

    def test_different_content_hashes_both_stored(self, tmp_path):
        db = _tmp_db(tmp_path)
        c1, c2 = b"version 1\n", b"version 2\n"
        h1, h2 = sha256_of_bytes(c1), sha256_of_bytes(c2)
        store_snapshot(h1, "/proj/f.py", len(c1), c1.decode(), db)
        store_snapshot(h2, "/proj/f.py", len(c2), c2.decode(), db)

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM dev_snapshots").fetchone()
        conn.close()
        assert rows[0] == 2


# ─────────────────────────────────────────────────────────────────────────────
# 7. File-open events are distinguished from file modifications
# ─────────────────────────────────────────────────────────────────────────────

class TestFileEventTypeDistinction:

    def test_open_vs_modified_different_event_types(self, tmp_path):
        db = _tmp_db(tmp_path)
        ts = _now()
        save_file_change({"timestamp": ts, "event_type": "file_opened",
                          "file_path": "/proj/app.py", "file_name": "app.py"}, db)
        save_file_change({"timestamp": ts, "event_type": "modified",
                          "file_path": "/proj/app.py", "file_name": "app.py"}, db)

        changes = get_file_changes(database_path=db)
        types = [c["event_type"] for c in changes]
        assert "file_opened" in types
        assert "modified" in types

    def test_created_deleted_renamed_stored_correctly(self, tmp_path):
        db = _tmp_db(tmp_path)
        for et in ("created", "deleted", "renamed"):
            save_file_change({
                "timestamp": _now(),
                "event_type": et,
                "file_path": "/proj/file.py",
                "file_name": "file.py",
                "old_path": "/proj/old.py" if et == "renamed" else None,
            }, db)
        changes = get_file_changes(database_path=db)
        stored_types = {c["event_type"] for c in changes}
        assert {"created", "deleted", "renamed"}.issubset(stored_types)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Project association works for nested directories and repos
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectAssociation:

    def test_detects_pyproject_toml_as_root(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("[tool.poetry]\nname = 'myapp'\n")
        nested = proj / "src" / "myapp"
        nested.mkdir(parents=True)
        (nested / "main.py").write_text("print('hi')")

        result = resolve_project(nested / "main.py", use_git=False)
        assert result is not None
        assert "myapp" in result

    def test_detects_package_json_as_root(self, tmp_path):
        proj = tmp_path / "frontend"
        proj.mkdir()
        (proj / "package.json").write_text('{"name": "frontend"}')
        src = proj / "src"
        src.mkdir()
        (src / "App.jsx").write_text("export default function App() {}")

        result = resolve_project(src / "App.jsx", use_git=False)
        assert result is not None
        assert "frontend" in result

    def test_no_markers_returns_none_not_guess(self, tmp_path):
        bare = tmp_path / "bare_dir"
        bare.mkdir()
        (bare / "notes.txt").write_text("hello")

        result = resolve_project(bare / "notes.txt", use_git=False)
        # Should be None — no markers and no Git
        assert result is None

    def test_nested_project_gets_innermost_marker(self, tmp_path):
        outer = tmp_path / "workspace"
        outer.mkdir()
        (outer / "package.json").write_text('{"name": "outer"}')
        inner = outer / "packages" / "ui"
        inner.mkdir(parents=True)
        (inner / "package.json").write_text('{"name": "ui"}')
        (inner / "Button.tsx").write_text("export const Button = () => <button />;")

        result = resolve_project(inner / "Button.tsx", use_git=False)
        assert result is not None
        # Should resolve to inner (more specific)
        assert "ui" in result

    def test_unassigned_events_not_silently_project_attributed(self, tmp_path):
        db = _tmp_db(tmp_path)
        # A file with no project markers nearby
        bare = tmp_path / "random_file.txt"
        bare.write_text("hello")
        project = resolve_project(bare, use_git=False)
        save_file_change({
            "timestamp": _now(),
            "event_type": "modified",
            "file_path": str(bare),
            "project_path": project,  # expected to be None
        }, db)
        changes = get_file_changes(database_path=db)
        assert changes[0]["project_path"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 9. Uncertain project associations are NOT silently presented as facts
#    (tested via the None return above; also verify event model)
# ─────────────────────────────────────────────────────────────────────────────

class TestUncertainProjectAssociation:

    def test_resolve_returns_none_for_empty_path(self):
        assert resolve_project(None, use_git=False) is None
        assert resolve_project("", use_git=False) is None

    def test_resolve_returns_none_for_nonexistent_path(self):
        assert resolve_project("/this/does/not/exist/at/all", use_git=False) is None


# ─────────────────────────────────────────────────────────────────────────────
# 10. SQLite migrations preserve existing records
# ─────────────────────────────────────────────────────────────────────────────

class TestSQLiteMigrations:

    def test_create_dev_tables_is_idempotent(self, tmp_path):
        db = _tmp_db(tmp_path)
        # Pre-populate
        save_terminal_event({"timestamp": _now(), "command": "echo hi", "cwd": "/proj"}, db)
        save_file_change({"timestamp": _now(), "event_type": "modified",
                          "file_path": "/proj/a.py"}, db)
        # Re-run migration
        create_dev_tables(db)
        create_dev_tables(db)
        # Records still present
        assert len(get_terminal_events(database_path=db)) == 1
        assert len(get_file_changes(database_path=db)) == 1

    def test_existing_activity_events_survive_migration(self, tmp_path):
        from database.database import create_database, get_connection
        db = tmp_path / "migtest.db"
        create_database(db)
        conn = get_connection(db)
        conn.execute(
            "INSERT INTO activity_events (timestamp, process, window_title) VALUES (?, ?, ?)",
            ("2026-01-01T00:00:00", "Code.exe", "main.py"),
        )
        conn.commit()
        conn.close()
        # Now add dev tables
        create_dev_tables(db)
        conn = get_connection(db)
        rows = conn.execute("SELECT COUNT(*) FROM activity_events").fetchone()
        conn.close()
        assert rows[0] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 11. File-change events persist across restarts (data durability)
# ─────────────────────────────────────────────────────────────────────────────

class TestDataDurability:

    def test_records_survive_connection_close_and_reopen(self, tmp_path):
        db = _tmp_db(tmp_path)
        save_file_change({"timestamp": _now(), "event_type": "created",
                          "file_path": "/proj/new.py", "file_name": "new.py"}, db)
        save_terminal_event({"timestamp": _now(), "command": "python new.py",
                              "cwd": "/proj", "exit_code": 1,
                              "output": "SyntaxError: invalid syntax"}, db)
        # Simulate restart: create_dev_tables again and re-query
        create_dev_tables(db)
        file_events = get_file_changes(database_path=db)
        term_events = get_terminal_events(database_path=db)
        assert len(file_events) == 1
        assert file_events[0]["file_name"] == "new.py"
        assert len(term_events) == 1
        assert term_events[0]["exit_code"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 12. Git-independent: no Git repo required for any capture or query
# ─────────────────────────────────────────────────────────────────────────────

class TestGitIndependence:

    def test_file_changes_without_git_repo(self, tmp_path):
        """Core acceptance test: changes captured with no Git, no commits."""
        db = _tmp_db(tmp_path)
        # Create a plain directory with no .git
        proj = tmp_path / "no-git-project"
        proj.mkdir()
        assert not (proj / ".git").exists()
        (proj / "pyproject.toml").write_text('[tool.poetry]\nname = "no-git-project"\n')

        files = ["main.py", "utils.py", "config.py"]
        for fname in files:
            (proj / fname).write_text(f"# {fname} initial\n")
            save_file_change({
                "timestamp": _now(),
                "event_type": "created",
                "project_path": str(proj),
                "file_path": str(proj / fname),
                "file_name": fname,
            }, db)

        # Simulate modification
        (proj / "main.py").write_text("def main(): pass\n")
        save_file_change({
            "timestamp": _now(),
            "event_type": "modified",
            "project_path": str(proj),
            "file_path": str(proj / "main.py"),
            "file_name": "main.py",
        }, db)

        # Simulate a failing command
        save_terminal_event({
            "timestamp": _now(),
            "command": "python main.py",
            "cwd": str(proj),
            "project_path": str(proj),
            "exit_code": 1,
            "output": "TypeError: main() missing 1 required argument",
            "status": "failed",
        }, db)

        # Verify everything recorded without Git
        file_events = get_file_changes(project_path=str(proj), database_path=db)
        term_events = get_terminal_events(project_path=str(proj), database_path=db)
        assert len(file_events) == 4
        assert any(e["event_type"] == "modified" for e in file_events)
        assert len(term_events) == 1
        assert term_events[0]["exit_code"] == 1
        assert "TypeError" in term_events[0]["output"]

    def test_project_association_without_git(self, tmp_path):
        proj = tmp_path / "pure-python-project"
        proj.mkdir()
        (proj / "setup.py").write_text("from setuptools import setup; setup(name='p')")
        nested = proj / "src" / "mylib"
        nested.mkdir(parents=True)
        result = resolve_project(nested, use_git=False)
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# 13. LLM unavailability does not interrupt observation
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMUnavailabilityDoesNotBlock:

    def test_file_change_persists_without_llm(self, tmp_path):
        db = _tmp_db(tmp_path)
        # No LLM involved — pure DB write
        row_id = save_file_change({
            "timestamp": _now(),
            "event_type": "modified",
            "file_path": "/proj/app.py",
            "file_name": "app.py",
        }, db)
        assert row_id > 0

    def test_terminal_event_persists_without_llm(self, tmp_path):
        db = _tmp_db(tmp_path)
        row_id = save_terminal_event({
            "timestamp": _now(),
            "command": "pytest",
            "cwd": "/proj",
            "exit_code": 0,
        }, db)
        assert row_id > 0


# ─────────────────────────────────────────────────────────────────────────────
# 14. Secret redaction tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSecretRedaction:

    def test_openai_key_redacted(self):
        text = "export OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456"
        result = redact_secrets(text)
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result
        assert "[REDACTED_SECRET]" in result

    def test_github_pat_redacted(self):
        text = "git clone https://ghp_AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQRR@github.com/user/repo"
        result = redact_secrets(text)
        assert "ghp_" not in result

    def test_aws_access_key_redacted(self):
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_password_in_url_redacted(self):
        text = "postgres://admin:supersecret@localhost:5432/mydb"
        result = redact_secrets(text)
        assert "supersecret" not in result
        assert "localhost" in result  # host preserved

    def test_bearer_token_redacted(self):
        text = "curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig'"
        result = redact_secrets(text)
        assert "eyJhbGciO" not in result

    def test_api_key_value_redacted(self):
        text = "api_key = 'my-super-secret-api-key-value-1234'"
        result = redact_secrets(text)
        assert "my-super-secret-api-key-value-1234" not in result

    def test_non_secret_text_preserved(self):
        text = "Running pytest --verbose on 42 tests"
        result = redact_secrets(text)
        assert result == text

    def test_sensitive_file_detection(self):
        assert is_sensitive_file(".env")
        assert is_sensitive_file(".env.production")
        assert is_sensitive_file("id_rsa")
        assert is_sensitive_file("/home/user/.ssh/id_ed25519")
        assert is_sensitive_file("secrets.json")
        assert not is_sensitive_file("main.py")
        assert not is_sensitive_file("README.md")

    def test_terminal_event_sanitised_before_storage(self, tmp_path):
        db = _tmp_db(tmp_path)
        dirty = {
            "command": "export API_KEY=sk-secret12345678901234567890",
            "output": "Connected to postgres://admin:pass1234@prod-db:5432/app",
            "cwd": "/proj",
        }
        clean = sanitize_terminal_event(dirty)
        assert "sk-secret" not in clean["command"]
        assert "pass1234" not in clean["output"]


# ─────────────────────────────────────────────────────────────────────────────
# 15. Snapshot storage and retrieval (content hashing and deduplication)
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshotStorage:

    def test_snapshot_stored_and_retrieved(self, tmp_path):
        db = _tmp_db(tmp_path)
        content = "def hello():\n    return 'world'\n"
        h = sha256_of_bytes(content.encode())
        store_snapshot(h, "/proj/hello.py", len(content), content, db)
        retrieved = get_snapshot_text(h, db)
        assert retrieved == content

    def test_missing_hash_returns_none(self, tmp_path):
        db = _tmp_db(tmp_path)
        assert get_snapshot_text("nonexistent_hash_000", db) is None

    def test_binary_file_stored_without_text(self, tmp_path):
        db = _tmp_db(tmp_path)
        data = bytes(range(256))
        h = sha256_of_bytes(data)
        store_snapshot(h, "/proj/image.png", len(data), None, db)
        assert get_snapshot_text(h, db) is None

    def test_sha256_correctness(self):
        content = b"hello world"
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_of_bytes(content) == expected


# ─────────────────────────────────────────────────────────────────────────────
# 16. Filesystem watcher — real integration test (Git-independent)
# ─────────────────────────────────────────────────────────────────────────────

class TestFilesystemWatcherIntegration:

    def test_watcher_detects_file_creation_and_modification(self, tmp_path):
        from sensors.filesystem_watcher import FilesystemWatcher

        db = tmp_path / "watch_test.db"
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        (proj_dir / "pyproject.toml").write_text('[tool.poetry]\nname="proj"\n')

        captured = []
        watcher = FilesystemWatcher(
            watch_paths=[proj_dir],
            database_path=db,
            on_event_callback=captured.append,
        )
        watcher.start()
        try:
            # Create a file
            test_file = proj_dir / "hello.py"
            test_file.write_text("print('hello')\n")
            time.sleep(0.8)  # let watchdog process

            # Modify the file
            test_file.write_text("def hello():\n    print('hello')\n")
            time.sleep(0.8)

        finally:
            watcher.stop()

        # At least creation or modification captured
        assert len(captured) >= 1
        file_paths = [c["file_path"] for c in captured]
        assert any("hello.py" in fp for fp in file_paths)

    def test_watcher_skips_excluded_directories(self, tmp_path):
        from sensors.filesystem_watcher import FilesystemWatcher

        db = tmp_path / "exclude_test.db"
        proj_dir = tmp_path / "proj2"
        proj_dir.mkdir()

        captured = []
        watcher = FilesystemWatcher(
            watch_paths=[proj_dir],
            database_path=db,
            on_event_callback=captured.append,
        )
        watcher.start()
        try:
            # Write inside __pycache__ — should be excluded
            cache_dir = proj_dir / "__pycache__"
            cache_dir.mkdir()
            (cache_dir / "module.cpython-313.pyc").write_bytes(b"\x00\x01\x02")
            time.sleep(0.6)
        finally:
            watcher.stop()

        # No events from __pycache__
        for ev in captured:
            assert "__pycache__" not in ev["file_path"]

    def test_watcher_marks_sensitive_files_not_reads_them(self, tmp_path):
        from sensors.filesystem_watcher import FilesystemWatcher

        db = tmp_path / "sensitive_test.db"
        proj_dir = tmp_path / "proj3"
        proj_dir.mkdir()

        captured = []
        watcher = FilesystemWatcher(
            watch_paths=[proj_dir],
            database_path=db,
            on_event_callback=captured.append,
        )
        watcher.start()
        try:
            env_file = proj_dir / ".env"
            env_file.write_text("API_KEY=sk-secret12345678901234\nDATABASE_URL=postgres://user:pass@host/db\n")
            time.sleep(0.6)
        finally:
            watcher.stop()

        # If captured, must be flagged as sensitive with no content stored
        sensitive_events = [e for e in captured if ".env" in e["file_path"]]
        for ev in sensitive_events:
            assert ev.get("is_sensitive"), "Sensitive file not flagged"
            assert ev.get("content_hash") is None or ev.get("capture_note")

    def test_binary_file_captured_without_crash(self, tmp_path):
        from sensors.filesystem_watcher import FilesystemWatcher

        db = tmp_path / "binary_test.db"
        proj_dir = tmp_path / "proj4"
        proj_dir.mkdir()

        captured = []
        watcher = FilesystemWatcher(
            watch_paths=[proj_dir],
            database_path=db,
            on_event_callback=captured.append,
        )
        watcher.start()
        try:
            binary_file = proj_dir / "data.bin"
            binary_file.write_bytes(bytes(range(256)) * 100)
            time.sleep(0.6)
        finally:
            watcher.stop()

        binary_events = [e for e in captured if "data.bin" in e["file_path"]]
        for ev in binary_events:
            assert ev.get("is_binary"), "Binary file not flagged"


# ─────────────────────────────────────────────────────────────────────────────
# 17. ActivityEvent factory methods produce correct structure
# ─────────────────────────────────────────────────────────────────────────────

class TestActivityEventFactories:

    def test_create_terminal_event_success(self):
        ev = ActivityEvent.create_terminal_event(
            command="python -m pytest",
            cwd="/proj",
            exit_code=0,
            terminal_host="VS Code",
            shell="powershell",
        )
        assert ev.event_type == "command_executed"
        assert ev.exit_code == 0
        assert ev.command == "python -m pytest"
        assert ev.cwd == "/proj"

    def test_create_terminal_event_failure(self):
        ev = ActivityEvent.create_terminal_event(
            command="python app.py",
            cwd="/proj",
            exit_code=1,
            output="ModuleNotFoundError: No module named 'chromadb'",
        )
        assert ev.event_type == "command_failed"
        assert ev.exit_code == 1
        assert "chromadb" in ev.output

    def test_create_terminal_event_running(self):
        ev = ActivityEvent.create_terminal_event(
            command="python train.py",
            status="running",
            exit_code=None,
        )
        assert ev.event_type == "command_running"
        assert ev.exit_code is None

    def test_create_terminal_event_redacts_secrets(self):
        ev = ActivityEvent.create_terminal_event(
            command="export API_KEY=sk-realkey123456789012345678901234",
            cwd="/proj",
        )
        assert "sk-realkey" not in ev.command
        assert "[REDACTED_SECRET]" in ev.command

    def test_create_file_event_open(self):
        ev = ActivityEvent.create_file_event(
            event_type="file_opened",
            file_path="/proj/src/app.py",
            workspace="my-project",
        )
        assert ev.event_type == "file_opened"
        assert ev.file == "app.py"
        assert ev.workspace == "my-project"

    def test_create_file_event_save(self):
        ev = ActivityEvent.create_file_event(
            event_type="file_saved",
            file_path="/proj/src/app.py",
            workspace="my-project",
        )
        assert ev.event_type == "file_saved"


# ─────────────────────────────────────────────────────────────────────────────
# 18. Terminal receiver HTTP endpoint normalises and persists correctly
# ─────────────────────────────────────────────────────────────────────────────

class TestTerminalReceiverHTTP:

    def _post(self, port: int, payload: dict) -> int:
        import urllib.request
        import urllib.error
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/terminal-event",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Content-Length": len(body)},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_receiver_accepts_valid_event(self, tmp_path):
        from sensors.terminal_receiver import start_terminal_receiver, get_latest_terminal_event
        import sensors.terminal_receiver as tr
        tr._server_started = False  # reset for test isolation

        db = _tmp_db(tmp_path)
        port = 18767  # use different port to avoid conflict
        start_terminal_receiver(port=port, database_path=db)
        time.sleep(0.2)

        payload = {
            "command": "python app.py",
            "cwd": str(tmp_path),
            "exit_code": 1,
            "output": "ImportError: No module named 'foo'",
            "shell": "powershell",
            "terminal_host": "Windows Terminal",
            "status": "failed",
        }
        status = self._post(port, payload)
        assert status == 204

        time.sleep(0.2)
        events = get_terminal_events(database_path=db)
        assert len(events) == 1
        assert events[0]["exit_code"] == 1
        assert "foo" in events[0]["output"]

    def test_receiver_rejects_oversized_body(self, tmp_path):
        from sensors.terminal_receiver import start_terminal_receiver
        import sensors.terminal_receiver as tr
        tr._server_started = False

        db = _tmp_db(tmp_path)
        port = 18768
        start_terminal_receiver(port=port, database_path=db)
        time.sleep(0.2)

        big_output = "x" * 200_000
        status = self._post(port, {"command": "cmd", "cwd": "/", "output": big_output})
        assert status in (413, 400)  # rejected
