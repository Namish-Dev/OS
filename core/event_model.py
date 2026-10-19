"""
Personal OS — Standardized Activity Event Model.

This is the single event format consumed by the entire system.
It does NOT depend on any OS-specific API.

Any sensor (Windows, Linux, browser, IDE, filesystem) produces
an ActivityEvent that conforms to this model.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActivityEvent:
    """
    A single observation of what the user is doing or what is changing.

    Standard fields:
        id              Unique event ID (assigned by database or generator).
        timestamp       ISO-format string (seconds precision).
        event_type      Event type ("app_foreground", "window_change", "browser_tab",
                         "file_open", "file_modified", "file_created", "file_deleted", etc.).
        sensor          Source sensor ("windows_foreground", "hyprland", "browser_extension",
                         "cdp", "vscode_extension", "filesystem_watcher").
        application     Human-readable name ("Google Chrome", "Visual Studio Code").
        process         Raw executable name ("chrome.exe", "Code.exe").
        pid             Process ID when available.
        window_title    Raw window title as reported by the OS.
        context         Flexible dictionary with observation-specific metadata:
                            VS Code:  {"file": "main.py", "file_path": "/...", "workspace": "OS", "workspace_path": "/..."}
                            Browser:  {"page_title": "GitHub", "url": "https://github.com/", "domain": "github.com", "browser": "..."}
                            Explorer: {"path": "C:\\Users\\..."}
                            Files:    {"file_name": "...", "file_path": "...", "event_type": "..."}
    """

    timestamp: str
    application: str
    process: str
    window_title: str
    context: dict = field(default_factory=dict)
    event_type: str = "app_foreground"
    sensor: str | None = None
    pid: int | None = None
    id: int | None = None

    # ---- Convenient properties for direct access ---------------------------

    @property
    def url(self) -> str | None:
        return self.context.get("url")

    @property
    def domain(self) -> str | None:
        return self.context.get("domain")

    @property
    def page_title(self) -> str | None:
        return self.context.get("page_title") or self.context.get("title")

    @property
    def file(self) -> str | None:
        return self.context.get("file") or self.context.get("file_name")

    @property
    def file_path(self) -> str | None:
        return self.context.get("file_path") or self.context.get("path")

    @property
    def workspace(self) -> str | None:
        return self.context.get("workspace")

    @property
    def workspace_path(self) -> str | None:
        return self.context.get("workspace_path")

    @property
    def command(self) -> str | None:
        return self.context.get("command")

    @property
    def cwd(self) -> str | None:
        return self.context.get("cwd") or self.context.get("working_directory")

    @property
    def exit_code(self) -> int | None:
        return self.context.get("exit_code")

    @property
    def output(self) -> str | None:
        return self.context.get("output")

    @property
    def status(self) -> str | None:
        return self.context.get("status")

    @property
    def terminal_host(self) -> str | None:
        return self.context.get("terminal_host")

    @property
    def shell(self) -> str | None:
        return self.context.get("shell")

    @property
    def session_id(self) -> str | None:
        return self.context.get("session_id")

    @property
    def git_branch(self) -> str | None:
        return self.context.get("git_branch")

    @property
    def git_status(self) -> str | None:
        return self.context.get("git_status")

    @property
    def diff(self) -> str | None:
        return self.context.get("diff")

    # ---- Factories --------------------------------------------------------

    @classmethod
    def create(
        cls,
        application: str,
        process: str | None,
        window_title: str | None,
        context: dict | None = None,
        event_type: str = "app_foreground",
        sensor: str | None = None,
        pid: int | None = None,
        id: int | None = None,
        timestamp: str | None = None,
    ) -> "ActivityEvent":
        """Create an event stamped with current timestamp or provided timestamp."""

        return cls(
            id=id,
            timestamp=timestamp or datetime.now().isoformat(timespec="seconds"),
            event_type=event_type,
            sensor=sensor,
            application=application or "Unknown",
            process=process or "unknown",
            pid=pid,
            window_title=window_title or "",
            context=dict(context) if context else {},
        )

    @classmethod
    def create_terminal_event(
        cls,
        command: str,
        cwd: str | None = None,
        exit_code: int | None = None,
        output: str | None = None,
        terminal_host: str | None = None,
        shell: str | None = None,
        session_id: str | None = None,
        status: str = "completed",
        sensor: str = "terminal",
        start_time: str | None = None,
        completion_time: str | None = None,
        extra_context: dict | None = None,
        timestamp: str | None = None,
    ) -> "ActivityEvent":
        """Create a sanitized command execution event."""
        from core.privacy import sanitize_terminal_event
        ctx = {
            "command": command,
            "cwd": cwd,
            "exit_code": exit_code,
            "output": output,
            "terminal_host": terminal_host or "Terminal",
            "shell": shell or "unknown",
            "session_id": session_id,
            "status": status,
            "start_time": start_time,
            "completion_time": completion_time,
        }
        if extra_context:
            ctx.update(extra_context)
        sanitized = sanitize_terminal_event(ctx)
        app_name = terminal_host or shell or "Terminal"
        proc = shell.lower() if shell else "terminal"
        event_type = "command_failed" if (exit_code is not None and exit_code != 0) else "command_executed"
        if status == "running":
            event_type = "command_running"
        return cls.create(
            application=app_name,
            process=proc,
            window_title=f"{app_name}: {sanitized.get('command', '')[:80]}",
            context=sanitized,
            event_type=event_type,
            sensor=sensor,
            timestamp=timestamp,
        )

    @classmethod
    def create_file_event(
        cls,
        event_type: str,
        file_path: str,
        workspace: str | None = None,
        workspace_path: str | None = None,
        application: str = "Editor",
        sensor: str = "ide",
        extra_context: dict | None = None,
        timestamp: str | None = None,
    ) -> "ActivityEvent":
        """Create a file activity event (open, modify, save, create, delete)."""
        from pathlib import Path
        file_name = Path(file_path).name if file_path else None
        ctx = {
            "file": file_name,
            "file_path": file_path,
            "workspace": workspace,
            "workspace_path": workspace_path,
        }
        if extra_context:
            ctx.update(extra_context)
        return cls.create(
            application=application,
            process=application.lower(),
            window_title=f"{file_name or 'file'} - {workspace or application}",
            context=ctx,
            event_type=event_type,
            sensor=sensor,
            timestamp=timestamp,
        )

    # ---- Serialisation ----------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain dict suitable for JSON / database storage."""

        data = {
            "id": self.id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "sensor": self.sensor,
            "application": self.application,
            "process": self.process,
            "pid": self.pid,
            "window_title": self.window_title,
            "context": dict(self.context),
        }
        return data

    # ---- Display ----------------------------------------------------------

    def __str__(self) -> str:
        parts = [
            f"[{self.timestamp}]",
            self.application,
        ]
        if self.pid is not None:
            parts.append(f"PID:{self.pid}")
        if self.event_type and self.event_type != "app_foreground":
            parts.append(f"<{self.event_type}>")

        if self.context:
            details = ", ".join(
                f"{k}={v}" for k, v in self.context.items() if v is not None and v != ""
            )
            if details:
                parts.append(f"({details})")

        return " | ".join(parts)
