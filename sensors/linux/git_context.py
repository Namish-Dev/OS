"""Read-only Git context collection for a known local project directory."""

import subprocess
from collections.abc import Callable
from pathlib import Path


class GitContextCollector:
    """Collect minimal repository state without reading source contents.

    A caller must already have a trustworthy project path (for example from a
    future VS Code integration). This collector never searches arbitrary home
    directories, executes shell text, stages files, or changes Git state.
    """

    def __init__(self, runner: Callable[[list[str]], str] | None = None):
        self._runner = runner or self._run

    @staticmethod
    def _run(command: list[str]) -> str:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=3)
        return result.stdout.strip()

    def collect(self, project_path: str | Path) -> dict:
        path = Path(project_path).expanduser()
        if not path.is_dir():
            return {}
        base = ["git", "-C", str(path)]
        try:
            root = self._runner([*base, "rev-parse", "--show-toplevel"])
            branch = self._runner([*base, "branch", "--show-current"])
            status_lines = self._runner([*base, "status", "--porcelain=v1"]).splitlines()
            commits_today = self._runner([*base, "log", "--since=midnight", "--format=%H"]).splitlines()
            last_commit = self._runner([*base, "log", "-1", "--format=%cI"])
        except (OSError, subprocess.SubprocessError):
            return {}

        modified = sum(1 for line in status_lines if line and not line.startswith("??"))
        untracked = sum(1 for line in status_lines if line.startswith("??"))
        return {
            "git": {
                "repository": root or str(path),
                "branch": branch or "detached",
                "modified_files": modified,
                "untracked_files": untracked,
                "commits_today": len(commits_today),
                "last_commit_at": last_commit or None,
            }
        }
