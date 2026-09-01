import requests
import win32gui
import win32process
import psutil


PORT = 9222


def get_active_window():

    hwnd = win32gui.GetForegroundWindow()

    if not hwnd:
        return None

    window_title = win32gui.GetWindowText(hwnd)

    _, pid = win32process.GetWindowThreadProcessId(hwnd)

    try:
        process = psutil.Process(pid)
        process_name = process.name()
    except psutil.Error:
        process_name = None

    return {
        "window_title": window_title,
        "process": process_name
    }


def get_browser_tabs():

    try:

        response = requests.get(
            f"http://127.0.0.1:{PORT}/json",
            timeout=2
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException:

        return []


def get_page_tabs():

    tabs = get_browser_tabs()

    return [
        tab
        for tab in tabs
        if tab.get("type") == "page"
    ]


def find_active_chrome_tab(window_title):

    tabs = get_page_tabs()

    if not window_title:
        return None

    cleaned_title = window_title.strip()

    suffixes = [
        " - Google Chrome",
        " - Chrome"
    ]

    for suffix in suffixes:

        if cleaned_title.endswith(suffix):

            cleaned_title = cleaned_title[
                :-len(suffix)
            ].strip()

            break

    cleaned_title = cleaned_title.lower()

    # Exact match
    for tab in tabs:

        title = (
            tab.get("title") or ""
        ).strip().lower()

        if title == cleaned_title:

            return tab

    # Partial match
    for tab in tabs:

        title = (
            tab.get("title") or ""
        ).strip().lower()

        if (
            cleaned_title in title
            or title in cleaned_title
        ):

            return tab

    return None


def detect_browser_context():

    active_window = get_active_window()

    if not active_window:
        return None

    process = active_window["process"]
    window_title = active_window["window_title"]

    if process != "chrome.exe":
        return None

    tab = find_active_chrome_tab(window_title)

    if not tab:
        return {
            "application": "Google Chrome",
            "process": process,
            "window_title": window_title,
            "browser_tab_found": False
        }

    return {
        "application": "Google Chrome",
        "process": process,
        "window_title": window_title,
        "title": tab.get("title"),
        "url": tab.get("url"),
        "browser_tab_found": True
    }


if __name__ == "__main__":

    print("Personal OS Browser Sensor")
    print("=" * 60)

    context = detect_browser_context()

    if context:

        for key, value in context.items():

            print(f"{key}: {value}")

    else:

        print("Chrome is not the active application.")