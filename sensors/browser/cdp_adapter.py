"""
Personal OS — Chrome DevTools Protocol Adapter.

Communicates with any Chromium-based browser via the Chrome DevTools
Protocol (CDP) over HTTP. This module is completely platform-independent.

The adapter:
    1. Fetches all tabs from http://127.0.0.1:{port}/json
    2. Filters to real user pages (type == "page", no internal URLs)
    3. Matches the OS foreground window title against tab titles

This is used by chrome_adapter.py (and can be reused by brave/edge later).
"""

import re
import requests

from core.context_extractors import (
    extract_domain,
    is_internal_url,
    strip_browser_suffix,
)
from sensors.browser.base import BrowserAdapter


class CDPBrowserAdapter(BrowserAdapter):
    """
    Browser adapter built on the Chrome DevTools Protocol.

    Subclasses only need to set:
        _port            — debugging port
        _title_suffixes  — window title suffixes to strip
        _process_names   — OS process names for this browser
        _browser_name    — human-readable name
    """

    _port: int = 9222
    _title_suffixes: list[str] = [" - Google Chrome", " - Chrome"]
    _process_names: list[str] = ["chrome.exe", "google-chrome"]
    _browser_name: str = "Google Chrome"
    _timeout: float = 2.0

    # ---- BrowserAdapter interface -----------------------------------------

    @property
    def process_names(self) -> list[str]:
        return list(self._process_names)

    @property
    def browser_name(self) -> str:
        return self._browser_name

    def get_page_tabs(self) -> list[dict]:
        """Fetch real user-visible page tabs from the CDP endpoint."""

        raw_tabs = self._fetch_tabs()

        return [
            tab for tab in raw_tabs
            if self._is_user_page(tab)
        ]

    def find_active_tab(self, window_title: str) -> dict | None:
        """
        Match the OS window title to a CDP tab.

        Strategy:
            1. Strip the browser suffix from the window title.
            2. Strip notification badges (e.g. "(1) ") if present.
            3. Try exact match against tab titles.
            4. Fall back to partial/substring match.
        """

        if not window_title:
            return None

        tabs = self.get_page_tabs()

        if not tabs:
            return None

        # Strip browser suffix: "GitHub - Google Chrome" → "GitHub"
        cleaned = strip_browser_suffix(window_title)

        if not cleaned:
            return None

        cleaned_lower = cleaned.lower()
        normalized_cleaned = re.sub(r"^(?:\(\d+\+?\)|[•*])\s*", "", cleaned_lower).strip()

        # Pass 1: exact match (case-insensitive)
        for tab in tabs:

            tab_title = (tab.get("title") or "").strip()
            tab_title_lower = tab_title.lower()
            normalized_tab = re.sub(r"^(?:\(\d+\+?\)|[•*])\s*", "", tab_title_lower).strip()

            if tab_title_lower == cleaned_lower or (normalized_cleaned and normalized_tab == normalized_cleaned):
                return self._enrich_tab(tab)

        # Pass 2: substring match
        for tab in tabs:

            tab_title = (tab.get("title") or "").strip().lower()
            normalized_tab = re.sub(r"^(?:\(\d+\+?\)|[•*])\s*", "", tab_title).strip()

            if (
                cleaned_lower in tab_title
                or tab_title in cleaned_lower
                or (normalized_cleaned and normalized_cleaned in normalized_tab)
                or (normalized_tab and normalized_tab in normalized_cleaned)
            ):
                return self._enrich_tab(tab)

        return None

    # ---- Internal ---------------------------------------------------------

    def _fetch_tabs(self) -> list[dict]:
        """HTTP GET to the CDP /json endpoint."""

        try:

            response = requests.get(
                f"http://127.0.0.1:{self._port}/json",
                timeout=self._timeout,
            )

            response.raise_for_status()

            data = response.json()

            if not isinstance(data, list):
                return []

            return data

        except (requests.RequestException, ValueError):
            return []

    @staticmethod
    def _is_user_page(tab: dict) -> bool:
        """
        Return True only for real user-visible pages.

        Filters out:
            - Non-page types (iframe, background_page, service_worker, etc.)
            - Internal browser URLs (chrome://, devtools://, extensions, etc.)
        """

        # Must be type "page"
        if tab.get("type") != "page":
            return False

        url = tab.get("url", "")

        # Filter internal URLs
        if is_internal_url(url):
            return False

        return True

    def _enrich_tab(self, tab: dict) -> dict:
        """Build a clean result dict from a raw CDP tab entry."""

        url = tab.get("url", "")
        title = (tab.get("title") or "").strip()

        return {
            "browser": self._browser_name,
            "title": title,
            "page_title": title,
            "url": url,
            "domain": extract_domain(url),
        }

