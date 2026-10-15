"""
Personal OS — Activity Tracker (main entry point).

Runs the observation loop:
    1. A platform-specific foreground sensor detects the active window.
    2. A short-lived candidate window must stay foreground for
       DEBOUNCE_SECONDS before it is treated as real activity.
       This filters out transient, sub-second foreground flickers
       caused by things like Alt-Tab / Task View, which briefly
       report "explorer.exe" as foreground while switching windows.
    3. ActivityEngine classifies, enriches, and stores the event.

Architecture:
    OS sensor  →  debounce  →  activity engine  →  database

The factory currently selects Windows or Hyprland/Linux. The debounce logic
and activity engine remain platform-independent.
"""

import sys
import time
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import create_database
from core.activity_engine import ActivityEngine
from sensors.factory import create_foreground_sensor
from sensors.browser.chrome_adapter import ChromeAdapter
from sensors.browser.extension_adapter import ExtensionBrowserAdapter
from sensors.browser.extension_server import start_server_in_background
from sensors.browser.cascading_adapter import CascadingBrowserAdapter
from sensors.vscode.extension_adapter import VSCodeExtensionAdapter
from sensors.vscode.extension_server import start_server_in_background as start_vscode_server
from sensors.linux.git_context import GitContextCollector


# How long (seconds) a window must remain continuously foreground
# before it is recorded as a real activity event. Filters out
# sub-second flicker from Alt-Tab, Task View, etc.
DEBOUNCE_SECONDS = 1.5

# Poll interval. Kept shorter than DEBOUNCE_SECONDS so the debounce
# window is actually measured with reasonable precision.
POLL_INTERVAL_SECONDS = 0.3

# Record a lightweight observation while the same window stays focused. This
# makes elapsed time evidence-based instead of guessing from window switches.
HEARTBEAT_SECONDS = 60

# Windows whose process reports as "explorer.exe" but are not real
# File Explorer windows (e.g. the Alt-Tab / Task View overlay) tend
# to have an empty or whitespace-only title. Real Explorer windows
# always show a folder name. Skip these immediately, regardless of
# debounce, since they're never legitimate activity.
_EXPLORER_PROCESS = "explorer.exe"


def _is_noise_window(process_name: str | None, window_title: str | None, window_class: str | None = None) -> bool:
    """Return True for windows that should never be recorded."""

    if process_name == _EXPLORER_PROCESS:
        # Only these Win32 classes represent actual Explorer folder windows.
        # Task switcher, desktop shell, and other Explorer-owned surfaces must
        # not become fake file activity.
        if window_class and window_class not in {"CabinetWClass", "ExploreWClass"}:
            return True
        if not (window_title or "").strip():
            return True

    return False


def main():

    # Initialise the database (safe — only creates tables if missing)
    create_database()

    # Platform-specific sensor, selected without importing another OS's APIs.
    sensor = create_foreground_sensor()

    # Local server the Personal OS browser extension reports to.
    # Safe to call even if the extension is never installed — it
    # just sits idle, and browser context falls back to CDP or
    # page-title-only as before.
    start_server_in_background()
    start_vscode_server()

    # Browser context, in priority order:
    #   1. Extension  — works against the user's normal, already-open
    #      browser (Chrome, Brave, Edge), if the extension is installed.
    #   2. CDP         — works only against a debug-launched Chrome
    #      (see scripts/launch_chrome_debug.ps1), but needs no extension.
    #   3. (handled by ActivityEngine itself) page-title-only fallback
    #      if neither source has data.
    chrome = CascadingBrowserAdapter(
        adapters=[ExtensionBrowserAdapter(), ChromeAdapter()],
        process_names=ChromeAdapter().process_names,
        browser_name="Google Chrome",
    )

    # Central engine — platform-independent
    engine = ActivityEngine(
        browser_adapters=[chrome],
        vscode_adapter=VSCodeExtensionAdapter(),
        git_collector=GitContextCollector(),
    )

    print("Personal OS Activity Tracker")
    print("=" * 60)
    print("Tracking active application...")
    print("Press Ctrl+C to stop.\n")

    committed_hwnd = None
    committed_title = None
    last_recorded_at = None

    # The window currently being "timed" — not yet committed as a
    # real event because it hasn't stayed foreground long enough.
    candidate = None  # {"hwnd", "title", "process", "first_seen"}

    try:

        while True:

            observation = sensor.get_foreground()
            now = time.monotonic()

            if observation:

                hwnd = observation.get("hwnd") or observation.get("window_id")
                window_title = observation["window_title"]
                process_name = observation["process"]

                already_committed = (
                    hwnd == committed_hwnd and window_title == committed_title
                )

                if _is_noise_window(process_name, window_title, observation.get("window_class")):
                    candidate = None

                elif already_committed:
                    candidate = None

                    if (
                        last_recorded_at is None
                        or now - last_recorded_at >= HEARTBEAT_SECONDS
                    ):
                        event = engine.process_observation(
                            process_name,
                            window_title,
                            observation.get("context"),
                        )
                        print(event)
                        last_recorded_at = now

                elif candidate and candidate["hwnd"] == hwnd and candidate["title"] == window_title:

                    # Same candidate as last tick — check if it's been
                    # foreground long enough to count as real activity.
                    if now - candidate["first_seen"] >= DEBOUNCE_SECONDS:

                        event = engine.process_observation(
                            process_name,
                            window_title,
                            observation.get("context"),
                        )

                        print(event)

                        committed_hwnd = hwnd
                        committed_title = window_title
                        last_recorded_at = now
                        candidate = None

                else:

                    # A new, different window — start timing it.
                    candidate = {
                        "hwnd": hwnd,
                        "title": window_title,
                        "process": process_name,
                        "first_seen": now,
                    }

            else:
                candidate = None
                committed_hwnd = None
                committed_title = None
                last_recorded_at = None

            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:

        print("\nActivity tracker stopped.")


if __name__ == "__main__":
    main()
