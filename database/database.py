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


def get_connection():
    """Create and return a connection to the Personal OS database."""
    return sqlite3.connect(DATABASE_PATH)


def create_database():
    """Create the database tables if they don't already exist."""

    connection = get_connection()
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
    # Add 'application' column to activity_events if it doesn't exist.
    # ALTER TABLE ADD COLUMN is safe — existing rows get NULL.
    _migrate_add_column(
        cursor, "activity_events", "application", "TEXT"
    )

    # Add 'path' column to activity_context for File Explorer paths
    _migrate_add_column(
        cursor, "activity_context", "path", "TEXT"
    )

    # Preserves new, structured collector facts without requiring a schema
    # migration for every source. Sensitive values must be filtered by the
    # collector before reaching this boundary.
    _migrate_add_column(
        cursor, "activity_context", "metadata_json", "TEXT"
    )

    connection.commit()
    connection.close()


def _migrate_add_column(cursor, table: str, column: str, col_type: str):
    """Add a column to a table if it doesn't already exist."""

    cursor.execute(f"PRAGMA table_info({table})")

    existing_columns = {row[1] for row in cursor.fetchall()}

    if column not in existing_columns:

        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        )


def save_activity(timestamp, process, window_title):
    """
    Save one activity event to the database (legacy interface).

    Preserved for backward compatibility with analyzer.py and view.py.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO activity_events
        (timestamp, process, window_title)
        VALUES (?, ?, ?)
    """, (
        timestamp,
        process,
        window_title
    ))

    connection.commit()
    connection.close()


def save_activity_event(event) -> int:
    """
    Save a full ActivityEvent (with context) to the database.

    Inserts into activity_events and, if context is present,
    also inserts into activity_context.

    Args:
        event: An ActivityEvent instance (or anything with .to_dict()).

    Returns:
        The id of the inserted activity_events row.
    """

    data = event.to_dict() if hasattr(event, "to_dict") else event

    connection = get_connection()
    cursor = connection.cursor()

    try:

        # Insert the main event
        cursor.execute("""
            INSERT INTO activity_events
            (timestamp, application, process, window_title)
            VALUES (?, ?, ?, ?)
        """, (
            data["timestamp"],
            data.get("application"),
            data.get("process"),
            data.get("window_title"),
        ))

        event_id = cursor.lastrowid

        # Insert context if we have any useful data
        ctx = data.get("context", {})

        if ctx and any(v is not None for v in ctx.values()):

            page_title = ctx.get("page_title") or ctx.get("title")
            app_name = data.get("application") or ctx.get("browser")

            cursor.execute("""
                INSERT INTO activity_context
                (activity_event_id, application, workspace, file,
                 note, vault, domain, url, page_title, path, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                app_name,
                ctx.get("workspace"),
                ctx.get("file"),
                ctx.get("note"),
                ctx.get("vault"),
                ctx.get("domain"),
                ctx.get("url"),
                page_title,
                ctx.get("path"),
                json.dumps({
                    key: value for key, value in ctx.items()
                    if key not in {
                        "workspace", "file", "note", "vault", "domain",
                        "url", "page_title", "title", "path",
                    } and value is not None
                }, ensure_ascii=True, sort_keys=True),
            ))

        connection.commit()

        return event_id

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


if __name__ == "__main__":
    create_database()
    print(f"Database ready at: {DATABASE_PATH}")
