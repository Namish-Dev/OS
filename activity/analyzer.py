import sys
from pathlib import Path
from datetime import datetime


# Add project root to Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from database.database import get_connection


def get_recent_activity(limit=50):
    """Get recent activity events from the database."""

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
    SELECT timestamp, process, window_title
    FROM activity_events
    ORDER BY id DESC
    LIMIT ?
""", (limit,))

    rows = cursor.fetchall()

    connection.close()

    # We retrieved newest → oldest.
    # Reverse so analysis runs chronologically.
    rows.reverse()

    return rows


def calculate_sessions(events):
    """Calculate how long each activity remained active."""

    sessions = []

    for i in range(len(events)):

        timestamp, process, window_title = events[i]

        start_time = datetime.fromisoformat(timestamp)

        # If this is not the final event,
        # the next event marks the end of this activity.
        if i < len(events) - 1:

            next_timestamp = events[i + 1][0]

            end_time = datetime.fromisoformat(next_timestamp)

            duration = (end_time - start_time).total_seconds()

        else:

            end_time = None
            duration = None

        sessions.append({
            "start": start_time,
            "end": end_time,
            "duration": duration,
            "process": process,
            "window_title": window_title
        })

    return sessions


def main():

    events = get_recent_activity()

    sessions = calculate_sessions(events)

    print("\nActivity Sessions\n")
    print("-" * 80)

    for session in sessions:

        print(
            f"{session['start'].strftime('%H:%M:%S')} | "
            f"{session['process']:15} | "
            f"{session['duration']} sec | "
            f"{session['window_title']}"
        )


if __name__ == "__main__":
    main()