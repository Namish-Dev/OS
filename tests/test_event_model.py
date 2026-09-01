"""
Tests for core.event_model.ActivityEvent.

All platform-independent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.event_model import ActivityEvent


class TestActivityEventCreate:

    def test_create_basic(self):

        event = ActivityEvent.create(
            application="Google Chrome",
            process="chrome.exe",
            window_title="GitHub - Google Chrome",
        )

        assert event.application == "Google Chrome"
        assert event.process == "chrome.exe"
        assert event.window_title == "GitHub - Google Chrome"
        assert event.context == {}
        assert event.timestamp  # Should be a non-empty string

    def test_create_with_context(self):

        ctx = {"file": "main.py", "workspace": "OS"}

        event = ActivityEvent.create(
            application="Visual Studio Code",
            process="Code.exe",
            window_title="main.py - OS - Visual Studio Code",
            context=ctx,
        )

        assert event.context == ctx
        assert event.context["file"] == "main.py"
        assert event.context["workspace"] == "OS"

    def test_create_none_process(self):
        """None process should become 'unknown'."""

        event = ActivityEvent.create(
            application="Unknown",
            process=None,
            window_title="Something",
        )

        assert event.process == "unknown"

    def test_create_none_title(self):
        """None window title should become empty string."""

        event = ActivityEvent.create(
            application="Unknown",
            process="test.exe",
            window_title=None,
        )

        assert event.window_title == ""

    def test_create_none_context(self):
        """None context should become empty dict."""

        event = ActivityEvent.create(
            application="Test",
            process="test.exe",
            window_title="Test",
            context=None,
        )

        assert event.context == {}


class TestActivityEventToDict:

    def test_to_dict_structure(self):

        event = ActivityEvent.create(
            application="Google Chrome",
            process="chrome.exe",
            window_title="GitHub - Google Chrome",
            context={"url": "https://github.com/", "domain": "github.com"},
        )

        d = event.to_dict()

        assert isinstance(d, dict)
        assert d["application"] == "Google Chrome"
        assert d["process"] == "chrome.exe"
        assert d["window_title"] == "GitHub - Google Chrome"
        assert d["context"]["url"] == "https://github.com/"
        assert d["context"]["domain"] == "github.com"
        assert "timestamp" in d

    def test_to_dict_context_is_copy(self):
        """Modifying the returned dict should not affect the original."""

        event = ActivityEvent.create(
            application="Test",
            process="test.exe",
            window_title="Test",
            context={"key": "value"},
        )

        d = event.to_dict()
        d["context"]["key"] = "modified"

        assert event.context["key"] == "value"


class TestActivityEventStr:

    def test_str_no_context(self):

        event = ActivityEvent.create(
            application="Notepad",
            process="notepad.exe",
            window_title="Untitled",
        )

        s = str(event)

        assert "Notepad" in s

    def test_str_with_context(self):

        event = ActivityEvent.create(
            application="Google Chrome",
            process="chrome.exe",
            window_title="GitHub - Google Chrome",
            context={"domain": "github.com"},
        )

        s = str(event)

        assert "Google Chrome" in s
        assert "github.com" in s
