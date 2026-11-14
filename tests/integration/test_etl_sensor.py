"""
Teste de integração do fluxo ETL de sensores.

Fluxo testado:

Firebase
    ↓
FirebaseClient
    ↓
normalize_sensor()
    ↓
Sensor
    ↓
SensorRepository
    ↓
TimescaleDB
"""

import unittest

from app.firebase.client import FirebaseClient
from app.transformer.normalize import normalize_sensor
from app.models.sensor import Sensor
from app.repository.sensor_repository import SensorRepository
from tests.integration.temporary_database import TemporaryDatabaseTestCase


from tests.integration.gate import integration_test
from tests.integration.firebase_samples import buscar_leitura_real


@integration_test
class TestETLSensor(TemporaryDatabaseTestCase):

    def test_firebase_to_timescaledb(self):

        # =====================================================
        # 1. FIREBASE
        # =====================================================

        client = FirebaseClient()
        sensor_id, firebase_id, firebase_data = buscar_leitura_real(client, "sensores")

        print("\n" + "=" * 70)
        print("TESTE DE INTEGRAÇÃO - ETL SENSOR")
        print("=" * 70)

        print("\n[1] Firebase")
        print(f"Sensor ID: {sensor_id}")
        print(f"Firebase ID: {firebase_id}")

        # =====================================================
        # 2. NORMALIZAÇÃO
        # =====================================================

        sensor = normalize_sensor(
            firebase_id=firebase_id,
            sensor_id=sensor_id,
            data=firebase_data,
        )

        self.assertIsInstance(sensor, Sensor)

        print("\n[2] Normalização")
        print("Objeto Sensor:")
        print(sensor)

        # =====================================================
        # 3. TIMESCALEDB
        # =====================================================

        db = self.database
        repository = SensorRepository(db)

        repository.insert(sensor)

        print("\n[3] TimescaleDB")
        print("Sensor enviado para o banco.")

        # =====================================================
        # 4. VERIFICAÇÃO
        # =====================================================

        connection = db.connect()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    firebase_id,
                    sensor_id,
                    timestamp,
                    temperatura,
                    umidade,
                    pressao
                FROM sensor_data
                WHERE firebase_id = %s
                  AND timestamp = %s;
                """,
                (
                    sensor.firebase_id,
                    sensor.timestamp,
                )
            )

            registro = cursor.fetchone()

        db.close()

        self.assertIsNotNone(registro)

        print("\n[4] Verificação no banco")
        print(f"Registro encontrado: {registro}")

        print("\n" + "=" * 70)
        print("ETL SENSOR CONCLUÍDO COM SUCESSO")
        print("=" * 70)
