"""
Personal OS — Application Classifier.

Maps raw process names to human-readable application names.
Completely platform-independent: the map just contains strings.

Windows sensors feed Windows process names.
Linux sensors will feed Linux process names.
Both are looked up in the same map.
"""


APPLICATION_MAP = {
    # Windows process names
    "Code.exe":             "Visual Studio Code",
    "Antigravity IDE.exe":   "Antigravity",
    "Antigravity.exe":       "Antigravity",
    "chrome.exe":           "Google Chrome",
    "brave.exe":            "Brave",
    "msedge.exe":           "Microsoft Edge",
    "Obsidian.exe":         "Obsidian",
    "explorer.exe":         "File Explorer",
    "SearchHost.exe":       "Windows Search",

    # Linux process names (ready for Phase 2+)
    "code":                 "Visual Studio Code",
    "antigravity":          "Antigravity",
    "antigravity-ide":      "Antigravity",
    "google-chrome":        "Google Chrome",
    "brave-browser":    "Brave",
    "msedge":           "Microsoft Edge",
    "obsidian":         "Obsidian",
    "nautilus":         "Files",
    "dolphin":          "Dolphin",
    "thunar":           "Thunar",
}


# Process names that correspond to a browser application.
# Used by the activity engine to decide whether to attempt browser enrichment.
BROWSER_PROCESSES = {
    "chrome.exe",   "google-chrome",
    "brave.exe",    "brave-browser",
    "msedge.exe",   "msedge",
}


def classify_application(process_name: str | None) -> str:
    """
    Return a human-readable application name for *process_name*.

    If the process is not in the map, return the raw name unchanged.
    If *process_name* is None or empty, return "Unknown".
    """

    if not process_name:
        return "Unknown"

    return APPLICATION_MAP.get(process_name, APPLICATION_MAP.get(process_name.lower(), process_name))


def is_browser(process_name: str | None) -> bool:
    """Return True if the process is a known browser."""

    if not process_name:
        return False

    return process_name in BROWSER_PROCESSES or process_name.lower() in BROWSER_PROCESSES
