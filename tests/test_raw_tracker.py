"""
Tests for Raw Activity Tracking System.

Verifies:
- Application and window changes generate appropriate events.
- Browser titles and URLs are captured when supported.
- Missing browser metadata is handled correctly without inventing URLs.
- File and folder events are recorded accurately by supported sensors.
- Duplicate foreground-state events are avoided.
- Events persist across application restarts.
- Timestamps, PID, and optional metadata are handled correctly.
- Database queries return the correct events in chronological order.
- Sensor failures do not crash unrelated tracking components.
- The application starts and stops cleanly.
- Removed intelligence features are not required for the tracker to operate.
"""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.activity_engine import ActivityEngine
from core.event_model import ActivityEvent
from core.context_extractors import (
    parse_vscode_title,
    parse_antigravity_title,
    parse_obsidian_title,
    parse_explorer_title,
    sanitize_url,
)
from database.database import (
    create_database,
    get_connection,
    save_activity_event,
    get_events,
    get_recent_events,
    get_events_by_timerange,
)
from activity.activity_tracker import ActivityTracker


class TestDebounceAndDuplicatePrevention:

    def test_duplicate_foreground_events_are_avoided(self):
        """Identical consecutive observations do not create new events."""
        mock_sensor = MagicMock()
        mock_sensor.get_foreground.return_value = {
            "process": "Code.exe",
            "window_title": "main.py - OS - Visual Studio Code",
            "hwnd": 12345,
            "pid": 9999,
        }
        engine = MagicMock()
        engine.process_observation.return_value = ActivityEvent.create("Visual Studio Code", "Code.exe", "main.py - OS")

        tracker = ActivityTracker(sensor=mock_sensor, engine=engine, debounce_seconds=1.0, heartbeat_seconds=60.0)

        # First tick at t=0: window becomes candidate
        ev1 = tracker.step(current_time=0.0)
        assert ev1 is None
        assert engine.process_observation.call_count == 0

        # Second tick at t=1.5 (> debounce): window is committed
        ev2 = tracker.step(current_time=1.5)
        assert ev2 is not None
        assert engine.process_observation.call_count == 1

        # Third tick at t=2.0 (same window): must NOT record a duplicate
        ev3 = tracker.step(current_time=2.0)
        assert ev3 is None
        assert engine.process_observation.call_count == 1

        # Fourth tick at t=65.0 (>= heartbeat): records heartbeat observation
        ev4 = tracker.step(current_time=65.0)
        assert ev4 is not None
        assert engine.process_observation.call_count == 2

    def test_window_switch_records_new_event(self):
        """Switching to another window records a new event after debounce."""
        mock_sensor = MagicMock()
        engine = MagicMock()
        tracker = ActivityTracker(sensor=mock_sensor, engine=engine, debounce_seconds=1.0)

        # Window A focused
        mock_sensor.get_foreground.return_value = {"process": "Code.exe", "window_title": "A", "hwnd": 1}
        tracker.step(current_time=0.0)
        tracker.step(current_time=1.5)
        assert engine.process_observation.call_count == 1

        # Switch to Window B
        mock_sensor.get_foreground.return_value = {"process": "chrome.exe", "window_title": "B", "hwnd": 2}
        tracker.step(current_time=2.0)  # candidate
        assert engine.process_observation.call_count == 1

        tracker.step(current_time=3.5)  # debounced & committed
        assert engine.process_observation.call_count == 2


