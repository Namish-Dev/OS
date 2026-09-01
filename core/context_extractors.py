"""
Personal OS — Context Extractors.

Pure functions that parse window titles into structured context dicts.
No OS-specific dependencies — only string operations.
"""

import re
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# VS Code
# ---------------------------------------------------------------------------

def parse_vscode_title(window_title: str | None) -> dict:
    """
    Extract file and workspace from a VS Code window title.

    Examples:
        "activity_tracker.py - OS - Visual Studio Code"
            → {"file": "activity_tracker.py", "workspace": "OS"}
        "Welcome - Visual Studio Code"
            → {"file": "Welcome", "workspace": None}
    """

    if not window_title:
        return {"file": None, "workspace": None}

    suffix = " - Visual Studio Code"

    if suffix not in window_title:
        return {"file": None, "workspace": None}

    content = window_title.replace(suffix, "").strip()

    parts = [p.strip() for p in content.split(" - ")]

    if len(parts) >= 2:
        return {"file": parts[0], "workspace": parts[1]}

    return {"file": content, "workspace": None}


# ---------------------------------------------------------------------------
# Antigravity IDE
# ---------------------------------------------------------------------------

def parse_antigravity_title(window_title: str | None) -> dict:
    """
    Extract file and workspace from an Antigravity IDE window title.

    Format:
        "<Workspace> - Antigravity IDE - <File>"
        "<Workspace> - Antigravity IDE"
        "Antigravity IDE - <File>"
        "<File> - Antigravity IDE"
        "Antigravity IDE"

    Examples:
        "OS - Antigravity IDE - view.py"
            → {"file": "view.py", "workspace": "OS"}
        "OS - Antigravity IDE - Walkthrough"
            → {"file": "Walkthrough", "workspace": "OS"}
        "OS - Antigravity IDE"
            → {"file": None, "workspace": "OS"}
        "Antigravity IDE - view.py"
            → {"file": "view.py", "workspace": None}
        "Antigravity IDE"
            → {"file": None, "workspace": None}
    """

    if not window_title:
        return {"file": None, "workspace": None}

    title = window_title.strip()
    if not title:
        return {"file": None, "workspace": None}

    # 1. Check for standard 3-part form: "<Workspace> - Antigravity IDE - <File>"
    # or "<Workspace> - Antigravity - <File>"
    for marker in (" - Antigravity IDE - ", " - Antigravity - "):
        if marker in title:
            left, right = title.split(marker, 1)
            return {
                "file": right.strip() or None,
                "workspace": left.strip() or None,
            }

    # 2. Check for suffix: "<Workspace> - Antigravity IDE"
    for suffix in (" - Antigravity IDE", " - Antigravity"):
        if title.endswith(suffix):
            content = title[:-len(suffix)].strip()
            return {
                "file": None,
                "workspace": content or None,
            }

    # 3. Check for prefix: "Antigravity IDE - <File>"
    for prefix in ("Antigravity IDE - ", "Antigravity - "):
        if title.startswith(prefix):
            content = title[len(prefix):].strip()
            return {
                "file": content or None,
                "workspace": None,
            }

    if title in ("Antigravity IDE", "Antigravity"):
        return {"file": None, "workspace": None}

    return {"file": None, "workspace": None}



# ---------------------------------------------------------------------------
# Obsidian  (version-agnostic)
# ---------------------------------------------------------------------------

_OBSIDIAN_SUFFIX_RE = re.compile(r"\s*-\s*Obsidian[\s\d.]*$")


def parse_obsidian_title(window_title: str | None) -> dict:
    """
    Extract note and vault from an Obsidian window title.

    Handles any Obsidian version string (1.13.7, 1.14.0, etc.).

    Examples:
        "Daily Log - Personal - Obsidian 1.13.7"
            → {"note": "Daily Log", "vault": "Personal"}
        "Settings - Obsidian"
            → {"note": "Settings", "vault": None}
    """

    if not window_title:
        return {"note": None, "vault": None}

    match = _OBSIDIAN_SUFFIX_RE.search(window_title)

    if not match:
        return {"note": None, "vault": None}

    content = window_title[:match.start()].strip()

    parts = [p.strip() for p in content.split(" - ")]

    if len(parts) >= 2:
        return {"note": parts[0], "vault": parts[1]}

    return {"note": content, "vault": None}


# ---------------------------------------------------------------------------
# File Explorer
# ---------------------------------------------------------------------------

def parse_explorer_title(window_title: str | None) -> dict:
    """
    Extract the current folder/path from a File Explorer window title.

    The title is usually just the folder name or path.

    Examples:
        "Downloads"   → {"path": "Downloads"}
        "OS"          → {"path": "OS"}
        ""            → {"path": None}
    """

    if not window_title:
        return {"path": None}

    return {"path": window_title.strip() or None}


# ---------------------------------------------------------------------------
# Browser — title stripping
# ---------------------------------------------------------------------------

_BROWSER_SUFFIXES = [
    " - Google Chrome",
    " - Chrome",
    " - Brave",
    " - Microsoft Edge",
    " - Edge",
    " — Google Chrome",
    " — Chrome",
    " — Brave",
    " — Microsoft Edge",
    " — Edge",
    " – Google Chrome",
    " – Chrome",
    " – Brave",
    " – Microsoft Edge",
    " – Edge",
]


def strip_browser_suffix(window_title: str | None) -> str | None:
    """
    Remove the browser name suffix from a window title.

    "GitHub - Google Chrome" → "GitHub"
    "YouTube - Brave"       → "YouTube"
    """

    if not window_title:
        return None

    title = window_title.strip()

    for suffix in _BROWSER_SUFFIXES:
        if title.endswith(suffix):
            return title[:-len(suffix)].strip()

    return title


# ---------------------------------------------------------------------------
# URL / domain helpers
# ---------------------------------------------------------------------------

def extract_domain(url: str | None) -> str | None:
    """
    Extract the domain from a URL.

    "https://www.github.com/user/repo" → "github.com"
    "chrome://settings"                → None  (internal page)
    """

    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    # Ignore internal browser pages
    if parsed.scheme in ("chrome", "brave", "edge", "chrome-extension",
                         "about", "devtools"):
        return None

    hostname = parsed.hostname

    if not hostname:
        return None

    # Strip leading "www."
    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname


def is_internal_url(url: str | None) -> bool:
    """Return True if the URL is an internal browser page."""

    if not url:
        return False

    internal_schemes = (
        "chrome://", "brave://", "edge://",
        "chrome-extension://", "about:", "devtools://",
    )

    return any(url.startswith(s) for s in internal_schemes)
