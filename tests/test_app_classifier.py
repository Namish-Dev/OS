"""
Tests for core.app_classifier.

All platform-independent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app_classifier import classify_application, is_browser


class TestClassifyApplication:

    def test_known_windows_processes(self):

        assert classify_application("Code.exe") == "Visual Studio Code"
        assert classify_application("Antigravity IDE.exe") == "Antigravity"
        assert classify_application("Antigravity.exe") == "Antigravity"
        assert classify_application("chrome.exe") == "Google Chrome"
        assert classify_application("brave.exe") == "Brave"
        assert classify_application("msedge.exe") == "Microsoft Edge"
        assert classify_application("Obsidian.exe") == "Obsidian"
        assert classify_application("explorer.exe") == "File Explorer"
        assert classify_application("SearchHost.exe") == "Windows Search"

    def test_known_linux_processes(self):

        assert classify_application("code") == "Visual Studio Code"
        assert classify_application("antigravity") == "Antigravity"
        assert classify_application("antigravity-ide") == "Antigravity"
        assert classify_application("google-chrome") == "Google Chrome"
        assert classify_application("brave-browser") == "Brave"
        assert classify_application("obsidian") == "Obsidian"

    def test_unknown_process(self):
        """Unknown processes should return the raw process name."""

        assert classify_application("something.exe") == "something.exe"
        assert classify_application("myapp") == "myapp"

    def test_none_process(self):

        assert classify_application(None) == "Unknown"

    def test_empty_process(self):

        assert classify_application("") == "Unknown"


class TestIsBrowser:

    def test_browser_processes(self):

        assert is_browser("chrome.exe") is True
        assert is_browser("google-chrome") is True
        assert is_browser("brave.exe") is True
        assert is_browser("msedge.exe") is True

    def test_non_browser_processes(self):

        assert is_browser("Code.exe") is False
        assert is_browser("Obsidian.exe") is False
        assert is_browser("explorer.exe") is False

    def test_none_and_empty(self):

        assert is_browser(None) is False
        assert is_browser("") is False
