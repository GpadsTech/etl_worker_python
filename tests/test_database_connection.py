from app.database.connection import DatabaseConnection


def test_database_connection():
    db = DatabaseConnection()

    conn = db.connect()

    cursor = conn.cursor()
    cursor.execute("SELECT current_database(), version();")

    result = cursor.fetchone()

    print("\nBanco:", result[0])
    print("Versão:", result[1])

    cursor.close()
    db.close()