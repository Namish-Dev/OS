"""
Personal OS — Central Database.

There is exactly ONE database: database/personal_os.db

Every module must use get_connection() or DATABASE_PATH from this file.
Do NOT create additional .db files anywhere in the project.
"""

import json
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).parent / "personal_os.db"


_initialized_dbs = set()


def get_connection(database_path: Path | str | None = None) -> sqlite3.Connection:
    """Create and return a connection to the Personal OS database."""
    path = Path(database_path or DATABASE_PATH).resolve()
    if path not in _initialized_dbs and path.exists():
        _initialized_dbs.add(path)
        create_database(path)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def create_database(database_path: Path | str | None = None) -> None:
    """Create the database tables and indexes if they don't already exist."""

    connection = get_connection(database_path)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            process TEXT,
            window_title TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_event_id INTEGER NOT NULL,
            application TEXT,
            workspace TEXT,
            file TEXT,
            note TEXT,
            vault TEXT,
            domain TEXT,
            url TEXT,
            page_title TEXT,
            FOREIGN KEY (activity_event_id)
                REFERENCES activity_events(id)
        )
    """)

    connection.commit()

    # ---------- Safe migrations ----------
    # ALTER TABLE ADD COLUMN is safe — existing rows get NULL or DEFAULT.
    _migrate_add_column(cursor, "activity_events", "application", "TEXT")
    _migrate_add_column(cursor, "activity_events", "event_type", "TEXT DEFAULT 'app_foreground'")
    _migrate_add_column(cursor, "activity_events", "sensor", "TEXT")
    _migrate_add_column(cursor, "activity_events", "pid", "INTEGER")

    _migrate_add_column(cursor, "activity_context", "path", "TEXT")
    _migrate_add_column(cursor, "activity_context", "workspace_path", "TEXT")
    _migrate_add_column(cursor, "activity_context", "file_path", "TEXT")
    _migrate_add_column(cursor, "activity_context", "metadata_json", "TEXT")

    # Indexes for fast chronological lookups and foreign key joins
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_events_timestamp ON activity_events(timestamp)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_context_event_id ON activity_context(activity_event_id)"
    )

    connection.commit()
    connection.close()


def _migrate_add_column(cursor: sqlite3.Cursor, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it doesn't already exist."""

    cursor.execute(f"PRAGMA table_info({table})")
    existing_columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in cursor.fetchall()}

    if column not in existing_columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def save_activity(timestamp: str, process: str | None, window_title: str | None) -> int:
    """
    Save one activity event to the database (legacy interface).
    Preserved for backward compatibility.
    """

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO activity_events
            (timestamp, process, window_title)
            VALUES (?, ?, ?)
        """, (
            timestamp,
            process,
            window_title,
        ))
        event_id = cursor.lastrowid
        connection.commit()
        return event_id
    finally:
        connection.close()


def save_activity_event(event) -> int:
    """
    Save a full ActivityEvent (with context) to the database.

    Inserts into activity_events and, if context is present,
    also inserts into activity_context.

    Args:
        event: An ActivityEvent instance (or dict with event fields).

    Returns:
        The id of the inserted activity_events row.
    """

    data = event.to_dict() if hasattr(event, "to_dict") else event

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO activity_events
            (timestamp, application, process, window_title, event_type, sensor, pid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("timestamp"),
            data.get("application"),
            data.get("process"),
            data.get("window_title"),
            data.get("event_type", "app_foreground"),
            data.get("sensor"),
            data.get("pid"),
        ))

        event_id = cursor.lastrowid

        ctx = data.get("context", {})
        if ctx and any(v is not None for v in ctx.values()):
            page_title = ctx.get("page_title") or ctx.get("title")
            app_name = data.get("application") or ctx.get("browser")

            # Extract any remaining fields into metadata_json
            known_keys = {
                "workspace", "workspace_path", "file", "file_path",
                "note", "vault", "domain", "url", "page_title", "title", "path",
            }
            extra_metadata = {
                k: v for k, v in ctx.items()
                if k not in known_keys and v is not None
            }

            cursor.execute("""
                INSERT INTO activity_context
                (activity_event_id, application, workspace, workspace_path, file,
                 file_path, note, vault, domain, url, page_title, path, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                app_name,
                ctx.get("workspace"),
                ctx.get("workspace_path"),
                ctx.get("file"),
                ctx.get("file_path"),
                ctx.get("note"),
                ctx.get("vault"),
                ctx.get("domain"),
                ctx.get("url"),
                page_title,
                ctx.get("path"),
                json.dumps(extra_metadata, ensure_ascii=True, sort_keys=True) if extra_metadata else None,
            ))

        connection.commit()

        if hasattr(event, "id") and event_id is not None:
            event.id = event_id

        return event_id

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _row_to_event_dict(row: sqlite3.Row) -> dict:
    """Format a joined database row into a standardized event dict."""
    metadata = {}
    if "metadata_json" in row.keys() and row["metadata_json"]:
        try:
            metadata = json.loads(row["metadata_json"])
        except (ValueError, TypeError):
            metadata = {}

    context = {}
    for key in ("workspace", "workspace_path", "file", "file_path", "note", "vault", "domain", "url", "page_title", "path"):
        if key in row.keys() and row[key] is not None:
            context[key] = row[key]
    context.update(metadata)

    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "event_type": row["event_type"] if "event_type" in row.keys() and row["event_type"] else "app_foreground",
        "sensor": row["sensor"] if "sensor" in row.keys() else None,
        "application": row["application"] if "application" in row.keys() else None,
        "process": row["process"],
        "pid": row["pid"] if "pid" in row.keys() else None,
        "window_title": row["window_title"],
        "context": context,
    }


