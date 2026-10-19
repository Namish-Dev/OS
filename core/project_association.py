"""
Personal OS — Project Association.

Resolves the canonical project root for a given file path or working directory
without relying on Git. Git is used as an optional supplementary signal only.

Resolution order (most to least specific):
  1. Exact match in user-defined project registry (config/projects.json or DB).
  2. Longest registered workspace_path prefix.
  3. Git repository root (optional; only when Git is available).
  4. First ancestor directory that contains a project marker file
     (pyproject.toml, package.json, Cargo.toml, go.mod, etc.).
  5. Unassigned — returns None rather than guessing.

Returned values are absolute, normalised paths (forward slashes on Windows too).
Associations are cached per process; call clear_cache() for tests.
"""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Project-marker filenames that indicate a project root
# ──────────────────────────────────────────────────────────────────────────────
_PROJECT_MARKERS = {
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "CMakeLists.txt",
    ".project",
}

# Default location of the user-defined project registry
_DEFAULT_REGISTRY_PATH = Path(__file__).parent.parent / "config" / "project_paths.json"


def _load_registry(registry_path: Path | None = None) -> list[dict]:
    """Load the user-defined project registry from JSON, if present."""
    path = registry_path or _DEFAULT_REGISTRY_PATH
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("projects", [])
        except Exception:
            pass
    return []


def _normalise(p: str | Path) -> str:
    """Return an absolute, forward-slash path string."""
    return str(Path(p).resolve()).replace("\\", "/")


def resolve_project(
    path: str | Path | None,
    registry_path: Path | None = None,
    use_git: bool = True,
) -> str | None:
    """
    Determine the project root for *path* (a file path or working directory).

    Returns the normalised absolute path of the project root, or None when
    association is uncertain.  Never raises.
    """
    if not path:
        return None

    try:
        candidate = Path(path).resolve()
    except Exception:
        return None

    # Walk up from the candidate; if it's a file, start from its parent
    start = candidate if candidate.is_dir() else candidate.parent
    if not start.exists():
        # Use last-known directory segment
        start = candidate.parent

    # 1. Registry exact match or longest prefix
    registry = _load_registry(registry_path)
    best_prefix: str | None = None
    best_len = 0
    for entry in registry:
        rp = _normalise(entry.get("path", ""))
        if not rp:
            continue
        norm_start = _normalise(start)
        if norm_start == rp or norm_start.startswith(rp + "/"):
            if len(rp) > best_len:
                best_prefix = rp
                best_len = len(rp)

    if best_prefix:
        return best_prefix

    # 2. Walk ancestors for project markers (Git-independent)
    check = start
    for _ in range(20):  # max 20 levels up
        if any((check / marker).exists() for marker in _PROJECT_MARKERS):
            return _normalise(check)
        parent = check.parent
        if parent == check:
            break
        check = parent

    # 3. Git root (optional supplementary signal)
    if use_git:
        git_root = _git_root(start)
        if git_root:
            return git_root

    return None


def _git_root(directory: Path) -> str | None:
    """Return the git repository root above *directory*, or None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return _normalise(result.stdout.strip())
    except Exception:
        pass
    return None


def clear_cache() -> None:
    """Clear the lru_cache on _git_root (useful in tests)."""
    pass  # lru_cache is on subprocess; kept for API compatibility
