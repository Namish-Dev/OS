from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


APPLICATION_MAP = {
    "Code.exe": "Visual Studio Code",
    "Antigravity IDE.exe": "Antigravity",
    "Antigravity.exe": "Antigravity",
    "chrome.exe": "Google Chrome",
    "brave.exe": "Brave",
    "Obsidian.exe": "Obsidian",
    "explorer.exe": "File Explorer",
    "SearchHost.exe": "Windows Search",
}


def identify_application(process_name):
    """Convert a process name into a readable application name."""

    if not process_name:
        return "Unknown"

    return APPLICATION_MAP.get(process_name, process_name)


def parse_vscode_title(window_title):

    suffix = " - Visual Studio Code"

    if not window_title or suffix not in window_title:
        return {
            "file": None,
            "workspace": None
        }

    content = window_title.replace(suffix, "").strip()

    parts = [
        part.strip()
        for part in content.split(" - ")
    ]

    if len(parts) >= 2:
        return {
            "file": parts[0],
            "workspace": parts[1]
        }

    return {
        "file": content,
        "workspace": None
    }


def parse_obsidian_title(window_title):

    suffix = " - Obsidian 1.13.7"

    if not window_title or suffix not in window_title:
        return {
            "note": None,
            "vault": None
        }

    content = window_title.replace(suffix, "").strip()

    parts = [
        part.strip()
        for part in content.split(" - ")
    ]

    if len(parts) >= 2:
        return {
            "note": parts[0],
            "vault": parts[1]
        }

    return {
        "note": content,
        "vault": None
    }


def build_context(process_name, window_title):

    application = identify_application(process_name)

    context = {
        "application": application,
        "process": process_name,
        "window_title": window_title
    }

    if application == "Visual Studio Code":

        context.update(
            parse_vscode_title(window_title)
        )

    elif application == "Antigravity":
        from core.context_extractors import parse_antigravity_title
        context.update(
            parse_antigravity_title(window_title)
        )

    elif application == "Obsidian":

        context.update(
            parse_obsidian_title(window_title)
        )

    return context