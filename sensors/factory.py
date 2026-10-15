"""Select the appropriate foreground sensor without leaking OS APIs upward."""

import platform

from sensors.base import ForegroundSensor


def create_foreground_sensor(system: str | None = None) -> ForegroundSensor:
    """Create the foreground sensor for the current operating system.

    Linux currently supports Hyprland.  Other desktop environments fail with
    an actionable error instead of silently recording misleading data.
    """

    system = (system or platform.system()).lower()

    if system == "windows":
        from sensors.windows.foreground_sensor import WindowsForegroundSensor
        return WindowsForegroundSensor()

    if system == "linux":
        from sensors.linux.hyprland_sensor import HyprlandForegroundSensor
        return HyprlandForegroundSensor()

    raise RuntimeError(f"Unsupported operating system for activity collection: {system}")
