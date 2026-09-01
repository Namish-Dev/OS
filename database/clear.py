from database import get_connection


def clear_database():
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("DELETE FROM activity_context")
        cursor.execute("DELETE FROM activity_events")

        # Reset AUTOINCREMENT counters
        cursor.execute(
            "DELETE FROM sqlite_sequence WHERE name = 'activity_context'"
        )
        cursor.execute(
            "DELETE FROM sqlite_sequence WHERE name = 'activity_events'"
        )

        connection.commit()
        print("Database cleared successfully. Tables were preserved.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    clear_database()