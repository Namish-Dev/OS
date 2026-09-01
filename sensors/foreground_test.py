import time
import win32gui
import win32process
import psutil


print("Foreground Window Monitor")
print("Press Ctrl+C to stop.")
print("=" * 60)

last_hwnd = None

try:

    while True:

        hwnd = win32gui.GetForegroundWindow()

        if hwnd != last_hwnd:

            last_hwnd = hwnd

            title = win32gui.GetWindowText(hwnd)

            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            try:
                process = psutil.Process(pid)
                process_name = process.name()

            except psutil.Error:
                process_name = "unknown"

            print()
            print("PROCESS:", process_name)
            print("TITLE:  ", title)

        time.sleep(0.5)

except KeyboardInterrupt:

    print("\nStopped.")