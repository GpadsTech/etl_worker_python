"""
Testes de idempotência dos repositories.

Garante que o mesmo registro não seja
inserido mais de uma vez no banco.
"""

import unittest

from app.firebase.client import FirebaseClient
from app.transformer.normalize import (
    normalize_sensor,
    normalize_buoy,
)
from app.repository.sensor_repository import SensorRepository
from app.repository.buoy_repository import BuoyRepository
from tests.integration.temporary_database import TemporaryDatabaseTestCase


from tests.integration.gate import integration_test
from tests.integration.firebase_samples import buscar_leitura_real


@integration_test
class TestIdempotency(TemporaryDatabaseTestCase):

    def test_sensor_idempotency(self):

        # =====================================================
        # 1. BUSCAR REGISTRO REAL DO FIREBASE
        # =====================================================

        client = FirebaseClient()
        sensor_id, firebase_id, firebase_data = buscar_leitura_real(client, "sensores")

        # =====================================================
        # 2. NORMALIZAR
        # =====================================================

        sensor = normalize_sensor(
            firebase_id=firebase_id,
            sensor_id=sensor_id,
            data=firebase_data,
        )

        # =====================================================
        # 3. INSERIR DUAS VEZES
        # =====================================================

        db = self.database
        repository = SensorRepository(db)

        repository.insert(sensor)
        repository.insert(sensor)

        # =====================================================
        # 4. VERIFICAR QUANTIDADE
        # =====================================================

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

        print("\n" + "=" * 70)
        print("IDEMPOTÊNCIA - SENSOR")
        print("=" * 70)

        print(f"Sensor ID: {sensor_id}")
        print(f"Firebase ID: {sensor.firebase_id}")
        print(f"Timestamp: {sensor.timestamp}")
        print(f"Quantidade encontrada: {quantidade}")

        self.assertEqual(quantidade, 1)

        print("Sensor não foi duplicado.")


    def test_buoy_idempotency(self):

        # =====================================================
        # 1. BUSCAR REGISTRO REAL DO FIREBASE
        # =====================================================

        client = FirebaseClient()
        buoy_id, firebase_id, firebase_data = buscar_leitura_real(client, "boias")

        # =====================================================
        # 2. NORMALIZAR
        # =====================================================

        buoy = normalize_buoy(
            firebase_id=firebase_id,
            buoy_id=buoy_id,
            data=firebase_data,
        )

        # =====================================================
        # 3. INSERIR DUAS VEZES
        # =====================================================

        db = self.database
        repository = BuoyRepository(db)

        repository.insert(buoy)
        repository.insert(buoy)

        # =====================================================
        # 4. VERIFICAR QUANTIDADE
        # =====================================================

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

        print("\n" + "=" * 70)
        print("IDEMPOTÊNCIA - BOIA")
        print("=" * 70)

        print(f"Boia ID: {buoy_id}")
        print(f"Firebase ID: {buoy.firebase_id}")
        print(f"Timestamp: {buoy.timestamp}")
        print(f"Quantidade encontrada: {quantidade}")

        self.assertEqual(quantidade, 1)

        print("Boia não foi duplicada.")
