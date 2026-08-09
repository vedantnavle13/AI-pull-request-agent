from app.database.postgres import get_connection


def test_connection():

    with get_connection() as conn:

        with conn.cursor() as cursor:

            cursor.execute("SELECT 1")

            result = cursor.fetchone()

            print("Database result:", result)


if __name__ == "__main__":
    test_connection()