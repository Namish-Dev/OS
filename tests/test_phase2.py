"""
Tests for Phase 2: activity_classifier, project_matcher, sessionizer.

All platform-independent — uses in-memory data, no real DB/OS needed
for classifier/matcher tests. Sessionizer tests use a temp SQLite DB.
"""

import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.activity_classifier import (
    classify_event,
    CODING, RESEARCH, LEARNING, NOTES, COMMUNICATION, ENTERTAINMENT, FILES, OTHER,
)
from core.project_matcher import ProjectMatcher, UNASSIGNED


# --------------------------------------------------------------------------
# activity_classifier
# --------------------------------------------------------------------------

class TestClassifyEvent:

    def test_vscode_is_coding(self):
        assert classify_event("Visual Studio Code", {}) == CODING

    def test_antigravity_is_coding(self):
        assert classify_event("Antigravity", {}) == CODING

    def test_obsidian_is_notes(self):
        assert classify_event("Obsidian", {"note": "JWT"}) == NOTES

    def test_file_explorer_is_files(self):
        assert classify_event("File Explorer", {"path": "C:\\Projects"}) == FILES

    def test_github_domain_is_research(self):
        result = classify_event("Google Chrome", {"domain": "github.com"})
        assert result == RESEARCH

    def test_youtube_domain_is_learning(self):
        result = classify_event("Google Chrome", {"domain": "youtube.com"})
        assert result == LEARNING

    def test_gmail_domain_is_communication(self):
        result = classify_event("Google Chrome", {"domain": "mail.google.com"})
        assert result == COMMUNICATION

    def test_reddit_domain_is_entertainment(self):
        result = classify_event("Google Chrome", {"domain": "reddit.com"})
        assert result == ENTERTAINMENT

    def test_unknown_domain_is_other(self):
        result = classify_event("Google Chrome", {"domain": "some-random-site.com"})
        assert result == OTHER

    def test_no_context_is_other(self):
        assert classify_event("Some Random App", None) == OTHER

    def test_none_application_is_other(self):
        assert classify_event(None, {}) == OTHER


# --------------------------------------------------------------------------
# project_matcher
# --------------------------------------------------------------------------

def _write_config(tmp_path: Path, projects: list[dict]) -> Path:
    config_path = tmp_path / "projects.json"
    config_path.write_text(json.dumps({"projects": projects}), encoding="utf-8")
    return config_path


class TestProjectMatcher:

    def test_matches_keyword_in_file(self, tmp_path=Path(tempfile.mkdtemp())):

        config_path = _write_config(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py", "jwt"]},
        ])

        matcher = ProjectMatcher(config_path=config_path)

        result = matcher.match("Code.exe - auth.py", {"file": "auth.py"})

        assert result == "FastAPI Authentication"

    def test_matches_keyword_in_domain(self, tmp_path=Path(tempfile.mkdtemp())):

        config_path = _write_config(tmp_path, [
            {"name": "Personal OS", "keywords": ["github.com/anthropics"]},
        ])

        matcher = ProjectMatcher(config_path=config_path)

        result = matcher.match(None, {"url": "https://github.com/anthropics/repo"})

        assert result == "Personal OS"

    def test_no_match_returns_unassigned(self, tmp_path=Path(tempfile.mkdtemp())):

        config_path = _write_config(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["jwt"]},
        ])

        matcher = ProjectMatcher(config_path=config_path)

        result = matcher.match("Random Window", {"file": "unrelated.txt"})

        assert result == UNASSIGNED

    def test_missing_config_file_returns_unassigned(self, tmp_path=Path(tempfile.mkdtemp())):

        matcher = ProjectMatcher(config_path=tmp_path / "does_not_exist.json")

        result = matcher.match("anything", {"file": "auth.py"})

        assert result == UNASSIGNED

    def test_case_insensitive(self, tmp_path=Path(tempfile.mkdtemp())):

        config_path = _write_config(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["JWT"]},
        ])

        matcher = ProjectMatcher(config_path=config_path)

        result = matcher.match(None, {"note": "notes about jwt dependency injection"})

        assert result == "FastAPI Authentication"

    def test_first_matching_project_wins(self, tmp_path=Path(tempfile.mkdtemp())):
        """Equal-length keywords tie-break to config order."""

        config_path = _write_config(tmp_path, [
            {"name": "Project A", "keywords": ["shared"]},
            {"name": "Project B", "keywords": ["shared"]},
        ])

        matcher = ProjectMatcher(config_path=config_path)

        result = matcher.match(None, {"file": "shared.py"})

        assert result == "Project A"

    def test_more_specific_keyword_wins_over_generic_one(self, tmp_path=Path(tempfile.mkdtemp())):
        """A specific filename match should beat a generic workspace-name
        match, even if the generic project is listed first in config."""

        config_path = _write_config(tmp_path, [
            {"name": "Personal OS", "keywords": ["personal os"]},
            {"name": "FastAPI Authentication", "keywords": ["auth.py"]},
        ])

        matcher = ProjectMatcher(config_path=config_path)

        result = matcher.match(
            "auth.py - Personal OS - Visual Studio Code",
            {"workspace": "Personal OS", "file": "auth.py"},
        )

        assert result == "FastAPI Authentication"


