from dataclasses import asdict

from psycopg2 import Error

from app.database.connection import DatabaseConnection


class BaseRepository:

    table_name = None

    def __init__(self):

        self.db = DatabaseConnection()

        self.connection = self.db.connect()

        self.cursor = self.connection.cursor()

    def insert(self, obj):

        data = asdict(obj)

        columns = list(data.keys())

        values = list(data.values())

        placeholders = ", ".join(["%s"] * len(values))

        sql = f"""
            INSERT INTO {self.table_name}
            ({", ".join(columns)})

            VALUES
            ({placeholders})

            ON CONFLICT(firebase_id, timestamp)

            DO NOTHING;
        """

        try:

            self.cursor.execute(sql, values)

            self.connection.commit()

        except Error:

            self.connection.rollback()

            raise

    def close(self):

        self.cursor.close()

        self.connection.close()