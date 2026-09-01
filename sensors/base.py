"""
Personal OS — Abstract Foreground Sensor Interface.

Every platform must implement this interface.
The core system only depends on this abstraction.
"""

from abc import ABC, abstractmethod


class ForegroundSensor(ABC):
    """
    Detects which application window is currently in the foreground.

    Platform implementations:
        sensors/windows/foreground_sensor.py  — Windows (ctypes)
        sensors/linux/foreground_sensor.py    — Linux/X11 or Wayland (future)
    """

    @abstractmethod
    def get_foreground(self) -> dict | None:
        """
        Return information about the current foreground window.

        Returns:
            dict with at least:
                "process"       — executable name (str)
                "window_title"  — window title text (str)
            or None if no foreground window can be detected.
        """
