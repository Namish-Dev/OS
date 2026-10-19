"""Read-only report for the disposable integration database."""
import json
import sqlite3
from pathlib import Path

db = Path(__file__).parent / "capture.db"
connection = sqlite3.connect(db)
connection.row_factory = sqlite3.Row

for table, order_by in (
    ("dev_file_changes", "id"),
    ("dev_terminal_events", "id"),
    ("dev_snapshots", "captured_at"),
):
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
    print(table, json.dumps([dict(row) for row in rows], indent=2))

connection.close()
