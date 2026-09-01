"""
Personal OS — Extension-based Browser Adapter.

Implements the same BrowserAdapter interface as CDPBrowserAdapter,
but sources active-tab data from the Personal OS browser extension
(via extension_server.py) instead of polling the Chrome DevTools
Protocol.

Why this exists:
    CDP only works against a browser launched with
    --remote-debugging-port, which the user's normal browser never
    is. This adapter works against whatever Chromium-based browser
    (Chrome, Brave, Edge) the user is actually using day-to-day,
    as long as the Personal OS extension is installed.

This module is platform-independent.
"""

from core.context_extractors import extract_domain
from sensors.browser import extension_server
from sensors.browser.base import BrowserAdapter


class ExtensionBrowserAdapter(BrowserAdapter):
    """
    Browser adapter backed by the local extension server.

    Unlike CDPBrowserAdapter, this doesn't need to match a window
    title against a list of tabs — the extension already knows
    exactly which tab is active, so find_active_tab() ignores
    window_title and simply returns the latest fresh report.
    """

    _process_names = [
        "chrome.exe",
        "google-chrome",
        "brave.exe",
        "msedge.exe",
    ]
    _browser_name = "Browser (extension)"

    def __init__(self, max_age: float = extension_server.FRESHNESS_SECONDS):
        self._max_age = max_age

    # ---- BrowserAdapter interface -----------------------------------------

    @property
    def process_names(self) -> list[str]:
        return list(self._process_names)

    @property
    def browser_name(self) -> str:
        return self._browser_name

    def get_page_tabs(self) -> list[dict]:
        """
        The extension only ever reports the single active tab, not
        the full tab list, so this returns at most one tab.
        """

        tab = extension_server.get_latest_tab_data(self._max_age)

        if not tab:
            return []

        return [tab]

    def find_active_tab(self, window_title: str) -> dict | None:
        """
        Return the most recently reported active tab, if fresh.

        window_title is accepted for interface compatibility but
        isn't needed — the extension already tells us which tab is
        active, no title-matching required.
        """

        tab = extension_server.get_latest_tab_data(self._max_age)

        if not tab:
            return None

        return self._enrich_tab(tab)

    # ---- Internal ---------------------------------------------------------

    def _enrich_tab(self, tab: dict) -> dict:

        url = tab.get("url", "")
        title = (tab.get("title") or "").strip()

        return {
            "browser": tab.get("browser") or self._browser_name,
            "title": title,
            "page_title": title,
            "url": url,
            "domain": extract_domain(url),
        }