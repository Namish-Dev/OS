"""Unit tests for permission-controlled Hyprland tools."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.permissions import ConfirmationRequiredError
from tools.base import ToolExecutor
from tools.linux.hyprland import (
    CloseFocusedWindowTool,
    FocusWorkspaceTool,
    HyprlandController,
    ToggleFloatingTool,
    ToggleFullscreenTool,
)


def _controller(commands: list[list[str]]) -> HyprlandController:
    return HyprlandController(runner=commands.append)


def test_window_layout_tools_use_fixed_hyprctl_commands():
    commands: list[list[str]] = []
    controller = _controller(commands)
    executor = ToolExecutor()

    assert executor.execute(ToggleFullscreenTool(controller)).success
    assert executor.execute(ToggleFloatingTool(controller)).success
    assert executor.execute(FocusWorkspaceTool(controller), workspace="2").success

    assert commands == [
        ["hyprctl", "dispatch", "fullscreen", "0"],
        ["hyprctl", "dispatch", "togglefloating"],
        ["hyprctl", "dispatch", "workspace", "2"],
    ]


def test_close_window_requires_confirmation():
    commands: list[list[str]] = []
    tool = CloseFocusedWindowTool(_controller(commands))
    executor = ToolExecutor()

    try:
        executor.execute(tool)
        assert False, "Expected confirmation to be required"
    except ConfirmationRequiredError:
        pass

    result = executor.execute(tool, confirmed=True)
    assert result.success
    assert commands == [["hyprctl", "dispatch", "closewindow", "active"]]
