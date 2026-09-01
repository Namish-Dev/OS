import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).parent / "personal_os.db"

connection = sqlite3.connect(DATABASE_PATH)
cursor = connection.cursor()

cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name
""")

tables = cursor.fetchall()

print("Tables in Personal OS database:")
print()

for table in tables:
    print("-", table[0])

connection.close()