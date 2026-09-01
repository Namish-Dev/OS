"""
Personal OS — Standardized Activity Event Model.

This is the single event format consumed by the entire system.
It does NOT depend on any OS-specific API.

Any sensor (Windows, Linux/X11, Linux/Wayland) must produce
an ActivityEvent that conforms to this model.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActivityEvent:
    """
    A single observation of what the user is doing.

    Required fields:
        timestamp       ISO-format string (seconds precision).
        application     Human-readable name ("Google Chrome", "Visual Studio Code").
        process         Raw executable name ("chrome.exe", "Code.exe").
        window_title    Raw window title as reported by the OS.

    Optional context:
        context         Flexible dict — contents depend on the application.
                        Examples:
                            VS Code:  {"file": "main.py", "workspace": "OS"}
                            Chrome:   {"page_title": "GitHub", "url": "https://github.com/", "domain": "github.com"}
                            Obsidian: {"note": "Daily Log", "vault": "Personal"}
                            Explorer: {"path": "C:\\Users\\..."}
    """

    timestamp: str
    application: str
    process: str
    window_title: str
    context: dict = field(default_factory=dict)

    # ---- Factories --------------------------------------------------------

    @classmethod
    def create(
        cls,
        application: str,
        process: str,
        window_title: str,
        context: dict | None = None,
    ) -> "ActivityEvent":
        """Create an event stamped with the current time."""

        return cls(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            application=application,
            process=process or "unknown",
            window_title=window_title or "",
            context=context or {},
        )

    # ---- Serialisation ----------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain dict suitable for JSON / database storage."""

        return {
            "timestamp": self.timestamp,
            "application": self.application,
            "process": self.process,
            "window_title": self.window_title,
            "context": dict(self.context),      # shallow copy
        }

    # ---- Display ----------------------------------------------------------

    def __str__(self) -> str:

        parts = [
            f"[{self.timestamp}]",
            self.application,
        ]

        if self.context:
            details = ", ".join(
                f"{k}={v}" for k, v in self.context.items() if v
            )
            if details:
                parts.append(f"({details})")

        return " | ".join(parts)
