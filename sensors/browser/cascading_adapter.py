"""
Personal OS — Cascading Browser Adapter.

Wraps multiple BrowserAdapter instances and tries each in order,
returning the first one that produces a result. Presents itself as
a single BrowserAdapter, so ActivityEngine needs no changes to
support multiple data sources per browser.

Typical use: prefer the extension adapter (works against the user's
normal browser) and fall back to CDP (works only against a
debug-launched browser, but needs no extension installed).

This module is platform-independent.
"""

from sensors.browser.base import BrowserAdapter


class CascadingBrowserAdapter(BrowserAdapter):
    """
    Tries each adapter in `adapters` order for every lookup.
    The first adapter to return a non-empty/non-None result wins.
    """

    def __init__(
        self,
        adapters: list[BrowserAdapter],
        process_names: list[str],
        browser_name: str = "Browser",
    ):
        if not adapters:
            raise ValueError("CascadingBrowserAdapter needs at least one adapter")

        self._adapters = list(adapters)
        self._process_names = list(process_names)
        self._browser_name = browser_name

    # ---- BrowserAdapter interface -----------------------------------------

    @property
    def process_names(self) -> list[str]:
        return list(self._process_names)

    @property
    def browser_name(self) -> str:
        return self._browser_name

    def get_page_tabs(self) -> list[dict]:
        for adapter in self._adapters:
            try:
                tabs = adapter.get_page_tabs()
            except Exception:
                tabs = []

            if tabs:
                return tabs

        return []

    def find_active_tab(self, window_title: str) -> dict | None:
        for adapter in self._adapters:
            try:
                tab = adapter.find_active_tab(window_title)
            except Exception:
                tab = None

            if tab:
                return tab

        return None