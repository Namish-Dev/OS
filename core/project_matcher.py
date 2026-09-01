"""
Personal OS — Project Matcher.

Attributes an event to a project using user-defined keyword rules
from config/projects.json, plus a similar flat list of "distraction"
keywords from config/distractions.json (things like video titles or
domains the user has confirmed are not project-related).

Both lists start empty/small and grow over time via
core/classification_learning.py, whenever the user confirms a
classification through the review flow (activity/review_unclassified.py).
This is intentionally simple and rule-based — smarter/automatic
project detection (clustering related files, repos, and notes
without any manual config) is Phase 5 (Project Intelligence)
territory.

Platform-independent — works purely on already-extracted context
fields, never touches the filesystem or OS APIs directly beyond
reading its own two small JSON config files.
"""

import json
import re
from pathlib import Path

DEFAULT_PROJECTS_PATH = Path(__file__).resolve().parent.parent / "config" / "projects.json"
DEFAULT_DISTRACTIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "distractions.json"

UNASSIGNED = "Unassigned"
DISTRACTION = "Distraction"

# Confidence levels, in order from strongest to weakest evidence.
# A caller (like the review flow) uses this to decide whether a
# match is trustworthy enough to skip asking the user about it.
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_NONE = "none"

# Fields checked for keyword matches, grouped by specificity tier
# (checked highest tier first, mapped 1:1 to the CONFIDENCE_* levels
# above). A match on a specific artifact (an exact filename, note
# title, or page title) is much stronger evidence of intent than a
# match on a broad, repo-wide signal like workspace name — the
# workspace name is identical across every file in that repo, so it
# would otherwise dominate every event and drown out more specific
# signals. Ties within a tier fall back to the longest matching
# keyword, then to config order.
_FIELD_TIERS: list[tuple[str, list[str]]] = [
    (CONFIDENCE_HIGH, ["file", "note", "page_title"]),
    (CONFIDENCE_MEDIUM, ["domain", "url"]),
    (CONFIDENCE_LOW, ["workspace", "vault", "path", "window_title"]),
]


class ProjectMatcher:
    """Matches events to projects/distractions using keyword rules loaded from JSON."""

    def __init__(
        self,
        config_path: Path | str = DEFAULT_PROJECTS_PATH,
        distractions_path: Path | str = DEFAULT_DISTRACTIONS_PATH,
    ):
        self._config_path = Path(config_path)
        self._distractions_path = Path(distractions_path)
        self._projects = self._load_projects(self._config_path)
        self._distraction_keywords = self._load_distractions(self._distractions_path)

    @staticmethod
    def _load_projects(config_path: Path) -> list[dict]:
        """
        Load project definitions from JSON.

        Returns an empty list (everything falls back to Unassigned)
        if the config is missing or malformed — this must never
        crash the sessionizer.
        """

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []

        projects = data.get("projects", [])
        normalized = []

        for project in projects:

            name = project.get("name")
            keywords = project.get("keywords", [])
            workspaces = project.get("workspaces", [])
            vaults = project.get("vaults", [])

            if not name or not (keywords or workspaces or vaults):
                continue

            normalized.append({
                "name": name,
                "keywords": [kw.lower() for kw in keywords if kw],
                "workspaces": [w.lower() for w in workspaces if w],
                "vaults": [v.lower() for v in vaults if v],
            })

        return normalized

    @staticmethod
    def _load_distractions(config_path: Path) -> list[str]:
        """Load the flat distraction keyword list. Missing file = empty list."""

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []

        return [kw.lower() for kw in data.get("keywords", []) if kw]

    def match(self, window_title: str | None, context: dict | None) -> str:
        """
        Return the matched project name, DISTRACTION, or UNASSIGNED.

        Convenience wrapper around match_with_confidence() for callers
        that don't need the confidence level (e.g. the sessionizer).
        """

        label, _confidence = self.match_with_confidence(window_title, context)
        return label

    def match_with_confidence(
        self, window_title: str | None, context: dict | None
    ) -> tuple[str, str]:
        """
        Return (label, confidence).

        label is a project name, DISTRACTION, or UNASSIGNED.
        confidence is one of CONFIDENCE_HIGH/MEDIUM/LOW/NONE,
        indicating how strong the evidence for that label was.

        Checks fields in specificity order (file/note/page_title
        first, then domain/url, then workspace/vault/path/window_title
        last) and returns as soon as anything matches within a tier —
        so a specific match (exact filename) always beats a generic
        one (workspace name), regardless of string length. Within a
        tier, projects and distraction keywords compete on equal
        footing; the longest matching keyword wins, ties fall back to
        config order (projects checked before distractions).
        """

        context = context or {}

        # Exact workspace/vault match — checked FIRST and separately
        # from the fuzzy keyword tiers below. This is a structural,
        # deterministic signal (you told the system "this exact VS
        # Code workspace / Obsidian vault IS this project" once), not
        # a fuzzy guess — so it's trusted at HIGH confidence even
        # when the workspace name itself is short/generic (e.g. "OS"),
        # which would be far too risky to use as a substring keyword.
        workspace = (context.get("workspace") or "").strip().lower()
        vault = (context.get("vault") or "").strip().lower()

        if workspace or vault:
            for project in self._projects:
                if workspace and workspace in project["workspaces"]:
                    return project["name"], CONFIDENCE_HIGH
                if vault and vault in project["vaults"]:
                    return project["name"], CONFIDENCE_HIGH

        for confidence, tier_fields in _FIELD_TIERS:

            best_label = None
            best_keyword_length = -1

            for field in tier_fields:

                value = window_title if field == "window_title" else context.get(field)

                if not value:
                    continue

                value_lower = str(value).lower()

                for project in self._projects:
                    for keyword in project["keywords"]:
                        if keyword in value_lower and len(keyword) > best_keyword_length:
                            best_label = project["name"]
                            best_keyword_length = len(keyword)

                for keyword in self._distraction_keywords:
                    if keyword in value_lower and len(keyword) > best_keyword_length:
                        best_label = DISTRACTION
                        best_keyword_length = len(keyword)

            if best_label:
                return best_label, confidence

        return UNASSIGNED, CONFIDENCE_NONE