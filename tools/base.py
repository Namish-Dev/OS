"""Shared types for assistant actions.

Tools receive typed parameters from an eventual agent layer.  They do not
accept a free-form shell command: a tool's implementation owns the command it
is permitted to invoke.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.permissions import PermissionLevel, PermissionPolicy


@dataclass(frozen=True)
class ToolResult:
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """A narrowly-scoped action with a declared permission requirement."""

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.SAFE

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool after permission has been checked."""


class ToolExecutor:
    """Central gate that applies policy before any tool implementation runs."""

    def __init__(self, policy: PermissionPolicy | None = None):
        self._policy = policy or PermissionPolicy()

    def execute(self, tool: Tool, *, confirmed: bool = False, **kwargs: Any) -> ToolResult:
        self._policy.require(tool.permission_level, confirmed=confirmed)
        return tool.run(**kwargs)
