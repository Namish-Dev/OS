"""Tests for the JSON-only portion of the Hyprland activity sensor."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sensors.linux.hyprland_sensor import HyprlandForegroundSensor


def test_parses_active_hyprland_window():
    payload = {
        "address": "0x55c34b",
        "class": "Code",
        "initialClass": "code",
        "title": "context.py - personal-agent - Visual Studio Code",
        "pid": 1234,
        "workspace": {"id": 2, "name": "work"},
        "floating": False,
        "fullscreen": 0,
    }
    sensor = HyprlandForegroundSensor(runner=lambda: json.dumps(payload))

    observation = sensor.get_foreground()

    assert observation["process"] == "code"
    assert observation["window_title"] == payload["title"]
    assert observation["window_id"] == "0x55c34b"
    assert observation["context"]["workspace"] == "work"
    assert observation["context"]["window_pid"] == 1234


def test_returns_none_for_no_active_window():
    sensor = HyprlandForegroundSensor(runner=lambda: "{}")
    assert sensor.get_foreground() is None


def test_returns_none_for_invalid_ipc_json():
    sensor = HyprlandForegroundSensor(runner=lambda: "not json")
    assert sensor.get_foreground() is None
