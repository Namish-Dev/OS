
"""
Tests for ExtensionBrowserAdapter and CascadingBrowserAdapter.

All platform-independent — uses mocking, no real server/browser needed.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sensors.browser.extension_adapter import ExtensionBrowserAdapter
from sensors.browser.cascading_adapter import CascadingBrowserAdapter


class TestExtensionBrowserAdapter:

    def test_returns_none_when_no_fresh_data(self):

        adapter = ExtensionBrowserAdapter()

        with patch(
            "sensors.browser.extension_adapter.extension_server.get_latest_tab_data",
            return_value=None,
        ):
            result = adapter.find_active_tab("GitHub - Google Chrome")

        assert result is None

    def test_returns_enriched_tab_when_fresh(self):

        adapter = ExtensionBrowserAdapter()

        fresh_tab = {
            "url": "https://github.com/octocat/Hello-World",
            "title": "octocat/Hello-World",
            "browser": "Google Chrome",
        }

        with patch(
            "sensors.browser.extension_adapter.extension_server.get_latest_tab_data",
            return_value=fresh_tab,
        ):
            result = adapter.find_active_tab("anything")

        assert result is not None
        assert result["url"] == "https://github.com/octocat/Hello-World"
        assert result["domain"] == "github.com"
        assert result["title"] == "octocat/Hello-World"

    def test_ignores_window_title_argument(self):
        """The extension already knows the active tab; no title matching needed."""

        adapter = ExtensionBrowserAdapter()

        fresh_tab = {"url": "https://example.com/", "title": "Example"}

        with patch(
            "sensors.browser.extension_adapter.extension_server.get_latest_tab_data",
            return_value=fresh_tab,
        ):
            result_a = adapter.find_active_tab("Completely unrelated title")
            result_b = adapter.find_active_tab("")

        assert result_a == result_b

    def test_get_page_tabs_empty_when_no_data(self):

        adapter = ExtensionBrowserAdapter()

        with patch(
            "sensors.browser.extension_adapter.extension_server.get_latest_tab_data",
            return_value=None,
        ):
            assert adapter.get_page_tabs() == []


class TestCascadingBrowserAdapter:

    def test_requires_at_least_one_adapter(self):

        try:
            CascadingBrowserAdapter(adapters=[], process_names=["chrome.exe"])
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_uses_first_adapter_result_when_available(self):

        primary = MagicMock()
        primary.find_active_tab.return_value = {"url": "https://primary.example/"}

        fallback = MagicMock()
        fallback.find_active_tab.return_value = {"url": "https://fallback.example/"}

        adapter = CascadingBrowserAdapter(
            adapters=[primary, fallback],
            process_names=["chrome.exe"],
        )

        result = adapter.find_active_tab("some title")

        assert result == {"url": "https://primary.example/"}
        fallback.find_active_tab.assert_not_called()

    def test_falls_back_when_primary_returns_none(self):

        primary = MagicMock()
        primary.find_active_tab.return_value = None

        fallback = MagicMock()
        fallback.find_active_tab.return_value = {"url": "https://fallback.example/"}

        adapter = CascadingBrowserAdapter(
            adapters=[primary, fallback],
            process_names=["chrome.exe"],
        )

        result = adapter.find_active_tab("some title")

        assert result == {"url": "https://fallback.example/"}

    def test_falls_back_when_primary_raises(self):

        primary = MagicMock()
        primary.find_active_tab.side_effect = RuntimeError("boom")

        fallback = MagicMock()
        fallback.find_active_tab.return_value = {"url": "https://fallback.example/"}

        adapter = CascadingBrowserAdapter(
            adapters=[primary, fallback],
            process_names=["chrome.exe"],
        )

        result = adapter.find_active_tab("some title")

        assert result == {"url": "https://fallback.example/"}

    def test_returns_none_when_all_adapters_fail(self):

        primary = MagicMock()
        primary.find_active_tab.return_value = None

        fallback = MagicMock()
        fallback.find_active_tab.return_value = None

        adapter = CascadingBrowserAdapter(
            adapters=[primary, fallback],
            process_names=["chrome.exe"],
        )

        assert adapter.find_active_tab("some title") is None

    def test_process_names_and_browser_name(self):

        adapter = CascadingBrowserAdapter(
            adapters=[MagicMock()],
            process_names=["chrome.exe", "brave.exe"],
            browser_name="Custom Browser",
        )

        assert adapter.process_names == ["chrome.exe", "brave.exe"]
        assert adapter.browser_name == "Custom Browser"