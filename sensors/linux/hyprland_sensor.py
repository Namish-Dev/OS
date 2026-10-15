"""Hyprland foreground-window sensor.

Hyprland exposes the active client through its local IPC command-line
interface.  This sensor deliberately reads only window metadata that Hyprland
already exposes: application class, title, address and workspace.  It never
captures screen contents or keyboard input.
"""

import json
import subprocess
from collections.abc import Callable

from sensors.base import ForegroundSensor


class HyprlandUnavailableError(RuntimeError):
    """Raised when Hyprland IPC cannot provide an active window."""


class HyprlandForegroundSensor(ForegroundSensor):
    """Read the focused Hyprland client using ``hyprctl -j activewindow``.

    ``runner`` is injectable to keep parsing fully testable without a running
    Hyprland session.  The default runner has a short timeout: activity
    collection must never stall the tracker.
    """

    def __init__(self, runner: Callable[[], str] | None = None):
        self._runner = runner or self._run_hyprctl

    @staticmethod
    def _run_hyprctl() -> str:
        try:
            result = subprocess.run(
                ["hyprctl", "-j", "activewindow"],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise HyprlandUnavailableError(
                "Could not read Hyprland's active window via hyprctl."
            ) from exc

        return result.stdout

    def get_foreground(self) -> dict | None:
        try:
            raw_window = self._runner()
            window = json.loads(raw_window)
        except (HyprlandUnavailableError, TypeError, ValueError, json.JSONDecodeError):
            return None

        if not isinstance(window, dict) or not window.get("address"):
            return None

        title = (window.get("title") or "").strip()
        process = self._process_name(window)
        if not title or not process:
            return None

        workspace = window.get("workspace") or {}
        context = {
            "workspace": workspace.get("name") or workspace.get("id"),
            "hyprland_address": window.get("address"),
            "window_class": window.get("class"),
            "window_pid": window.get("pid"),
            "is_floating": bool(window.get("floating")),
            "is_fullscreen": bool(window.get("fullscreen")),
        }

        return {
            "process": process,
            "window_title": title,
            "window_id": window.get("address"),
            "context": {key: value for key, value in context.items() if value is not None},
        }

    @staticmethod
    def _process_name(window: dict) -> str | None:
        """Prefer the initial class because it is stable across title changes."""

        value = window.get("initialClass") or window.get("class")
        if not value:
            return None

        # Hyprland supplies a desktop-app class, not always an executable.
        # Lowercasing keeps it compatible with the Linux application map.
        return str(value).strip().lower() or None
