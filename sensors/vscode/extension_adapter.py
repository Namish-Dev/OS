"""Adapt the local VS Code extension report to activity-event context."""

from pathlib import Path

from sensors.vscode import extension_server


class VSCodeExtensionAdapter:
    def __init__(self, max_age: float = extension_server.FRESHNESS_SECONDS):
        self._max_age = max_age

    def get_context(self) -> dict:
        report = extension_server.get_latest_context(self._max_age)
        if not report:
            return {}
        file_path = report.get("file_path")
        return {
            "workspace": report.get("workspace"),
            "workspace_path": report.get("workspace_path"),
            "file": Path(file_path).name if file_path else None,
            "language": report.get("language"),
        }
