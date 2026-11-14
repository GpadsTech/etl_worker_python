
"""
Testes do BuoyRepository
"""

import unittest
from datetime import datetime, timezone

from app.models.buoy import Buoy
from app.repository.buoy_repository import BuoyRepository
from tests.integration.temporary_database import TemporaryDatabaseTestCase


from tests.integration.gate import integration_test


@integration_test
class TestBuoyRepository(TemporaryDatabaseTestCase):

    def test_insert_buoy_without_duplication(self):

        buoy = Buoy(
            firebase_id="test-buoy-duplicate-001",
            buoy_id="BOIA001",
            timestamp=datetime(
                2026, 8, 10, 20, 0, 0,
                tzinfo=timezone.utc
            ),
            adc=24.0,
            ph=7.20,
            sensor_uv_v=2.54,
            tensao_v=0.81,
            turbidez_v=3.08,
        )

        db = self.database
        repository = BuoyRepository(db)

        # Primeira inserção
        repository.insert(buoy)

        # Segunda inserção do mesmo registro
        repository.insert(buoy)

        connection = db.connect()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM buoy_data
                WHERE firebase_id = %s
                  AND timestamp = %s;
                """,
                (
                    buoy.firebase_id,
                    buoy.timestamp,
                )
            )

            quantidade = cursor.fetchone()[0]

        db.close()

        print(
            f"\nQuantidade de registros encontrados: {quantidade}"
        )

        self.assertEqual(quantidade, 1)