def get_events(
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int | None = None,
    event_type: str | None = None,
    database_path: Path | str | None = None,
) -> list[dict]:
    """
    Retrieve stored events chronologically with parameterized SQL queries.

    Args:
        start_time: Optional ISO timestamp lower bound (inclusive).
        end_time: Optional ISO timestamp upper bound (inclusive).
        limit: Optional maximum number of events to return.
        event_type: Optional event_type filter.
        database_path: Optional custom database path.

    Returns:
        List of event dicts in chronological order (earliest to latest).
    """

    connection = get_connection(database_path)
    cursor = connection.cursor()

    query = """
        SELECT
            e.id,
            e.timestamp,
            e.application,
            e.process,
            e.window_title,
            e.event_type,
            e.sensor,
            e.pid,
            c.workspace,
            c.workspace_path,
            c.file,
            c.file_path,
            c.note,
            c.vault,
            c.domain,
            c.url,
            c.page_title,
            c.path,
            c.metadata_json
        FROM activity_events e
        LEFT JOIN activity_context c ON e.id = c.activity_event_id
    """

    conditions = []
    params = []

    if start_time is not None:
        conditions.append("e.timestamp >= ?")
        params.append(start_time)

    if end_time is not None:
        conditions.append("e.timestamp <= ?")
        params.append(end_time)

    if event_type is not None:
        conditions.append("e.event_type = ?")
        params.append(event_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY e.timestamp ASC, e.id ASC"

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    connection.close()

    return [_row_to_event_dict(row) for row in rows]


def get_recent_events(limit: int = 50, database_path: Path | str | None = None) -> list[dict]:
    """
    Get the most recent *limit* events, returned in chronological order.
    """

    connection = get_connection(database_path)
    cursor = connection.cursor()

    query = """
        SELECT
            e.id,
            e.timestamp,
            e.application,
            e.process,
            e.window_title,
            e.event_type,
            e.sensor,
            e.pid,
            c.workspace,
            c.workspace_path,
            c.file,
            c.file_path,
            c.note,
            c.vault,
            c.domain,
            c.url,
            c.page_title,
            c.path,
            c.metadata_json
        FROM activity_events e
        LEFT JOIN activity_context c ON e.id = c.activity_event_id
        ORDER BY e.timestamp DESC, e.id DESC
        LIMIT ?
    """

    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    connection.close()

    # Reverse so the returned list is chronological (oldest to newest)
    events = [_row_to_event_dict(row) for row in rows]
    events.reverse()
    return events


def get_events_by_timerange(
    start_time: str,
    end_time: str,
    database_path: Path | str | None = None,
) -> list[dict]:
    """
    Query events within a time range [start_time, end_time] chronologically.
    """
    return get_events(start_time=start_time, end_time=end_time, database_path=database_path)


if __name__ == "__main__":
    create_database()
    print(f"Database ready at: {DATABASE_PATH}")