class TestBrowserTrackingAndMetadata:

    def test_browser_url_and_domain_captured(self):
        """Browser active tab enriches URL, domain, and page_title."""
        mock_adapter = MagicMock()
        mock_adapter.process_names = ["chrome.exe"]
        mock_adapter.find_active_tab.return_value = {
            "url": "https://github.com/Namish-Dev/OS?ref=main",
            "domain": "github.com",
            "page_title": "GitHub - Repo",
        }
        with patch("core.activity_engine.save_activity_event"):
            engine = ActivityEngine(browser_adapters=[mock_adapter])
            event = engine.process_observation("chrome.exe", "GitHub - Repo - Google Chrome")

            assert event.application == "Google Chrome"
            assert event.domain == "github.com"
            assert event.url == "https://github.com/Namish-Dev/OS?ref=main"
            assert event.page_title == "GitHub - Repo"

    def test_missing_browser_url_handled_gracefully(self):
        """When browser adapter fails or returns None, URL is None and not invented."""
        mock_adapter = MagicMock()
        mock_adapter.process_names = ["chrome.exe"]
        mock_adapter.find_active_tab.return_value = None

        with patch("core.activity_engine.save_activity_event"):
            engine = ActivityEngine(browser_adapters=[mock_adapter])
            event = engine.process_observation("chrome.exe", "Private Page - Google Chrome")

            assert event.application == "Google Chrome"
            assert event.url is None
            assert event.domain is None
            assert event.page_title == "Private Page"

    def test_url_privacy_sanitization_removes_tokens(self):
        """Sensitive authentication tokens and passwords in query strings are removed."""
        url = "https://example.com/callback?code=SECRET123&token=xyz789&user=namish#access_token=bad"
        cleaned = sanitize_url(url)
        assert "SECRET123" not in cleaned
        assert "token" not in cleaned
        assert "user=namish" in cleaned
        assert "#access_token" not in cleaned

    def test_url_privacy_strip_all_query_option(self):
        """When configured to strip all query params, URLs are cleanly trimmed."""
        url = "https://example.com/search?q=my+secret+search&page=2"
        cleaned = sanitize_url(url, strip_all_query=True)
        assert cleaned == "https://example.com/search"


class TestFileAndFolderTracking:

    def test_vscode_file_and_workspace_tracking(self):
        """VS Code titles and extension reports record workspace and file paths."""
        title_context = parse_vscode_title("activity_tracker.py - OS - Visual Studio Code")
        assert title_context == {"file": "activity_tracker.py", "workspace": "OS"}

        mock_vscode_adapter = MagicMock()
        mock_vscode_adapter.get_context.return_value = {
            "workspace": "OS",
            "workspace_path": "E:\\OS",
            "file": "activity_tracker.py",
            "file_path": "E:\\OS\\activity\\activity_tracker.py",
            "language": "python",
        }
        with patch("core.activity_engine.save_activity_event"):
            engine = ActivityEngine(vscode_adapter=mock_vscode_adapter)
            event = engine.process_observation("Code.exe", "activity_tracker.py - OS - Visual Studio Code")

            assert event.workspace == "OS"
            assert event.workspace_path == "E:\\OS"
            assert event.file == "activity_tracker.py"
            assert event.file_path == "E:\\OS\\activity\\activity_tracker.py"

    def test_explorer_folder_path_tracking(self):
        """File Explorer titles are recorded as paths."""
        assert parse_explorer_title("Downloads") == {"path": "Downloads"}
        assert parse_explorer_title("C:\\Users\\namish\\Documents") == {"path": "C:\\Users\\namish\\Documents"}

    def test_antigravity_title_tracking(self):
        """Antigravity IDE titles parse file and workspace accurately."""
        assert parse_antigravity_title("OS - Antigravity IDE - main.py") == {
            "file": "main.py",
            "workspace": "OS",
        }

    def test_obsidian_notes_and_vault_tracking(self):
        """Obsidian window titles record note name and vault name."""
        assert parse_obsidian_title("Research Notes - Personal - Obsidian 1.13.7") == {
            "note": "Research Notes",
            "vault": "Personal",
        }


