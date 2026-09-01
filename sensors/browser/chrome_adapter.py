"""
Personal OS — Google Chrome Browser Adapter.

Thin subclass of CDPBrowserAdapter with Chrome-specific configuration.
"""

from sensors.browser.cdp_adapter import CDPBrowserAdapter


class ChromeAdapter(CDPBrowserAdapter):
    """Google Chrome adapter using CDP on port 9222."""

    _port = 9222

    _title_suffixes = [
        " - Google Chrome",
        " - Chrome",
    ]

    _process_names = [
        "chrome.exe",       # Windows
        "google-chrome",    # Linux
    ]

    _browser_name = "Google Chrome"
