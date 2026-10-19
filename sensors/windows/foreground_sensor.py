"""
Personal OS — Windows Foreground Sensor.

Uses ctypes to call Win32 APIs for foreground window detection.
This is the ONLY module that depends on Windows-specific APIs
for the main tracker.

When we move to Linux, this module will be replaced by a
Linux-specific implementation (X11/Wayland) that produces
the exact same output format.
"""

import ctypes
from ctypes import wintypes

from sensors.base import ForegroundSensor


# Win32 API handles
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


class WindowsForegroundSensor(ForegroundSensor):
    """
    Detects the foreground window on Windows using ctypes.

    Returns:
        {"process": "chrome.exe", "window_title": "GitHub - Google Chrome"}
    """

    def get_foreground(self) -> dict | None:
        """Return the current foreground window's process and title."""

        hwnd = _user32.GetForegroundWindow()

        if not hwnd:
            return None

        window_title = self._get_window_title(hwnd)

        if not window_title:
            return None

        process_id = self._get_process_id(hwnd)
        process_name = self._get_process_name(process_id)

        return {
            "process": process_name,
            "window_title": window_title,
            "window_class": self._get_window_class(hwnd),
            "hwnd": hwnd,
            "pid": process_id,
        }

    # ---- Win32 wrappers ---------------------------------------------------

    @staticmethod
    def _get_window_title(hwnd) -> str | None:
        """Return the title text of a window handle."""

        length = _user32.GetWindowTextLengthW(hwnd)

        if length == 0:
            return None

        buffer = ctypes.create_unicode_buffer(length + 1)

        _user32.GetWindowTextW(hwnd, buffer, length + 1)

        return buffer.value or None

    @staticmethod
    def _get_window_class(hwnd) -> str | None:
        """Return the Win32 class so Explorer shell surfaces can be filtered."""
        buffer = ctypes.create_unicode_buffer(256)
        length = _user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value[:length] or None

    @staticmethod
    def _get_process_id(hwnd) -> int:
        """Return the PID for a window handle."""

        pid = wintypes.DWORD()

        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        return pid.value

    @staticmethod
    def _get_process_name(pid: int) -> str | None:
        """Return the executable name for a PID."""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        handle = _kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )

        if not handle:
            return None

        try:

            buf_size = wintypes.DWORD(260)
            buf = ctypes.create_unicode_buffer(260)

            success = _kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(buf_size)
            )

            if success:
                # Extract just the executable name from the full path
                return buf.value.split("\\")[-1]

            return None

        finally:
            _kernel32.CloseHandle(handle)
