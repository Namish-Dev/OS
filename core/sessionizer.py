"""
Personal OS — Sessionizer.

Turns a flat stream of raw activity_events rows into meaningful
sessions:

    "Namish opened analyzer.py, then Chrome, then Obsidian"
        → "Namish spent 52 minutes on the Personal OS project:
           31 min coding, 14 min research, 7 min reading notes."

A session is a contiguous block of time spent on the same project,
without a gap longer than SESSION_GAP_MINUTES between events.
Category time (coding/research/notes/...) is tracked *within* each
session, since a single project session naturally mixes activities.

This module only reads from the database — it never writes to it,
and never touches how events are recorded (Phase 1 is untouched).

Platform-independent.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.activity_classifier import classify_event
from core.project_matcher import ProjectMatcher, UNASSIGNED
from database.database import get_connection

# Fallback used only when the `application` column is missing/NULL
# (e.g. legacy rows recorded before this column was populated).
# Infers the application from the window title suffix, the same way
# strip_browser_suffix() and similar parsers already do elsewhere.
_TITLE_SUFFIX_APP_MAP = [
    (" - Visual Studio Code", "Visual Studio Code"),
    (" - Google Chrome", "Google Chrome"),
    (" - Brave", "Brave"),
    (" - File Explorer", "File Explorer"),
    (" - Obsidian", "Obsidian"),
    (" - Antigravity IDE", "Antigravity"),
    (" - Antigravity", "Antigravity"),
]


def _resolve_application(application: str | None, window_title: str | None) -> str | None:
    """Return `application` if present, otherwise infer it from the
    window title suffix. Returns None if neither is available/matches."""

    if application:
        return application

    title = window_title or ""

    for suffix, app_name in _TITLE_SUFFIX_APP_MAP:
        if title.endswith(suffix):
            return app_name

    return application

# A gap longer than this between two events on the same project
# ends the current session and starts a new one — the user was
# very likely away from the computer, not just reading/thinking.
# Kept >= MAX_EVENT_MINUTES so a single longer read (e.g. an 8-10
# minute documentation page) doesn't itself fragment the session.
SESSION_GAP_MINUTES = 15

# The last event in a session (or the very last event overall) has
# no "next event" to measure its duration against. We also cap any
# single event's contribution at this many minutes, so a window left
# open and forgotten doesn't inflate the session duration.
MAX_EVENT_MINUTES = 10


@dataclass
class Session:
    """A contiguous block of activity attributed to one project."""

    project: str
    start: datetime
    end: datetime
    category_minutes: dict = field(default_factory=dict)
    resources: set = field(default_factory=set)   # (kind, name) tuples
    files: set = field(default_factory=set)
    last_context_label: str | None = None          # "where they left off"

    @property
    def duration_minutes(self) -> float:
        return round(sum(self.category_minutes.values()), 1)

    def summary(self) -> str:

        cat_parts = ", ".join(
            f"{round(mins)} min {cat.lower()}"
            for cat, mins in sorted(
                self.category_minutes.items(), key=lambda kv: -kv[1]
            )
            if mins > 0
        )

        lines = [
            f"Project: {self.project}",
            f"Worked for ~{round(self.duration_minutes)} minutes"
            + (f" ({cat_parts})" if cat_parts else ""),
        ]

        if self.resources:
            resource_names = sorted({name for _, name in self.resources})
            lines.append(f"Resources: {', '.join(resource_names)}")

        if self.files:
            lines.append(f"Files: {', '.join(sorted(self.files))}")

        lines.append(f"Activity: {' + '.join(self._active_categories())}")

        if self.last_context_label:
            lines.append(
                f"Left off at: {self.last_context_label}"
            )

        return "\n".join(lines)

    def _active_categories(self) -> list[str]:
        return [
            cat.lower()
            for cat, mins in sorted(
                self.category_minutes.items(), key=lambda kv: -kv[1]
            )
            if mins > 0
        ]


def _fetch_events(limit: int | None = None, since: str | None = None, until: str | None = None) -> list[dict]:
    """
    Fetch events joined with their context, oldest first.

    Args:
        limit: Only consider the most recent N events.
        since: ISO timestamp lower bound (inclusive), e.g. a day's start.
        until: ISO timestamp upper bound (exclusive), e.g. next day's start.

    Returns a flat list of dicts merging activity_events and
    activity_context columns.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # Older databases and lightweight test fixtures predate metadata_json.
    # Read them faithfully with an empty metadata slot rather than failing.
    cursor.execute("PRAGMA table_info(activity_context)")
    context_columns = {row[1] for row in cursor.fetchall()}
    metadata_column = "c.metadata_json" if "metadata_json" in context_columns else "NULL"

    query = f"""
        SELECT
            e.id, e.timestamp, e.application, e.process, e.window_title,
            c.workspace, c.file, c.note, c.vault, c.domain, c.url,
            c.page_title, c.path, {metadata_column}
        FROM activity_events e
        LEFT JOIN activity_context c ON c.activity_event_id = e.id
        WHERE 1=1
    """

    params: list[str] = []

    if since:
        query += " AND e.timestamp >= ?"
        params.append(since)

    if until:
        query += " AND e.timestamp < ?"
        params.append(until)

    query += " ORDER BY e.id ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    connection.close()

    columns = [
        "id", "timestamp", "application", "process", "window_title",
        "workspace", "file", "note", "vault", "domain", "url",
        "page_title", "path", "metadata_json",
    ]

    events = [dict(zip(columns, row)) for row in rows]

    if limit:
        events = events[-limit:]

    return events


