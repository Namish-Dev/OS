"""
Tests for core.context_extractors.

All platform-independent — pure string operations.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.context_extractors import (
    parse_vscode_title,
    parse_antigravity_title,
    parse_obsidian_title,
    parse_explorer_title,
    strip_browser_suffix,
    extract_domain,
    is_internal_url,
)


class TestParseVSCodeTitle:

    def test_file_and_workspace(self):

        result = parse_vscode_title(
            "activity_tracker.py - OS - Visual Studio Code"
        )

        assert result["file"] == "activity_tracker.py"
        assert result["workspace"] == "OS"

    def test_file_only(self):

        result = parse_vscode_title("Welcome - Visual Studio Code")

        assert result["file"] == "Welcome"
        assert result["workspace"] is None

    def test_not_vscode(self):

        result = parse_vscode_title("Something Else")

        assert result["file"] is None
        assert result["workspace"] is None

    def test_none(self):

        result = parse_vscode_title(None)

        assert result["file"] is None
        assert result["workspace"] is None

    def test_empty(self):

        result = parse_vscode_title("")

        assert result["file"] is None
        assert result["workspace"] is None


class TestParseAntigravityTitle:

    def test_file_and_workspace(self):

        result = parse_antigravity_title(
            "OS - Antigravity IDE - view.py"
        )

        assert result["file"] == "view.py"
        assert result["workspace"] == "OS"

    def test_activity_tracker_file(self):

        result = parse_antigravity_title(
            "OS - Antigravity IDE - activity_tracker.py"
        )

        assert result["file"] == "activity_tracker.py"
        assert result["workspace"] == "OS"

    def test_walkthrough_tab(self):

        result = parse_antigravity_title(
            "OS - Antigravity IDE - Walkthrough"
        )

        assert result["file"] == "Walkthrough"
        assert result["workspace"] == "OS"

    def test_workspace_only(self):

        result = parse_antigravity_title("OS - Antigravity IDE")

        assert result["file"] is None
        assert result["workspace"] == "OS"

    def test_file_prefix_format(self):

        result = parse_antigravity_title("Antigravity IDE - main.py")

        assert result["file"] == "main.py"
        assert result["workspace"] is None

    def test_antigravity_short_name(self):

        result = parse_antigravity_title("OS - Antigravity - index.ts")

        assert result["file"] == "index.ts"
        assert result["workspace"] == "OS"

    def test_just_app_name(self):

        assert parse_antigravity_title("Antigravity IDE") == {"file": None, "workspace": None}
        assert parse_antigravity_title("Antigravity") == {"file": None, "workspace": None}

    def test_none(self):

        assert parse_antigravity_title(None) == {"file": None, "workspace": None}

    def test_empty(self):

        assert parse_antigravity_title("") == {"file": None, "workspace": None}


class TestParseObsidianTitle:

    def test_note_and_vault_with_version(self):

        result = parse_obsidian_title(
            "Daily Log - Personal - Obsidian 1.13.7"
        )

        assert result["note"] == "Daily Log"
        assert result["vault"] == "Personal"

    def test_note_and_vault_different_version(self):

        result = parse_obsidian_title(
            "My Note - Vault - Obsidian 2.0.0"
        )

        assert result["note"] == "My Note"
        assert result["vault"] == "Vault"

    def test_obsidian_no_version(self):

        result = parse_obsidian_title("Settings - Obsidian")

        assert result["note"] == "Settings"
        assert result["vault"] is None

    def test_not_obsidian(self):

        result = parse_obsidian_title("Random Window")

        assert result["note"] is None
        assert result["vault"] is None

    def test_none(self):

        result = parse_obsidian_title(None)

        assert result["note"] is None
        assert result["vault"] is None


class TestParseExplorerTitle:

    def test_folder_name(self):

        result = parse_explorer_title("Downloads")

        assert result["path"] == "Downloads"

    def test_empty(self):

        result = parse_explorer_title("")

        assert result["path"] is None

    def test_none(self):

        result = parse_explorer_title(None)

        assert result["path"] is None


class TestStripBrowserSuffix:

    def test_chrome_suffix(self):

        assert strip_browser_suffix("GitHub - Google Chrome") == "GitHub"

    def test_brave_suffix(self):

        assert strip_browser_suffix("YouTube - Brave") == "YouTube"

    def test_edge_suffix(self):

        assert strip_browser_suffix("Bing - Microsoft Edge") == "Bing"

    def test_no_suffix(self):

        assert strip_browser_suffix("Just a Title") == "Just a Title"

    def test_none(self):

        assert strip_browser_suffix(None) is None

    def test_empty(self):

        assert strip_browser_suffix("") is None


class TestExtractDomain:

    def test_simple_url(self):

        assert extract_domain("https://github.com/user/repo") == "github.com"

    def test_www_stripped(self):

        assert extract_domain("https://www.youtube.com/watch?v=123") == "youtube.com"

    def test_subdomain_preserved(self):

        assert extract_domain("https://docs.google.com/") == "docs.google.com"

    def test_chrome_internal(self):
        """chrome:// URLs should return None."""

        assert extract_domain("chrome://settings") is None

    def test_extension_url(self):

        assert extract_domain("chrome-extension://abc123/popup.html") is None

    def test_none(self):

        assert extract_domain(None) is None

    def test_empty(self):

        assert extract_domain("") is None


class TestIsInternalUrl:

    def test_chrome_internal(self):

        assert is_internal_url("chrome://newtab") is True
        assert is_internal_url("chrome://settings") is True

    def test_extension(self):

        assert is_internal_url("chrome-extension://abc/popup.html") is True

    def test_devtools(self):

        assert is_internal_url("devtools://devtools/bundled/inspector.html") is True

    def test_brave_internal(self):

        assert is_internal_url("brave://settings") is True

    def test_normal_url(self):

        assert is_internal_url("https://github.com") is False
        assert is_internal_url("http://localhost:3000") is False

    def test_none_and_empty(self):

        assert is_internal_url(None) is False
        assert is_internal_url("") is False
