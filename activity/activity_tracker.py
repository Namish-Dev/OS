"""
Personal OS — Activity Tracker (main entry point).

Runs the observation loop:
    1. A platform-specific foreground sensor detects the active window.
    2. A candidate window must stay foreground for DEBOUNCE_SECONDS before
       it is recorded as real activity, filtering out transient flickers
       (e.g. Alt-Tab / Task View).
    3. Avoids duplicate events when nothing has changed.
    4. Records heartbeat events at regular intervals for continuous focus.
    5. Normalizes observations into standardized raw ActivityEvents and persists them to SQLite.

Architecture:
    Sensors  →  Debounce / Normalization  →  ActivityEngine  →  SQLite Persistence
"""

import platform
import sys
import time
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH, create_database
from core.activity_engine import ActivityEngine
from core.event_model import ActivityEvent
from sensors.factory import create_foreground_sensor
from sensors.browser.chrome_adapter import ChromeAdapter
from sensors.browser.extension_adapter import ExtensionBrowserAdapter
from sensors.browser.extension_server import start_server_in_background
from sensors.browser.cascading_adapter import CascadingBrowserAdapter
from sensors.vscode.extension_adapter import VSCodeExtensionAdapter
from sensors.vscode.extension_server import start_server_in_background as start_vscode_server
from sensors.filesystem_watcher import FilesystemWatcher
from sensors.terminal_receiver import start_terminal_receiver, stop_terminal_receiver


DEBOUNCE_SECONDS = 1.5
POLL_INTERVAL_SECONDS = 0.3
HEARTBEAT_SECONDS = 60
_EXPLORER_PROCESS = "explorer.exe"


def is_noise_window(
    process_name: str | None,
    window_title: str | None,
    window_class: str | None = None,
) -> bool:
    """Return True for windows that should never be recorded as user activity."""

    if process_name == _EXPLORER_PROCESS:
        if window_class and window_class not in {"CabinetWClass", "ExploreWClass"}:
            return True
        if not (window_title or "").strip():
            return True

    return False