def _event_context(event: dict) -> dict:
    """Extract the context-shaped sub-dict from a flat event row."""

    context = {
        "workspace": event.get("workspace"),
        "file": event.get("file"),
        "note": event.get("note"),
        "vault": event.get("vault"),
        "domain": event.get("domain"),
        "url": event.get("url"),
        "page_title": event.get("page_title"),
        "path": event.get("path"),
    }
    try:
        metadata = json.loads(event.get("metadata_json") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    if isinstance(metadata, dict):
        context.update(metadata)
    return context


def _resource_for_event(category: str, context: dict) -> tuple[str, str] | None:
    """
    Return a (kind, display_name) resource tuple for a given event,
    or None if this event doesn't represent a distinct "resource".
    """

    domain = context.get("domain")
    if domain:
        return ("domain", domain)

    note = context.get("note")
    if note:
        return ("note", "Obsidian")

    return None


def _left_off_label(event: dict, context: dict) -> str | None:
    """Best available description of what the user was doing at the
    end of a session — used for continuity ("left off at ...")."""

    return (
        context.get("file")
        or context.get("note")
        or context.get("page_title")
        or event.get("window_title")
    )


def build_sessions(limit: int | None = None, matcher: ProjectMatcher | None = None) -> list[Session]:
    """
    Fetch events from the database and group them into Sessions.

    Args:
        limit:   Only consider the most recent N events, if given.
        matcher: Optional ProjectMatcher instance (mainly for tests).
    """

    matcher = matcher or ProjectMatcher()

    events = _fetch_events(limit=limit)

    sessions: list[Session] = []
    current: Session | None = None
    previous_timestamp: datetime | None = None

    for i, event in enumerate(events):

        timestamp = datetime.fromisoformat(event["timestamp"])
        context = _event_context(event)
        application = _resolve_application(event.get("application"), event.get("window_title"))
        category = classify_event(application, context)
        project = matcher.match(event.get("window_title"), context)

        # Gap since the PREVIOUS event — this is what determines
        # whether the user was away from the computer long enough
        # to warrant starting a new session.
        if previous_timestamp is not None:
            gap_since_previous = (timestamp - previous_timestamp).total_seconds() / 60.0
        else:
            gap_since_previous = 0.0

        starts_new_session = (
            current is None
            or current.project != project
            or gap_since_previous > SESSION_GAP_MINUTES
        )

        if starts_new_session:

            if current is not None:
                sessions.append(current)

            current = Session(
                project=project,
                start=timestamp,
                end=timestamp,
            )

        # Duration THIS event contributes: time until the next event,
        # capped so idle/forgotten windows don't inflate totals. The
        # very last event overall has no "next", so it contributes 0
        # (we don't know how long it lasted — it may still be ongoing).
        if i + 1 < len(events):
            next_timestamp = datetime.fromisoformat(events[i + 1]["timestamp"])
            gap_to_next = (next_timestamp - timestamp).total_seconds() / 60.0
        else:
            gap_to_next = 0.0

        contributed_minutes = min(gap_to_next, MAX_EVENT_MINUTES)

        current.category_minutes[category] = (
            current.category_minutes.get(category, 0.0) + contributed_minutes
        )
        current.end = timestamp

        resource = _resource_for_event(category, context)
        if resource:
            current.resources.add(resource)

        file_name = context.get("file")
        if file_name:
            current.files.add(file_name)

        label = _left_off_label(event, context)
        if label:
            current.last_context_label = label

        previous_timestamp = timestamp

    if current is not None:
        sessions.append(current)

    return sessions


def project_summary(project_name: str, limit: int | None = None) -> str | None:
    """
    Return a human-readable summary of the most recent session for
    the given project, or None if no session exists for it.

    Matches the target format:
        Project: FastAPI Authentication
        Worked for ~10 minutes (7 min coding, 3 min research)
        Resources: github.com
        Files: auth.py
        Activity: coding + research
        Left off at: auth.py
    """

    sessions = [
        s for s in build_sessions(limit=limit)
        if s.project == project_name
    ]

    if not sessions:
        return None

    return sessions[-1].summary()