class TestPersistenceAndQueries:

    def test_events_persist_across_application_restarts(self):
        """Events stored in SQLite remain available across connection and application restarts."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db = Path(tmp.name)

        try:
            create_database(tmp_db)

            # Session 1: Tracker writes event
            event1 = ActivityEvent.create(
                application="Visual Studio Code",
                process="Code.exe",
                window_title="main.py - OS - Visual Studio Code",
                context={"file": "main.py", "workspace_path": "E:\\OS"},
                pid=1234,
                timestamp="2026-10-19T10:00:00",
            )
            with patch("database.database.DATABASE_PATH", tmp_db):
                save_activity_event(event1)

            # Session 2: "Restart" - fresh connection queries the database
            events = get_events(database_path=tmp_db)
            assert len(events) == 1
            e = events[0]
            assert e["application"] == "Visual Studio Code"
            assert e["process"] == "Code.exe"
            assert e["pid"] == 1234
            assert e["context"]["file"] == "main.py"
            assert e["context"]["workspace_path"] == "E:\\OS"

        finally:
            tmp_db.unlink(missing_ok=True)

    def test_database_chronological_ordering_and_timerange_queries(self):
        """Queries return events in chronological order and support time ranges."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db = Path(tmp.name)

        try:
            create_database(tmp_db)

            # Insert out-of-order timestamps
            e2 = ActivityEvent.create("App B", "b.exe", "Window B", timestamp="2026-10-19T12:00:00")
            e1 = ActivityEvent.create("App A", "a.exe", "Window A", timestamp="2026-10-19T10:00:00")
            e3 = ActivityEvent.create("App C", "c.exe", "Window C", timestamp="2026-10-19T14:00:00")

            with patch("database.database.DATABASE_PATH", tmp_db):
                save_activity_event(e2)
                save_activity_event(e1)
                save_activity_event(e3)

            # 1. Full chronological query
            all_events = get_events(database_path=tmp_db)
            assert len(all_events) == 3
            assert [x["timestamp"] for x in all_events] == [
                "2026-10-19T10:00:00",
                "2026-10-19T12:00:00",
                "2026-10-19T14:00:00",
            ]

            # 2. Time-range query
            filtered = get_events_by_timerange(
                start_time="2026-10-19T11:00:00",
                end_time="2026-10-19T13:00:00",
                database_path=tmp_db,
            )
            assert len(filtered) == 1
            assert filtered[0]["application"] == "App B"

            # 3. Recent events query
            recent = get_recent_events(limit=2, database_path=tmp_db)
            assert len(recent) == 2
            assert [x["application"] for x in recent] == ["App B", "App C"]

        finally:
            tmp_db.unlink(missing_ok=True)


class TestTrackerLifecycleAndFailureResilience:

    def test_sensor_error_does_not_crash_tracker(self):
        """When an OS sensor raises an exception, the tracker recovers gracefully."""
        mock_sensor = MagicMock()
        mock_sensor.get_foreground.side_effect = RuntimeError("OS IPC failed")
        engine = MagicMock()

        tracker = ActivityTracker(sensor=mock_sensor, engine=engine)
        # Should not raise exception
        result = tracker.step(current_time=1.0)
        assert result is None
        assert engine.process_observation.call_count == 0

    def test_database_error_does_not_crash_engine(self):
        """When database write fails, engine logs warning and returns event without crashing."""
        with patch("core.activity_engine.save_activity_event", side_effect=sqlite3.OperationalError("disk error")):
            engine = ActivityEngine()
            event = engine.process_observation("notepad.exe", "Untitled - Notepad")
            assert event.application == "notepad.exe"
            assert event.window_title == "Untitled - Notepad"

    def test_tracker_clean_stop(self):
        """Tracker can be stopped cleanly."""
        tracker = ActivityTracker(sensor=MagicMock(), engine=MagicMock())
        tracker.running = True
        tracker.stop()
        assert tracker.running is False

    def test_removed_intelligence_features_not_required(self):
        """System operates without any removed LLM, classification, or project matcher modules."""
        # Assert none of the removed modules are imported or required
        engine = ActivityEngine()
        event = engine.process_observation("chrome.exe", "Google Search - Google Chrome")
        assert event.application == "Google Chrome"

        # Verify removed modules are not in sys.modules
        removed_modules = [
            "core.llm_client",
            "core.llm_classifier",
            "core.project_matcher",
            "core.sessionizer",
            "core.activity_classifier",
            "core.daily_report",
            "core.daily_attribution",
        ]
        for mod in removed_modules:
            assert mod not in sys.modules
