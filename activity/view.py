import sys
from pathlib import Path


# Add the project root to Python's path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from database.database import get_connection


connection = get_connection()

cursor = connection.cursor()

cursor.execute("""
    SELECT id, timestamp, process, window_title
    FROM activity_events
    ORDER BY id DESC
    LIMIT 20
""")

rows = cursor.fetchall()

for row in rows:
    print(row)

connection.close()