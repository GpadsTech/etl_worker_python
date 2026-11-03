"""
Repository responsável pela persistência de sensores
no PostgreSQL / TimescaleDB.
"""

from app.models.sensor import Sensor
from app.database.connection import DatabaseConnection


class SensorRepository:

    def __init__(self, database: DatabaseConnection):
        self.database = database

    def insert(self, sensor: Sensor) -> bool:
        """
        Insere um sensor no banco de dados.

        Caso o registro já exista, nenhuma duplicação é realizada.
        """

        query = """
            INSERT INTO sensor_data (
                firebase_id,
                sensor_id,
                timestamp,
                ar,
                chuva,
                gas,
                luz,
                pressao,
                rpm,
                temperatura,
                umidade,
                vento,
                volt
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
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
            sensor.firebase_id,
            sensor.sensor_id,
            sensor.timestamp,
            sensor.ar,
            sensor.chuva,
            sensor.gas,
            sensor.luz,
            sensor.pressao,
            sensor.rpm,
            sensor.temperatura,
            sensor.umidade,
            sensor.vento,
            sensor.volt,
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
