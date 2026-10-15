"""Safe, focused Hyprland window-management tools.

Every command uses a fixed ``hyprctl dispatch`` subcommand and argument list.
No action accepts or invokes arbitrary shell text.
"""

import subprocess
from collections.abc import Callable

from core.permissions import PermissionLevel
from tools.base import Tool, ToolResult


class HyprlandController:
    """Minimal wrapper around Hyprland's local IPC command interface."""

    def __init__(self, runner: Callable[[list[str]], None] | None = None):
        self._runner = runner or self._run_command

    @staticmethod
    def _run_command(command: list[str]) -> None:
        subprocess.run(command, check=True, timeout=3, capture_output=True, text=True)

    def dispatch(self, action: str, *arguments: str) -> None:
        # ``action`` is only supplied by tool implementations below.  Keeping
        # it out of an LLM-facing API prevents command-capability escalation.
        self._runner(["hyprctl", "dispatch", action, *arguments])


class FocusWorkspaceTool(Tool):
    name = "focus_workspace"
    description = "Focus a numbered or named Hyprland workspace."
    permission_level = PermissionLevel.SAFE

    def __init__(self, controller: HyprlandController | None = None):
        self._controller = controller or HyprlandController()

    def run(self, *, workspace: str) -> ToolResult:
        workspace = str(workspace).strip()
        if not workspace or len(workspace) > 64:
            return ToolResult(False, "A valid workspace name is required.")
        self._controller.dispatch("workspace", workspace)
        return ToolResult(True, f"Focused workspace {workspace}.")


class ToggleFullscreenTool(Tool):
    name = "toggle_fullscreen"
    description = "Toggle fullscreen for the currently focused window."
    permission_level = PermissionLevel.SAFE

    def __init__(self, controller: HyprlandController | None = None):
        self._controller = controller or HyprlandController()

    def run(self) -> ToolResult:
        self._controller.dispatch("fullscreen", "0")
        return ToolResult(True, "Toggled fullscreen for the focused window.")


class ToggleFloatingTool(Tool):
    name = "toggle_floating"
    description = "Toggle floating/tiled mode for the currently focused window."
    permission_level = PermissionLevel.SAFE

    def __init__(self, controller: HyprlandController | None = None):
        self._controller = controller or HyprlandController()

    def run(self) -> ToolResult:
        self._controller.dispatch("togglefloating")
        return ToolResult(True, "Toggled floating mode for the focused window.")


class CloseFocusedWindowTool(Tool):
    name = "close_focused_window"
    description = "Close the currently focused window."
    permission_level = PermissionLevel.CONFIRM

    def __init__(self, controller: HyprlandController | None = None):
        self._controller = controller or HyprlandController()

    def run(self) -> ToolResult:
        self._controller.dispatch("closewindow", "active")
        return ToolResult(True, "Closed the focused window.")
