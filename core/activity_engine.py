"""
Personal OS — Activity Engine.

The central orchestrator that:
    1. Receives raw foreground observations from any sensor.
    2. Classifies the application name from the process name.
    3. Extracts context (VS Code, Antigravity, Obsidian, Explorer, browser).
    4. For browsers, attempts enrichment via browser adapters.
    5. Produces a standardized ActivityEvent.
    6. Saves the raw event to the database.

This module is completely platform-independent.
It does NOT import any Windows or Linux APIs.
"""

import sys
from pathlib import Path

# Ensure project root is on the path so imports work
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
    sanitize_url,
)
from database.database import save_activity_event


class ActivityEngine:
    """
    Transforms raw observations into structured ActivityEvents and persists them.

    Usage:
        engine = ActivityEngine(browser_adapters=[chrome_adapter])
        event = engine.process_observation("chrome.exe", "GitHub - Google Chrome")
    """

    def __init__(self, browser_adapters=None, vscode_adapter=None, git_collector=None):
        """
        Args:
            browser_adapters: Optional list of BrowserAdapter instances.
            vscode_adapter: Optional VSCodeExtensionAdapter instance.
            git_collector: Deprecated/ignored parameter kept for backward compatibility.
        """

        self._browser_adapters = browser_adapters or []
        self._vscode_adapter = vscode_adapter
        self._git_collector = git_collector

        # Build a lookup: process_name → adapter
        self._adapter_map: dict = {}
        for adapter in self._browser_adapters:
            for proc_name in adapter.process_names:
                self._adapter_map[proc_name] = adapter

    def record_event(self, event: ActivityEvent) -> ActivityEvent:
        """Persist an already constructed ActivityEvent directly to the database."""
        try:
            save_activity_event(event)
        except Exception as exc:
            print(f"[WARNING] Failed to save event: {exc}", file=sys.stderr)
        return event

    def process_observation(
        self,
        process_name: str | None,
        window_title: str | None,
        sensor_context: dict | None = None,
        sensor: str | None = None,
        pid: int | None = None,
        event_type: str = "app_foreground",
    ) -> ActivityEvent:
        """
        Create a standardized ActivityEvent from a raw observation and persist it.

        This is the main entry point:
            1. Classifies the application name.
            2. Builds context based on application type.
            3. For browsers, enriches with URL/domain from adapters.
            4. Persists the raw event to the database.
            5. Returns the structured ActivityEvent.
        """

        application = classify_application(process_name)

        context = self._build_context(application, process_name, window_title)

        # Merge sensor context facts (e.g. Hyprland workspace or address)
        if sensor_context:
            for key, value in sensor_context.items():
                if value is not None and context.get(key) is None:
                    context[key] = value

        # Determine PID
        effective_pid = pid
        if effective_pid is None and sensor_context:
            effective_pid = sensor_context.get("pid") or sensor_context.get("window_pid")

        # Determine Sensor Name
        effective_sensor = sensor
        if effective_sensor is None and sensor_context:
            effective_sensor = sensor_context.get("sensor")

        event = ActivityEvent.create(
            application=application,
            process=process_name,
            window_title=window_title,
            context=context,
            event_type=event_type,
            sensor=effective_sensor,
            pid=effective_pid,
        )

        # Persist to the database
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
        """Build a context dict appropriate for the application type."""

        if application == "Visual Studio Code":
            context = parse_vscode_title(window_title)
            if self._vscode_adapter:
                try:
                    extension_context = self._vscode_adapter.get_context()
                except Exception:
                    extension_context = {}
                for key, value in extension_context.items():
                    if value is not None:
                        context[key] = value
            return context

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
        """Attempt to enrich a browser observation with URL/domain data."""

        # Basic fallback: strip browser suffix from window title
        page_title = strip_browser_suffix(window_title)

        basic_context = {
            "page_title": page_title,
        }

        adapter = self._adapter_map.get(process_name)
        if not adapter:
            return basic_context

        try:
            tab = adapter.find_active_tab(window_title)

            if tab:
                normalized = dict(basic_context)
                for key, value in tab.items():
                    if value is not None:
                        normalized[key] = value

                # Privacy-safe sanitization of URLs
                if normalized.get("url"):
                    normalized["url"] = sanitize_url(normalized["url"])

                # Normalize generic page titles
                generic_titles = {"youtube", "google chrome", "new tab", "localhost"}
                if (
                    str(normalized.get("page_title") or "").strip().lower() in generic_titles
                    and page_title
                    and page_title.strip().lower() not in generic_titles
                ):
                    normalized["page_title"] = page_title

                if not normalized.get("page_title"):
                    normalized["page_title"] = page_title

                return normalized

        except Exception:
            # Browser adapter unavailable, network timeout, etc.
            # Continue gracefully with basic context.
            pass

        return basic_context