class ActivityTracker:
    """
    Coordinates sensors, debounce logic, event normalization, and persistence.
    """

    def __init__(
        self,
        sensor=None,
        engine=None,
        debounce_seconds: float = DEBOUNCE_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ):
        self.sensor = sensor or create_foreground_sensor()
        self.engine = engine or ActivityEngine()
        self.debounce_seconds = debounce_seconds
        self.heartbeat_seconds = heartbeat_seconds

        self.committed_hwnd = None
        self.committed_title = None
        self.committed_process = None
        self.last_recorded_at = None
        self.candidate = None
        self.running = False

    def step(self, current_time: float | None = None) -> ActivityEvent | None:
        """
        Execute one observation cycle.
        Returns the recorded ActivityEvent if one was generated, or None.
        """

        now = time.monotonic() if current_time is None else current_time
        try:
            observation = self.sensor.get_foreground()
        except Exception as exc:
            print(f"[WARNING] Sensor error: {exc}", file=sys.stderr)
            return None

        if not observation:
            self.candidate = None
            self.committed_hwnd = None
            self.committed_title = None
            self.committed_process = None
            self.last_recorded_at = None
            return None

        hwnd = observation.get("hwnd") or observation.get("window_id")
        window_title = observation.get("window_title", "")
        process_name = observation.get("process")
        pid = observation.get("pid")
        window_class = observation.get("window_class")
        sensor_context = observation.get("context")

        if is_noise_window(process_name, window_title, window_class):
            self.candidate = None
            return None

        already_committed = (
            hwnd == self.committed_hwnd
            and window_title == self.committed_title
            and process_name == self.committed_process
        )

        if already_committed:
            self.candidate = None
            # Heartbeat check: record periodic observation if focused continuously
            if (
                self.last_recorded_at is None
                or now - self.last_recorded_at >= self.heartbeat_seconds
            ):
                event = self.engine.process_observation(
                    process_name=process_name,
                    window_title=window_title,
                    sensor_context=sensor_context,
                    pid=pid,
                    event_type="heartbeat",
                )
                self.last_recorded_at = now
                return event
            return None

        if (
            self.candidate
            and self.candidate["hwnd"] == hwnd
            and self.candidate["title"] == window_title
            and self.candidate["process"] == process_name
        ):
            # Same candidate as last tick: verify debounce duration
            if now - self.candidate["first_seen"] >= self.debounce_seconds:
                event = self.engine.process_observation(
                    process_name=process_name,
                    window_title=window_title,
                    sensor_context=sensor_context,
                    pid=pid,
                    event_type="app_foreground",
                )
                self.committed_hwnd = hwnd
                self.committed_title = window_title
                self.committed_process = process_name
                self.last_recorded_at = now
                self.candidate = None
                return event
            return None

        # Different window: start candidate debounce timer
        self.candidate = {
            "hwnd": hwnd,
            "title": window_title,
            "process": process_name,
            "first_seen": now,
        }
        return None

    def start(self, poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
        """Run observation loop until stopped or interrupted."""
        self.running = True
        try:
            while self.running:
                event = self.step()
                if event:
                    print(event)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop tracking cleanly."""
        self.running = False


def print_sensor_status(sensor, chrome_adapter) -> None:
    """Print the operational status of all tracking sensors."""
    print("Personal OS Activity Tracker")
    print("=" * 60)
    print("Sensor status:")

    # OS Foreground Sensor
    sensor_name = sensor.__class__.__name__
    print(f"  [Active] Foreground Sensor: {sensor_name} ({platform.system()})")

    # Browser Extension Server
    print("  [Active] Browser Extension Receiver: http://127.0.0.1:9333/tab")

    # VS Code Extension Server
    print("  [Active] VS Code Extension Receiver: http://127.0.0.1:8766/v1/context")

    # Development evidence capture
    print(f"  [Active] Filesystem Watcher: {PROJECT_ROOT}")
    print("  [Active] Terminal Event Receiver: http://127.0.0.1:8767/v1/terminal-event")

    # Chrome CDP Adapter check
    try:
        tabs = chrome_adapter.get_page_tabs()
        print(f"  [Active] Chrome DevTools Protocol (CDP port 9222): connected ({len(tabs)} tabs)")
    except Exception:
        print("  [Standby] Chrome DevTools Protocol (CDP port 9222): not attached (will use extension / window title fallback)")

    print("=" * 60)
    print("Tracking active application and interactions...")
    print("Press Ctrl+C to stop.\n")


def main():
    # 1. Initialize SQLite database and ensure tables/indexes exist
    create_database()

    # 2. Select platform-specific foreground sensor
    sensor = create_foreground_sensor()

    # 3. Start local receivers for browser and IDE extensions
    start_server_in_background()
    start_vscode_server()

    # 4. Configure browser adapters
    chrome = CascadingBrowserAdapter(
        adapters=[ExtensionBrowserAdapter(), ChromeAdapter()],
        process_names=ChromeAdapter().process_names,
        browser_name="Google Chrome",
    )

    # 5. Initialize central activity engine
    engine = ActivityEngine(
        browser_adapters=[chrome],
        vscode_adapter=VSCodeExtensionAdapter(),
    )

    tracker = ActivityTracker(sensor=sensor, engine=engine)
    watcher = FilesystemWatcher(
        watch_paths=[PROJECT_ROOT],
        database_path=DATABASE_PATH,
    )

    try:
        start_terminal_receiver(database_path=DATABASE_PATH)
        watcher.start()
        print_sensor_status(sensor, chrome)
        tracker.start()
    finally:
        watcher.stop()
        stop_terminal_receiver()

    print("\nActivity tracker stopped cleanly.")


if __name__ == "__main__":
    main()
