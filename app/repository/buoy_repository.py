"""
Repository responsável pela persistência de boias
no PostgreSQL / TimescaleDB.
"""

from app.models.buoy import Buoy
from app.database.connection import DatabaseConnection


class BuoyRepository:

    def __init__(self, database: DatabaseConnection):
        self.database = database

    def insert(self, buoy: Buoy) -> None:
        """
        Insere uma boia no banco de dados.

        Caso o registro já exista, nenhuma duplicação é realizada.
        """

        query = """
            INSERT INTO buoy_data (
                firebase_id,
                buoy_id,
                timestamp,
                adc,
                ph,
                sensor_uv_v,
                tensao_v,
                turbidez_v
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (firebase_id, timestamp)
            DO NOTHING
            RETURNING firebase_id;
        """

        values = (
            buoy.firebase_id,
            buoy.buoy_id,
            buoy.timestamp,
            buoy.adc,
            buoy.ph,
            buoy.sensor_uv_v,
            buoy.tensao_v,
            buoy.turbidez_v,
        )

        connection = self.database.connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(query, values)

                result = cursor.fetchone()

            self.database.commit()

            return result is not None

        except Exception:
            self.database.rollback()
            raise
