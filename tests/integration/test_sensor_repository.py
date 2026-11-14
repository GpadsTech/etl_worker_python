"""
Testes do SensorRepository
"""

import unittest
from datetime import datetime, timezone

from app.models.sensor import Sensor
from app.repository.sensor_repository import SensorRepository
from app.database.connection import DatabaseConnection


from tests.integration.gate import integration_test


@integration_test
class TestSensorRepository(unittest.TestCase):

    def test_insert_sensor_without_duplication(self):

        sensor = Sensor(
            firebase_id="test-sensor-duplicate-001",
            sensor_id="EST001",
            timestamp=datetime(
                2026, 8, 10, 20, 0, 0,
                tzinfo=timezone.utc
            ),
            ar=7.35,
            chuva=0.0,
            gas=3.87,
            luz=701.67,
            pressao=1011.75,
            rpm=0.0,
            temperatura=27.69,
            umidade=52.15,
            vento=0.0,
            volt=0.87,
        )

        db = DatabaseConnection()
        repository = SensorRepository(db)

        # Primeira inserção
        repository.insert(sensor)

        # Segunda inserção do mesmo registro
        repository.insert(sensor)

        connection = db.connect()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM sensor_data
                WHERE firebase_id = %s
                  AND timestamp = %s;
                """,
                (
                    sensor.firebase_id,
                    sensor.timestamp,
                )
            )

            quantidade = cursor.fetchone()[0]

        db.close()

        print(
            f"\nQuantidade de registros encontrados: {quantidade}"
        )

        self.assertEqual(quantidade, 1)
