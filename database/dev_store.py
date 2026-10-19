"""
Personal OS — Development Database Tables.

Adds three new tables for Git-independent work tracking:
  - dev_file_changes:    File-level change records (create/modify/delete/rename)
  - dev_snapshots:       Deduplicated content snapshots indexed by SHA-256 hash
  - dev_terminal_events: Terminal command executions with output and exit codes

All tables use safe ALTER TABLE migrations, preserving existing data.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from database.database import get_connection, DATABASE_PATH, _migrate_add_column


# ──────────────────────────────────────────────────────────────────────────────
# Schema creation
# ──────────────────────────────────────────────────────────────────────────────

def create_dev_tables(database_path: Path | str | None = None) -> None:
    """Create (or migrate) the development evidence tables.
    
    Also ensures the base activity_events and activity_context tables exist,
    so this function can be called standalone on a fresh database.
    """
    from database.database import create_database
    create_database(database_path)
    conn = get_connection(database_path)
    cur = conn.cursor()

    # ── File-change events ──────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_file_changes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT    NOT NULL,
            event_type   TEXT    NOT NULL,   -- 'created'|'modified'|'deleted'|'renamed'
            project_path TEXT,               -- resolved project root, if known
            file_path    TEXT    NOT NULL,   -- absolute path
            file_name    TEXT,               -- basename
            old_path     TEXT,               -- set on rename
            content_hash TEXT,               -- SHA-256 of file bytes at capture time
            diff_text    TEXT,               -- unified diff vs previous snapshot
            is_binary    INTEGER DEFAULT 0,
            is_sensitive INTEGER DEFAULT 0,
            capture_note TEXT                -- e.g. 'file too large', 'binary skipped'
        )
    """)

    # ── Deduplicated content snapshots ──────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_snapshots (
            content_hash TEXT PRIMARY KEY,   -- SHA-256 hex
            captured_at  TEXT NOT NULL,      -- first time this content was seen
            file_path    TEXT NOT NULL,      -- example path (may not be unique)
            size_bytes   INTEGER,
            content_text TEXT                -- NULL for binary or oversized files
        )
    """)

    # ── Terminal command executions ─────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_terminal_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,   -- when the command completed (or was captured)
            start_time      TEXT,               -- when execution began
            completion_time TEXT,               -- when execution ended
            session_id      TEXT,               -- groups commands within one terminal session
            terminal_host   TEXT,               -- 'VS Code'|'Windows Terminal'|'PowerShell'|…
            shell           TEXT,               -- 'powershell'|'bash'|'cmd'|…
            cwd             TEXT,               -- working directory at execution time
            project_path    TEXT,               -- resolved project root
            command         TEXT    NOT NULL,
            exit_code       INTEGER,            -- NULL = unknown
            output          TEXT,               -- combined stdout+stderr, truncated
            status          TEXT    DEFAULT 'completed',  -- 'completed'|'failed'|'running'|'unknown'
            source          TEXT,               -- 'vscode_extension'|'powershell_hook'|…
            capture_note    TEXT
        )
    """)

    # ── Indexes ─────────────────────────────────────────────────────────────
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_file_changes_ts ON dev_file_changes(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_file_changes_proj ON dev_file_changes(project_path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_file_changes_path ON dev_file_changes(file_path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_terminal_ts ON dev_terminal_events(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_terminal_proj ON dev_terminal_events(project_path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_terminal_sess ON dev_terminal_events(session_id)")

    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot helpers
# ──────────────────────────────────────────────────────────────────────────────

def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_snapshot(
    content_hash: str,
    file_path: str,
    size_bytes: int,
    content_text: str | None,
    database_path: Path | str | None = None,
) -> None:
    """Insert a snapshot only if the hash is not already stored."""
    conn = get_connection(database_path)
    cur = conn.cursor()
    try:
        from datetime import datetime
        cur.execute(
            "INSERT OR IGNORE INTO dev_snapshots "
            "(content_hash, captured_at, file_path, size_bytes, content_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                content_hash,
                datetime.now().isoformat(timespec="seconds"),
                file_path,
                size_bytes,
                content_text,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_snapshot_text(
    content_hash: str,
    database_path: Path | str | None = None,
) -> str | None:
    """Retrieve stored text content for a hash, or None if not available."""
    conn = get_connection(database_path)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT content_text FROM dev_snapshots WHERE content_hash = ?",
            (content_hash,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# File-change persistence
# ──────────────────────────────────────────────────────────────────────────────

def save_file_change(record: dict, database_path: Path | str | None = None) -> int:
    """
    Persist one file-change record.

    record keys (all optional unless marked *):
        timestamp*       ISO string
        event_type*      'created'|'modified'|'deleted'|'renamed'
        project_path     resolved project root
        file_path*       absolute path to the changed file
        file_name        basename
        old_path         previous path on rename
        content_hash     SHA-256
        diff_text        unified diff
        is_binary        bool
        is_sensitive     bool
        capture_note     str
    """
    conn = get_connection(database_path)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO dev_file_changes
            (timestamp, event_type, project_path, file_path, file_name,
             old_path, content_hash, diff_text, is_binary, is_sensitive, capture_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("timestamp"),
                record.get("event_type"),
                record.get("project_path"),
                record.get("file_path"),
                record.get("file_name"),
                record.get("old_path"),
                record.get("content_hash"),
                record.get("diff_text"),
                int(bool(record.get("is_binary"))),
                int(bool(record.get("is_sensitive"))),
                record.get("capture_note"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Terminal event persistence
# ──────────────────────────────────────────────────────────────────────────────

def save_terminal_event(record: dict, database_path: Path | str | None = None) -> int:
    """
    Persist one terminal command execution.

    record keys (all optional unless marked *):
        timestamp*       ISO string (completion time, or capture time)
        start_time       ISO string
        completion_time  ISO string
        session_id       str
        terminal_host    str
        shell            str
        cwd*             working directory
        project_path     resolved project root
        command*         command text
        exit_code        int | None
        output           str (already truncated/redacted)
        status           'completed'|'failed'|'running'|'unknown'
        source           capture source
        capture_note     str
    """
    conn = get_connection(database_path)
    cur = conn.cursor()
    try:
        status = record.get("status") or (
            "failed" if (record.get("exit_code") is not None and record.get("exit_code") != 0)
            else "completed" if record.get("exit_code") == 0
            else "unknown"
        )
        cur.execute(
            """
            INSERT INTO dev_terminal_events
            (timestamp, start_time, completion_time, session_id,
             terminal_host, shell, cwd, project_path, command,
             exit_code, output, status, source, capture_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("timestamp"),
                record.get("start_time"),
                record.get("completion_time"),
                record.get("session_id"),
                record.get("terminal_host"),
                record.get("shell"),
                record.get("cwd"),
                record.get("project_path"),
                record.get("command"),
                record.get("exit_code"),
                record.get("output"),
                status,
                record.get("source"),
                record.get("capture_note"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_file_changes(
    project_path: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int | None = None,
    database_path: Path | str | None = None,
) -> list[dict]:
    """Return file-change records, optionally filtered by project and time."""
    conn = get_connection(database_path)
    cur = conn.cursor()
    try:
        conditions, params = [], []
        if project_path:
            conditions.append("project_path = ?")
            params.append(project_path)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        lim = f"LIMIT {int(limit)}" if limit else ""
        cur.execute(
            f"SELECT * FROM dev_file_changes {where} ORDER BY timestamp ASC, id ASC {lim}",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_terminal_events(
    project_path: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int | None = None,
    database_path: Path | str | None = None,
) -> list[dict]:
    """Return terminal-event records, optionally filtered by project and time."""
    conn = get_connection(database_path)
    cur = conn.cursor()
    try:
        conditions, params = [], []
        if project_path:
            conditions.append("project_path = ?")
            params.append(project_path)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        lim = f"LIMIT {int(limit)}" if limit else ""
        cur.execute(
            f"SELECT * FROM dev_terminal_events {where} ORDER BY timestamp ASC, id ASC {lim}",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()