# --------------------------------------------------------------------------
# sessionizer
# --------------------------------------------------------------------------

import sqlite3
from unittest.mock import patch

from core.sessionizer import build_sessions, SESSION_GAP_MINUTES


def _make_test_db(rows: list[dict]) -> sqlite3.Connection:
    """
    Build an in-memory SQLite DB with the same schema as the real
    database, populated with the given rows.

    Each row dict may have: timestamp, application, process,
    window_title, and any activity_context fields (file, note, vault,
    domain, url, page_title, path, workspace).
    """

    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            application TEXT,
            process TEXT,
            window_title TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE activity_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_event_id INTEGER NOT NULL,
            workspace TEXT,
            file TEXT,
            note TEXT,
            vault TEXT,
            domain TEXT,
            url TEXT,
            page_title TEXT,
            path TEXT
        )
    """)

    for row in rows:

        cursor.execute(
            "INSERT INTO activity_events (timestamp, application, process, window_title) "
            "VALUES (?, ?, ?, ?)",
            (
                row["timestamp"], row.get("application"),
                row.get("process"), row.get("window_title"),
            ),
        )
        event_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO activity_context "
            "(activity_event_id, workspace, file, note, vault, domain, url, page_title, path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, row.get("workspace"), row.get("file"), row.get("note"),
                row.get("vault"), row.get("domain"), row.get("url"),
                row.get("page_title"), row.get("path"),
            ),
        )

    connection.commit()

    return connection


class TestSessionizer:

    def _matcher_for(self, tmp_path, projects):
        config_path = _write_config(tmp_path, projects)
        return ProjectMatcher(config_path=config_path)

    def test_groups_consecutive_events_same_project(self, tmp_path=Path(tempfile.mkdtemp())):

        base = datetime(2026, 1, 1, 9, 0, 0)

        rows = [
            {
                "timestamp": (base + timedelta(minutes=0)).isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py - Personal OS",
                "file": "auth.py",
            },
            {
                "timestamp": (base + timedelta(minutes=5)).isoformat(),
                "application": "Google Chrome",
                "window_title": "FastAPI - Google Chrome",
                "domain": "fastapi.tiangolo.com",
            },
            {
                "timestamp": (base + timedelta(minutes=10)).isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py - Personal OS",
                "file": "auth.py",
            },
        ]

        matcher = self._matcher_for(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py", "fastapi"]},
        ])

        test_conn = _make_test_db(rows)

        with patch("core.sessionizer.get_connection", return_value=test_conn):
            sessions = build_sessions(matcher=matcher)

        assert len(sessions) == 1
        assert sessions[0].project == "FastAPI Authentication"
        assert "auth.py" in sessions[0].files

    def test_gap_splits_into_two_sessions(self, tmp_path=Path(tempfile.mkdtemp())):

        base = datetime(2026, 1, 1, 9, 0, 0)

        rows = [
            {
                "timestamp": base.isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py",
                "file": "auth.py",
            },
            {
                # Big gap — should start a new session even though
                # it's still nominally the same project.
                "timestamp": (base + timedelta(minutes=SESSION_GAP_MINUTES + 30)).isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py",
                "file": "auth.py",
            },
        ]

        matcher = self._matcher_for(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py"]},
        ])

        test_conn = _make_test_db(rows)

        with patch("core.sessionizer.get_connection", return_value=test_conn):
            sessions = build_sessions(matcher=matcher)

        assert len(sessions) == 2

    def test_project_change_splits_session(self, tmp_path=Path(tempfile.mkdtemp())):

        base = datetime(2026, 1, 1, 9, 0, 0)

        rows = [
            {
                "timestamp": base.isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py",
                "file": "auth.py",
            },
            {
                "timestamp": (base + timedelta(minutes=2)).isoformat(),
                "application": "Visual Studio Code",
                "window_title": "activity_engine.py",
                "file": "activity_engine.py",
            },
        ]

        matcher = self._matcher_for(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py"]},
            {"name": "Personal OS", "keywords": ["activity_engine"]},
        ])

        test_conn = _make_test_db(rows)

        with patch("core.sessionizer.get_connection", return_value=test_conn):
            sessions = build_sessions(matcher=matcher)

        assert len(sessions) == 2
        assert sessions[0].project == "FastAPI Authentication"
        assert sessions[1].project == "Personal OS"

    def test_left_off_label_uses_last_event(self, tmp_path=Path(tempfile.mkdtemp())):

        base = datetime(2026, 1, 1, 9, 0, 0)

        rows = [
            {
                "timestamp": base.isoformat(),
                "application": "Visual Studio Code",
                "window_title": "models.py",
                "file": "models.py",
            },
            {
                "timestamp": (base + timedelta(minutes=3)).isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py",
                "file": "auth.py",
            },
        ]

        matcher = self._matcher_for(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py", "models.py"]},
        ])

        test_conn = _make_test_db(rows)

        with patch("core.sessionizer.get_connection", return_value=test_conn):
            sessions = build_sessions(matcher=matcher)

        assert sessions[0].last_context_label == "auth.py"

    def test_infers_application_from_title_when_null(self, tmp_path=Path(tempfile.mkdtemp())):
        """Legacy rows may have application=NULL; infer from window title suffix."""

        base = datetime(2026, 1, 1, 9, 0, 0)

        rows = [
            {
                "timestamp": base.isoformat(),
                "application": None,
                "window_title": "auth.py - OS - Visual Studio Code",
                "file": "auth.py",
            },
            {
                "timestamp": (base + timedelta(minutes=5)).isoformat(),
                "application": None,
                "window_title": "auth.py - OS - Visual Studio Code",
                "file": "auth.py",
            },
        ]

        matcher = self._matcher_for(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py"]},
        ])

        test_conn = _make_test_db(rows)

        with patch("core.sessionizer.get_connection", return_value=test_conn):
            sessions = build_sessions(matcher=matcher)

        assert len(sessions) == 1
        assert sessions[0].category_minutes.get("Coding", 0) > 0

    def test_summary_contains_expected_fields(self, tmp_path=Path(tempfile.mkdtemp())):

        base = datetime(2026, 1, 1, 9, 0, 0)

        rows = [
            {
                "timestamp": base.isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py",
                "file": "auth.py",
            },
            {
                "timestamp": (base + timedelta(minutes=7)).isoformat(),
                "application": "Google Chrome",
                "window_title": "FastAPI docs",
                "domain": "fastapi.tiangolo.com",
            },
            {
                "timestamp": (base + timedelta(minutes=10)).isoformat(),
                "application": "Visual Studio Code",
                "window_title": "auth.py",
                "file": "auth.py",
            },
        ]

        matcher = self._matcher_for(tmp_path, [
            {"name": "FastAPI Authentication", "keywords": ["auth.py", "fastapi"]},
        ])

        test_conn = _make_test_db(rows)

        with patch("core.sessionizer.get_connection", return_value=test_conn):
            sessions = build_sessions(matcher=matcher)

        summary = sessions[0].summary()

        assert "Project: FastAPI Authentication" in summary
        assert "Files: auth.py" in summary
        assert "coding" in summary.lower()
        assert "research" in summary.lower()