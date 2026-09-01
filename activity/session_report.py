"""
Personal OS — Session Report.

Reads recorded activity and prints project sessions in human-readable
form, e.g.:

    Project: Personal OS
    Worked for ~52 minutes (31 min coding, 14 min research, 7 min notes)
    Resources: github.com
    Files: activity_engine.py, sessionizer.py
    Activity: coding + research + notes
    Left off at: sessionizer.py

Usage:
    python activity/session_report.py               # all sessions
    python activity/session_report.py --project "Personal OS"
    python activity/session_report.py --limit 200    # only last 200 events
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.sessionizer import build_sessions


def main():

    parser = argparse.ArgumentParser(description="Personal OS session report")
    parser.add_argument(
        "--project", default=None,
        help="Only show sessions for this project name",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only consider the most recent N events",
    )
    args = parser.parse_args()

    sessions = build_sessions(limit=args.limit)

    if args.project:
        sessions = [s for s in sessions if s.project == args.project]

    if not sessions:
        print("No sessions found.")
        return

    for session in sessions:
        print(session.summary())
        print("-" * 60)


if __name__ == "__main__":
    main()