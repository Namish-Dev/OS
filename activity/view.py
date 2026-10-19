"""
Personal OS — View Raw Activity Events.

Command-line tool to inspect raw activity events stored in SQLite.

Usage:
    python activity/view.py                  # Show 20 most recent events
    python activity/view.py --limit 50       # Show 50 most recent events
    python activity/view.py --from 2026-10-19T10:00:00 --to 2026-10-19T14:00:00
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import get_recent_events, get_events_by_timerange


def format_event(event: dict) -> str:
    timestamp = event.get("timestamp", "")
    app = event.get("application") or event.get("process") or "Unknown"
    process = event.get("process") or ""
    pid = f"PID:{event.get('pid')}" if event.get("pid") is not None else ""
    title = event.get("window_title") or ""
    ctx = event.get("context") or {}

    details = []
    if ctx.get("url"):
        details.append(f"url={ctx['url']}")
    elif ctx.get("domain"):
        details.append(f"domain={ctx['domain']}")

    if ctx.get("file"):
        details.append(f"file={ctx['file']}")
    if ctx.get("workspace"):
        details.append(f"workspace={ctx['workspace']}")
    if ctx.get("path"):
        details.append(f"path={ctx['path']}")

    detail_str = f" ({', '.join(details)})" if details else ""
    pid_str = f" {pid}" if pid else ""
    return f"[{timestamp}] {app} [{process}]{pid_str} | \"{title}\"{detail_str}"


def main():
    parser = argparse.ArgumentParser(description="View raw activity events from Personal OS database.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of recent events to display.")
    parser.add_argument("--from", dest="from_time", help="Start timestamp in ISO format.")
    parser.add_argument("--to", dest="to_time", help="End timestamp in ISO format.")
    args = parser.parse_args()

    if args.from_time and args.to_time:
        events = get_events_by_timerange(args.from_time, args.to_time)
        print(f"\nActivity Events from {args.from_time} to {args.to_time} ({len(events)} events):")
    else:
        events = get_recent_events(limit=args.limit)
        print(f"\nMost Recent Activity Events ({len(events)} events):")

    print("-" * 80)
    for event in events:
        print(format_event(event))
    print()


if __name__ == "__main__":
    main()