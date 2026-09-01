"""
Personal OS — Activity Engine.

The central orchestrator that:
    1. Receives raw foreground observations from any sensor.
    2. Classifies the application.
    3. Extracts context (VS Code, Obsidian, Explorer, browser).
    4. For browsers, attempts enrichment via browser adapters.
    5. Produces a standardized ActivityEvent.
    6. Saves the event to the central database.

This module is completely platform-independent.
It does NOT import any Windows or Linux APIs.
"""

import sys
from pathlib import Path

# Ensure project root is on the path so imports work
# regardless of how the module is invoked.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.event_model import ActivityEvent
from core.app_classifier import classify_application, is_browser
from core.context_extractors import (
    parse_vscode_title,
    parse_antigravity_title,
    parse_obsidian_title,
    parse_explorer_title,
    strip_browser_suffix,
)
from database.database import save_activity_event


class ActivityEngine:
    """
    Transforms raw observations into structured ActivityEvents.

    Usage:
        engine = ActivityEngine(browser_adapters=[ChromeAdapter()])
        event = engine.process_observation("chrome.exe", "GitHub - Google Chrome")
        # → ActivityEvent with url, domain, page_title
    """

    def __init__(self, browser_adapters=None):
        """
        Args:
            browser_adapters: Optional list of BrowserAdapter instances.
                              Each adapter handles specific browser processes.
        """

        self._browser_adapters = browser_adapters or []

        # Build a lookup: process_name → adapter
        self._adapter_map: dict = {}

        for adapter in self._browser_adapters:
            for proc_name in adapter.process_names:
                self._adapter_map[proc_name] = adapter

    def process_observation(
        self,
        process_name: str | None,
        window_title: str | None,
    ) -> ActivityEvent:
        """
        Create an enriched ActivityEvent from a raw observation.

        This is the main entry point. It:
            1. Classifies the application.
            2. Builds context based on application type.
            3. For browsers, enriches with URL/domain from CDP.
            4. Saves to the database.
            5. Returns the structured event.

        Browser enrichment failures are silently caught —
        the event is still created with basic window info.
        """

        application = classify_application(process_name)

        context = self._build_context(
            application, process_name, window_title
        )

        event = ActivityEvent.create(
            application=application,
            process=process_name,
            window_title=window_title,
            context=context,
        )

        # Persist to the central database
        try:
            save_activity_event(event)
        except Exception as exc:
            # Database errors must never crash the tracker
            print(f"[WARNING] Failed to save event: {exc}", file=sys.stderr)

        return event

    # ---- Context building -------------------------------------------------

    def _build_context(
        self,
        application: str,
        process_name: str | None,
        window_title: str | None,
    ) -> dict:
        """
        Build a context dict appropriate for the application type.

        Returns an empty dict if no context can be extracted.
        """

        if application == "Visual Studio Code":
            return parse_vscode_title(window_title)

        if application == "Antigravity":
            return parse_antigravity_title(window_title)

        if application == "Obsidian":
            return parse_obsidian_title(window_title)

        if application == "File Explorer":
            return parse_explorer_title(window_title)

        if is_browser(process_name):
            return self._build_browser_context(process_name, window_title)

        return {}

    def _build_browser_context(
        self,
        process_name: str | None,
        window_title: str | None,
    ) -> dict:
        """
        Attempt to enrich a browser observation with URL/domain data.

        If CDP enrichment fails, returns a basic context with just
        the stripped page title.
        """

        # Basic fallback: at least strip the browser suffix
        page_title = strip_browser_suffix(window_title)

        basic_context = {
            "page_title": page_title,
        }

        # Try CDP enrichment
        adapter = self._adapter_map.get(process_name)

        if not adapter:
            return basic_context

        try:

            tab = adapter.find_active_tab(window_title)

            if tab:
                return tab   # Has page_title, url, domain

        except Exception:
            # Browser debugging unavailable, malformed response, etc.
            # This is fine — we still record the basic context.
            pass

        return basic_context
