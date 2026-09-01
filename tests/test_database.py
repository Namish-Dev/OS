"""
Tests for database operations.

Uses a temporary in-memory (or temp-file) database to avoid
touching the real personal_os.db.
"""

import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.database import (
    DATABASE_PATH,
    create_database,
    save_activity,
    save_activity_event,
    get_connection,
)
from core.event_model import ActivityEvent


class TestDatabasePath:

    def test_single_database_path(self):
        """There must be exactly one authoritative database path."""

        expected = Path(__file__).resolve().parent.parent / "database" / "personal_os.db"

        assert DATABASE_PATH == expected

    def test_path_is_in_database_dir(self):
        """The database must live in the database/ directory."""

        assert DATABASE_PATH.parent.name == "database"
        assert DATABASE_PATH.name == "personal_os.db"


class TestCreateDatabase:

    def test_creates_tables(self):
        """create_database should create activity_events and activity_context."""

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:

            with patch("database.database.DATABASE_PATH", tmp_path):
                create_database()

                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                assert "activity_events" in tables
                assert "activity_context" in tables

                # Check that application column exists
                cursor.execute("PRAGMA table_info(activity_events)")
                columns = {row[1] for row in cursor.fetchall()}
                assert "application" in columns

                # Check that path column exists in activity_context
                cursor.execute("PRAGMA table_info(activity_context)")
                columns = {row[1] for row in cursor.fetchall()}
                assert "path" in columns

                conn.close()

        finally:
            tmp_path.unlink(missing_ok=True)


class TestSaveActivity:

    def test_legacy_save(self):
        """The legacy save_activity function should still work."""

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:

            with patch("database.database.DATABASE_PATH", tmp_path):
                create_database()

                save_activity(
                    "2026-08-27T15:00:00",
                    "Code.exe",
                    "main.py - OS - Visual Studio Code",
                )

                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()

                cursor.execute("SELECT * FROM activity_events")
                rows = cursor.fetchall()

                assert len(rows) == 1
                assert rows[0][1] == "2026-08-27T15:00:00"
                assert rows[0][2] == "Code.exe"

                conn.close()

        finally:
            tmp_path.unlink(missing_ok=True)


class TestSaveActivityEvent:

    def test_save_event_with_context(self):

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:

            with patch("database.database.DATABASE_PATH", tmp_path):
                create_database()

                event = ActivityEvent(
                    timestamp="2026-08-27T15:01:00",
                    application="Google Chrome",
                    process="chrome.exe",
                    window_title="GitHub - Google Chrome",
                    context={
                        "page_title": "GitHub",
                        "url": "https://github.com/",
                        "domain": "github.com",
                    },
                )

                event_id = save_activity_event(event)

                assert event_id is not None
                assert event_id > 0

                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()

                # Check activity_events
                cursor.execute("SELECT * FROM activity_events WHERE id = ?", (event_id,))
                row = cursor.fetchone()

                assert row is not None
                assert row[1] == "2026-08-27T15:01:00"
                # application column (index depends on position after migration)

                # Check activity_context
                cursor.execute(
                    "SELECT application, domain, url, page_title FROM activity_context WHERE activity_event_id = ?",
                    (event_id,),
                )
                ctx_row = cursor.fetchone()

                assert ctx_row is not None
                assert ctx_row[0] == "Google Chrome"
                assert ctx_row[1] == "github.com"
                assert ctx_row[2] == "https://github.com/"
                assert ctx_row[3] == "GitHub"

                conn.close()

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_save_event_without_context(self):

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:

            with patch("database.database.DATABASE_PATH", tmp_path):
                create_database()

                event = ActivityEvent(
                    timestamp="2026-08-27T15:02:00",
                    application="something.exe",
                    process="something.exe",
                    window_title="Unknown Window",
                    context={},
                )

                event_id = save_activity_event(event)

                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()

                # Event should be saved
                cursor.execute("SELECT * FROM activity_events WHERE id = ?", (event_id,))
                assert cursor.fetchone() is not None

                # No context row (empty context)
                cursor.execute(
                    "SELECT * FROM activity_context WHERE activity_event_id = ?",
                    (event_id,),
                )
                assert cursor.fetchone() is None

                conn.close()

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_save_vscode_context(self):

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:

            with patch("database.database.DATABASE_PATH", tmp_path):
                create_database()

                event = ActivityEvent(
                    timestamp="2026-08-27T15:03:00",
                    application="Visual Studio Code",
                    process="Code.exe",
                    window_title="main.py - OS - Visual Studio Code",
                    context={
                        "file": "main.py",
                        "workspace": "OS",
                    },
                )

                event_id = save_activity_event(event)

                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT file, workspace FROM activity_context WHERE activity_event_id = ?",
                    (event_id,),
                )
                row = cursor.fetchone()

                assert row is not None
                assert row[0] == "main.py"
                assert row[1] == "OS"

                conn.close()

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_save_antigravity_context(self):

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:

            with patch("database.database.DATABASE_PATH", tmp_path):
                create_database()

                event = ActivityEvent(
                    timestamp="2026-08-27T15:04:00",
                    application="Antigravity",
                    process="Antigravity IDE.exe",
                    window_title="OS - Antigravity IDE - view.py",
                    context={
                        "file": "view.py",
                        "workspace": "OS",
                    },
                )

                event_id = save_activity_event(event)

                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT application, file, workspace FROM activity_context WHERE activity_event_id = ?",
                    (event_id,),
                )
                row = cursor.fetchone()

                assert row is not None
                assert row[0] == "Antigravity"
                assert row[1] == "view.py"
                assert row[2] == "OS"

                conn.close()

        finally:
            tmp_path.unlink(missing_ok=True)

