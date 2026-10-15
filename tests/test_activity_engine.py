"""
Tests for core.activity_engine.ActivityEngine.

All platform-independent — browser adapters are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.activity_engine import ActivityEngine
from core.event_model import ActivityEvent


def _make_mock_adapter(
    process_names=None,
    browser_name="Google Chrome",
    find_active_tab_return=None,
):
    """Create a mock BrowserAdapter."""

    adapter = MagicMock()
    adapter.process_names = process_names or ["chrome.exe", "google-chrome"]
    adapter.browser_name = browser_name
    adapter.find_active_tab.return_value = find_active_tab_return

    return adapter


class TestProcessObservation:

    @patch("core.activity_engine.save_activity_event")
    def test_vscode_event(self, mock_save):

        engine = ActivityEngine()

        event = engine.process_observation(
            "Code.exe",
            "main.py - OS - Visual Studio Code",
        )

        assert isinstance(event, ActivityEvent)
        assert event.application == "Visual Studio Code"
        assert event.process == "Code.exe"
        assert event.context["file"] == "main.py"
        assert event.context["workspace"] == "OS"

        mock_save.assert_called_once()

    @patch("core.activity_engine.save_activity_event")
    def test_antigravity_event(self, mock_save):

        engine = ActivityEngine()

        event = engine.process_observation(
            "Antigravity IDE.exe",
            "OS - Antigravity IDE - view.py",
        )

        assert isinstance(event, ActivityEvent)
        assert event.application == "Antigravity"
        assert event.process == "Antigravity IDE.exe"
        assert event.context["file"] == "view.py"
        assert event.context["workspace"] == "OS"

        mock_save.assert_called_once()

    @patch("core.activity_engine.save_activity_event")
    def test_obsidian_event(self, mock_save):

        engine = ActivityEngine()

        event = engine.process_observation(
            "Obsidian.exe",
            "Daily Log - Personal - Obsidian 1.13.7",
        )

        assert event.application == "Obsidian"
        assert event.context["note"] == "Daily Log"
        assert event.context["vault"] == "Personal"

    @patch("core.activity_engine.save_activity_event")
    def test_explorer_event(self, mock_save):

        engine = ActivityEngine()

        event = engine.process_observation(
            "explorer.exe",
            "Downloads",
        )

        assert event.application == "File Explorer"
        assert event.context["path"] == "Downloads"

    @patch("core.activity_engine.save_activity_event")
    def test_unknown_application(self, mock_save):
        """Unknown processes should not crash and should use raw name."""

        engine = ActivityEngine()

        event = engine.process_observation(
            "something.exe",
            "My Window",
        )

        assert event.application == "something.exe"
        assert event.process == "something.exe"
        assert event.context == {}

        mock_save.assert_called_once()

    @patch("core.activity_engine.save_activity_event")
    def test_none_process(self, mock_save):

        engine = ActivityEngine()

        event = engine.process_observation(None, "Window")

        assert event.application == "Unknown"
        assert event.process == "unknown"

    @patch("core.activity_engine.save_activity_event")
    def test_sensor_context_fills_missing_workspace(self, mock_save):
        engine = ActivityEngine()

        event = engine.process_observation(
            "code",
            "Welcome - Visual Studio Code",
            {"workspace": "work", "window_pid": 1234},
        )

        assert event.context["workspace"] == "work"
        assert event.context["window_pid"] == 1234

    @patch("core.activity_engine.save_activity_event")
    def test_vscode_extension_and_git_context_are_enriched(self, mock_save):
        adapter = MagicMock()
        adapter.get_context.return_value = {
            "workspace": "personal-agent",
            "workspace_path": "/home/user/Projects/personal-agent",
            "file": "context.py",
            "language": "python",
        }
        git = MagicMock()
        git.collect.return_value = {"git": {"branch": "context-engine", "modified_files": 4}}
        engine = ActivityEngine(vscode_adapter=adapter, git_collector=git)

        event = engine.process_observation("code", "Welcome - Visual Studio Code")

        assert event.context["workspace_path"] == "/home/user/Projects/personal-agent"
        assert event.context["file"] == "context.py"
        assert event.context["git"]["branch"] == "context-engine"
        git.collect.assert_called_once_with("/home/user/Projects/personal-agent")


class TestBrowserEnrichment:

    @patch("core.activity_engine.save_activity_event")
    def test_chrome_with_active_tab(self, mock_save):

        adapter = _make_mock_adapter(
            find_active_tab_return={
                "browser": "Google Chrome",
                "title": "GitHub",
                "page_title": "GitHub",
                "url": "https://github.com/",
                "domain": "github.com",
            },
        )

        engine = ActivityEngine(browser_adapters=[adapter])

        event = engine.process_observation(
            "chrome.exe",
            "GitHub - Google Chrome",
        )

        assert event.application == "Google Chrome"
        assert event.context["browser"] == "Google Chrome"
        assert event.context["title"] == "GitHub"
        assert event.context["page_title"] == "GitHub"
        assert event.context["url"] == "https://github.com/"
        assert event.context["domain"] == "github.com"
        mock_save.assert_called_once()

    def test_chrome_end_to_end_persistence(self, tmp_path):
        """Verify full path from process_observation to database storage."""
        import sqlite3
        from database.database import create_database

        db_file = tmp_path / "test_persist.db"
        with patch("database.database.DATABASE_PATH", db_file):
            create_database()

            adapter = _make_mock_adapter(
                find_active_tab_return={
                    "browser": "Google Chrome",
                    "title": "GitHub: Where the world builds software",
                    "page_title": "GitHub: Where the world builds software",
                    "url": "https://github.com/",
                    "domain": "github.com",
                },
            )

            engine = ActivityEngine(browser_adapters=[adapter])
            event = engine.process_observation("chrome.exe", "GitHub - Google Chrome")

            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

            # Check activity_events
            cursor.execute("SELECT application, process, window_title FROM activity_events")
            event_row = cursor.fetchone()
            assert event_row == ("Google Chrome", "chrome.exe", "GitHub - Google Chrome")

            # Check activity_context
            cursor.execute("SELECT application, domain, url, page_title FROM activity_context")
            ctx_row = cursor.fetchone()
            assert ctx_row is not None
            assert ctx_row[0] == "Google Chrome"
            assert ctx_row[1] == "github.com"
            assert ctx_row[2] == "https://github.com/"
            assert ctx_row[3] == "GitHub: Where the world builds software"

            conn.close()

    @patch("core.activity_engine.save_activity_event")
    def test_chrome_no_tab_match(self, mock_save):
        """When CDP can't match the tab, we still get the page title."""

        adapter = _make_mock_adapter(find_active_tab_return=None)

        engine = ActivityEngine(browser_adapters=[adapter])

        event = engine.process_observation(
            "chrome.exe",
            "Some Page - Google Chrome",
        )

        assert event.application == "Google Chrome"
        assert event.context["page_title"] == "Some Page"
        # No url/domain since tab wasn't matched
        assert "url" not in event.context

    @patch("core.activity_engine.save_activity_event")
    def test_chrome_adapter_throws(self, mock_save):
        """If the adapter crashes, the event is still created."""

        adapter = _make_mock_adapter()
        adapter.find_active_tab.side_effect = Exception("CDP error")

        engine = ActivityEngine(browser_adapters=[adapter])

        event = engine.process_observation(
            "chrome.exe",
            "YouTube - Google Chrome",
        )

        assert event.application == "Google Chrome"
        assert event.context["page_title"] == "YouTube"
        # Still saved successfully
        mock_save.assert_called_once()

    @patch("core.activity_engine.save_activity_event")
    def test_no_browser_adapters(self, mock_save):
        """Chrome without any adapter just gets the page title."""

        engine = ActivityEngine(browser_adapters=[])

        event = engine.process_observation(
            "chrome.exe",
            "Netflix - Google Chrome",
        )

        assert event.application == "Google Chrome"
        assert event.context["page_title"] == "Netflix"


class TestDatabaseSaving:

    @patch("core.activity_engine.save_activity_event")
    def test_save_called(self, mock_save):

        engine = ActivityEngine()

        engine.process_observation("Code.exe", "Test - Visual Studio Code")

        mock_save.assert_called_once()

        saved_event = mock_save.call_args[0][0]
        assert isinstance(saved_event, ActivityEvent)

    @patch("core.activity_engine.save_activity_event")
    def test_save_failure_does_not_crash(self, mock_save):
        """Database errors must never crash the tracker."""

        mock_save.side_effect = Exception("disk full")

        engine = ActivityEngine()

        # Should not raise
        event = engine.process_observation("Code.exe", "Test - Visual Studio Code")

        assert event is not None
