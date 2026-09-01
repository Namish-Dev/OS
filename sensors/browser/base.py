"""
Personal OS — Abstract Browser Adapter Interface.

Each supported browser (Chrome, Brave, Edge) gets an adapter
that implements this interface. The activity engine asks the
adapter for the active tab matching the foreground window title.

The adapter itself is platform-independent — it communicates
with the browser via the Chrome DevTools Protocol over HTTP.
"""

from abc import ABC, abstractmethod


class BrowserAdapter(ABC):
    """
    Connects to a browser's debugging interface and identifies
    the currently active tab by matching against a window title.
    """

    @abstractmethod
    def get_page_tabs(self) -> list[dict]:
        """
        Return all open tabs that are real user pages.

        Must filter OUT:
            - type == "iframe"
            - type == "browser_ui"
            - type == "background_page"
            - type == "service_worker"
            - chrome-extension:// URLs
            - chrome:// / brave:// / edge:// internal pages
            - devtools:// pages

        Each dict should have at least: "title", "url", "type".
        """

    @abstractmethod
    def find_active_tab(self, window_title: str) -> dict | None:
        """
        Find the tab that matches the browser's foreground window title.

        Args:
            window_title: The raw OS window title, e.g.
                          "GitHub - Google Chrome"

        Returns:
            A dict with "title" and "url" for the matched tab,
            or None if no match is found.
        """

    @property
    @abstractmethod
    def process_names(self) -> list[str]:
        """
        Return process names this adapter handles.

        Example: ["chrome.exe", "google-chrome"]
        """

    @property
    @abstractmethod
    def browser_name(self) -> str:
        """Human-readable browser name, e.g. 'Google Chrome'."""
