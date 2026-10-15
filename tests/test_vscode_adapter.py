"""Tests for the minimal local VS Code extension bridge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sensors.vscode import extension_server
from sensors.vscode.extension_adapter import VSCodeExtensionAdapter


def test_adapter_normalizes_extension_context_to_safe_event_fields():
    extension_server._state.clear()
    extension_server.update_latest_context({
        "workspace_path": "/home/user/Projects/personal-agent",
        "workspace": "personal-agent",
        "file_path": "/home/user/Projects/personal-agent/core/context.py",
        "language": "python",
        "document_text": "must be ignored",
    })

    context = VSCodeExtensionAdapter().get_context()

    assert context == {
        "workspace": "personal-agent",
        "workspace_path": "/home/user/Projects/personal-agent",
        "file": "context.py",
        "language": "python",
    }
