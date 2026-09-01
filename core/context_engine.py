import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from database.database import get_connection
from core.context import build_context


def get_recent_events(limit=20):

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

    rows.reverse()

    return rows


def main():

    events = get_recent_events(20)

    print("\nREAL ACTIVITY CONTEXT")
    print("=" * 80)

    for timestamp, process, window_title in events:

        context = build_context(
            process,
            window_title
        )

        print()
        print(timestamp)

        for key, value in context.items():

            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()