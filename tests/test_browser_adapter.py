"""
Tests for the browser adapter (CDP) layer.

All platform-independent — uses mocking, no real browser needed.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sensors.browser.cdp_adapter import CDPBrowserAdapter
from sensors.browser.chrome_adapter import ChromeAdapter


# --------------------------------------------------------------------------
# Helper: create a mock adapter that returns controlled tab data
# --------------------------------------------------------------------------

def _make_adapter_with_tabs(tabs: list[dict]) -> ChromeAdapter:
    """Return a ChromeAdapter whose _fetch_tabs returns *tabs*."""

    adapter = ChromeAdapter()
    adapter._fetch_tabs = MagicMock(return_value=tabs)

    return adapter


# --------------------------------------------------------------------------
# Tab filtering
# --------------------------------------------------------------------------

class TestGetPageTabs:

    def test_filters_to_pages_only(self):

        tabs = [
            {"type": "page",   "title": "GitHub", "url": "https://github.com/"},
            {"type": "iframe", "title": "Ad Frame", "url": "https://ads.example.com/"},
            {"type": "page",   "title": "YouTube", "url": "https://youtube.com/"},
        ]

        adapter = _make_adapter_with_tabs(tabs)
        result = adapter.get_page_tabs()

        assert len(result) == 2
        assert all(t["type"] == "page" for t in result)

    def test_filters_iframe(self):

        tabs = [
            {"type": "iframe", "title": "Hidden", "url": "https://example.com/"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_filters_browser_ui(self):

        tabs = [
            {"type": "browser_ui", "title": "Chrome UI", "url": ""},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_filters_background_page(self):

        tabs = [
            {"type": "background_page", "title": "Extension BG",
             "url": "chrome-extension://abc/bg.html"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_filters_service_worker(self):

        tabs = [
            {"type": "service_worker", "title": "",
             "url": "chrome-extension://abc/sw.js"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_filters_chrome_internal_pages(self):

        tabs = [
            {"type": "page", "title": "Settings",
             "url": "chrome://settings"},
            {"type": "page", "title": "Extensions",
             "url": "chrome://extensions"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_filters_extension_urls(self):

        tabs = [
            {"type": "page", "title": "Extension Popup",
             "url": "chrome-extension://abc123/popup.html"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_filters_devtools(self):

        tabs = [
            {"type": "page", "title": "DevTools",
             "url": "devtools://devtools/bundled/inspector.html"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        assert adapter.get_page_tabs() == []

    def test_empty_response(self):

        adapter = _make_adapter_with_tabs([])

        assert adapter.get_page_tabs() == []

    def test_mixed_real_and_internal(self):

        tabs = [
            {"type": "page", "title": "GitHub", "url": "https://github.com/"},
            {"type": "page", "title": "New Tab", "url": "chrome://newtab"},
            {"type": "iframe", "title": "Ad", "url": "https://ads.com/"},
            {"type": "page", "title": "YouTube", "url": "https://youtube.com/"},
            {"type": "background_page", "title": "Ext",
             "url": "chrome-extension://xyz/bg.html"},
        ]

        adapter = _make_adapter_with_tabs(tabs)
        result = adapter.get_page_tabs()

        assert len(result) == 2
        titles = {t["title"] for t in result}
        assert titles == {"GitHub", "YouTube"}


# --------------------------------------------------------------------------
# Active tab matching
# --------------------------------------------------------------------------

class TestFindActiveTab:

    def test_exact_match(self):

        tabs = [
            {"type": "page", "title": "YouTube", "url": "https://youtube.com/"},
            {"type": "page", "title": "GitHub", "url": "https://github.com/"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        result = adapter.find_active_tab("GitHub - Google Chrome")

        assert result is not None
        assert result["browser"] == "Google Chrome"
        assert result["title"] == "GitHub"
        assert result["page_title"] == "GitHub"
        assert result["url"] == "https://github.com/"
        assert result["domain"] == "github.com"

    def test_notification_count_match(self):

        tabs = [
            {"type": "page", "title": "GitHub", "url": "https://github.com/"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        result = adapter.find_active_tab("(3) GitHub - Google Chrome")

        assert result is not None
        assert result["page_title"] == "GitHub"
        assert result["url"] == "https://github.com/"
        assert result["domain"] == "github.com"

    def test_partial_match(self):

        tabs = [
            {"type": "page",
             "title": "VCT Pacific - YouTube",
             "url": "https://youtube.com/watch?v=xyz"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        result = adapter.find_active_tab(
            "VCT Pacific - YouTube - Google Chrome"
        )

        assert result is not None
        assert result["page_title"] == "VCT Pacific - YouTube"
        assert result["domain"] == "youtube.com"

    def test_no_match(self):

        tabs = [
            {"type": "page", "title": "GitHub", "url": "https://github.com/"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        result = adapter.find_active_tab("Netflix - Google Chrome")

        assert result is None

    def test_case_insensitive_match(self):

        tabs = [
            {"type": "page", "title": "ChatGPT", "url": "https://chat.openai.com/"},
        ]

        adapter = _make_adapter_with_tabs(tabs)

        result = adapter.find_active_tab("chatgpt - Google Chrome")

        assert result is not None
        assert result["page_title"] == "ChatGPT"

    def test_none_title(self):

        adapter = _make_adapter_with_tabs([])

        assert adapter.find_active_tab(None) is None

    def test_empty_title(self):

        adapter = _make_adapter_with_tabs([])

        assert adapter.find_active_tab("") is None

    def test_no_tabs_available(self):

        adapter = _make_adapter_with_tabs([])

        result = adapter.find_active_tab("GitHub - Google Chrome")

        assert result is None


# --------------------------------------------------------------------------
# Network failure handling
# --------------------------------------------------------------------------

class TestBrowserUnavailable:

    @patch("sensors.browser.cdp_adapter.requests.get")
    def test_connection_refused(self, mock_get):
        """Simulate Chrome not running with debugging."""

        import requests as req

        mock_get.side_effect = req.ConnectionError("Connection refused")

        adapter = ChromeAdapter()

        # Should not crash
        result = adapter.get_page_tabs()
        assert result == []

        result = adapter.find_active_tab("GitHub - Google Chrome")
        assert result is None

    @patch("sensors.browser.cdp_adapter.requests.get")
    def test_timeout(self, mock_get):

        import requests as req

        mock_get.side_effect = req.Timeout("Request timed out")

        adapter = ChromeAdapter()

        assert adapter.get_page_tabs() == []

    @patch("sensors.browser.cdp_adapter.requests.get")
    def test_malformed_json(self, mock_get):

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response

        adapter = ChromeAdapter()

        assert adapter.get_page_tabs() == []

    @patch("sensors.browser.cdp_adapter.requests.get")
    def test_non_list_response(self, mock_get):
        """CDP returns something unexpected (not a list)."""

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"error": "something"}
        mock_get.return_value = mock_response

        adapter = ChromeAdapter()

        assert adapter.get_page_tabs() == []


# --------------------------------------------------------------------------
# Adapter properties
# --------------------------------------------------------------------------

class TestChromeAdapterConfig:

    def test_process_names(self):

        adapter = ChromeAdapter()

        assert "chrome.exe" in adapter.process_names
        assert "google-chrome" in adapter.process_names

    def test_browser_name(self):

        adapter = ChromeAdapter()

        assert adapter.browser_name == "Google Chrome"
