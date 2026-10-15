"""
Personal OS — Classification Learning.

When the user confirms "this belongs to Project X" or "this is a
distraction", we don't build a separate ML/fuzzy-matching system —
we extract distinctive keywords from the confirmed content and add
them to the existing keyword-based config (config/projects.json or
config/distractions.json). Future content containing those same
words is then matched automatically by the existing ProjectMatcher,
with no further prompting.

This keeps "learning" fully explainable and inspectable: the user
can always open projects.json and see exactly what the system has
learned, and remove anything wrong.

Platform-independent — pure string/JSON logic, no OS or DB access.
"""

import json
import re
from pathlib import Path

# Common words that make poor keywords — too generic to distinguish
# one project/topic from another.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for",
    "with", "is", "are", "this", "that", "how", "what", "why", "your",
    "you", "full", "complete", "part", "video", "watch", "official",
    "new", "best", "top", "vs", "by", "at", "from", "into",
    # Generic content-type words: keeping these would make almost any
    # tutorial/video match, which defeats the purpose of a keyword.
    "tutorial", "guide", "explained", "course", "lesson", "episode",
}

_WORD_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+\-\.]{2,}")


def extract_keywords(text: str, existing_keywords: set[str], max_new: int = 3) -> list[str]:
    """
    Return up to `max_new` distinctive candidate keywords from `text`
    that aren't already in `existing_keywords` (case-insensitive) and
    aren't stopwords.

    This is intentionally simple word-extraction, not NLP — it's meant
    to be predictable and inspectable, not maximally clever.
    """

    if not text:
        return []

    existing_lower = {kw.lower() for kw in existing_keywords}
    candidates: list[str] = []

    for match in _WORD_PATTERN.finditer(text.lower()):

        word = match.group(0)

        if word in _STOPWORDS or word in existing_lower or word in candidates:
            continue

        candidates.append(word)

        if len(candidates) >= max_new:
            break

    return candidates


def load_json(config_path: Path) -> dict:
    """Load a JSON config file, returning {} if it doesn't exist yet."""

    if not config_path.exists():
        return {}

    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def save_json(config_path: Path, data: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_project_keywords(config_path: Path, project_name: str, new_keywords: list[str]) -> None:
    """
    Add `new_keywords` to the named project in projects.json.
    Creates the project entry if it doesn't already exist.
    No-op for keywords that are already present (case-insensitive).
    """

    if not new_keywords:
        return

    data = load_json(config_path)
    projects = data.setdefault("projects", [])

    for project in projects:
        if project.get("name") == project_name:
            existing = {kw.lower() for kw in project.get("keywords", [])}
            keywords = project.setdefault("keywords", [])
            for kw in new_keywords:
                if kw.lower() not in existing:
                    keywords.append(kw)
                    existing.add(kw.lower())
            break
    else:
        projects.append({"name": project_name, "keywords": list(new_keywords)})

    save_json(config_path, data)


def add_project_workspace(config_path: Path, project_name: str, workspace: str) -> None:
    """
    Record an exact-match workspace association for a project — e.g.
    "the VS Code workspace named 'OS' IS the Personal OS project".

    Unlike add_project_keywords(), this is an exact-match signal, not
    a fuzzy substring keyword — safe even for short/generic workspace
    names, and once set, every future file in that exact workspace
    matches automatically with no further review needed.
    """

    if not workspace:
        return

    data = load_json(config_path)
    projects = data.setdefault("projects", [])

    for project in projects:
        if project.get("name") == project_name:
            existing = {w.lower() for w in project.get("workspaces", [])}
            if workspace.lower() not in existing:
                project.setdefault("workspaces", []).append(workspace)
            break
    else:
        projects.append({"name": project_name, "keywords": [], "workspaces": [workspace]})

    save_json(config_path, data)


def add_project_vault(config_path: Path, project_name: str, vault: str) -> None:
    """Same as add_project_workspace(), for an Obsidian vault name."""

    if not vault:
        return

    data = load_json(config_path)
    projects = data.setdefault("projects", [])

    for project in projects:
        if project.get("name") == project_name:
            existing = {v.lower() for v in project.get("vaults", [])}
            if vault.lower() not in existing:
                project.setdefault("vaults", []).append(vault)
            break
    else:
        projects.append({"name": project_name, "keywords": [], "vaults": [vault]})

    save_json(config_path, data)


def add_distraction_keywords(config_path: Path, new_keywords: list[str]) -> None:
    """Add `new_keywords` to the flat distraction keyword list."""

    if not new_keywords:
        return

    data = load_json(config_path)
    existing = {kw.lower() for kw in data.get("keywords", [])}
    keywords = data.setdefault("keywords", [])

    for kw in new_keywords:
        if kw.lower() not in existing:
            keywords.append(kw)
            existing.add(kw.lower())

    save_json(config_path, data)


def add_topic_rule(
    config_path: Path,
    topic_name: str,
    category: str,
    domains: list[str] | None = None,
    keywords: list[str] | None = None,
) -> None:
    """Save an explicit user-confirmed topic rule without changing projects."""
    data = load_json(config_path)
    topics = data.setdefault("topics", [])
    for topic in topics:
        if topic.get("name", "").lower() == topic_name.lower() and topic.get("category") == category:
            for field, values in (("domains", domains or []), ("keywords", keywords or [])):
                existing = {str(value).lower() for value in topic.get(field, [])}
                target = topic.setdefault(field, [])
                for value in values:
                    if value and value.lower() not in existing:
                        target.append(value)
                        existing.add(value.lower())
            break
    else:
        topics.append({"name": topic_name, "category": category, "domains": list(domains or []), "keywords": list(keywords or [])})
    save_json(config_path, data)
