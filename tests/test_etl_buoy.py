
"""
Teste de integração do fluxo ETL de boias.

Fluxo testado:

Firebase
    ↓
FirebaseClient
    ↓
normalize_buoy()
    ↓
Buoy
    ↓
BuoyRepository
    ↓
TimescaleDB
"""

import unittest

from app.firebase.client import FirebaseClient
from app.transformer.normalize import normalize_buoy
from app.models.buoy import Buoy
from app.repository.buoy_repository import BuoyRepository
from app.database.connection import DatabaseConnection


class TestETLBuoy(unittest.TestCase):

    def test_firebase_to_timescaledb(self):

        # =====================================================
        # 1. FIREBASE
        # =====================================================

        client = FirebaseClient()
        client.connect()

        ref = client.buoy_data("BOIA001")
        data = ref.get()

        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)

        # Pega o último registro disponível
        firebase_id, firebase_data = list(data.items())[-1]

        print("\n" + "=" * 70)
        print("TESTE DE INTEGRAÇÃO - ETL BOIA")
        print("=" * 70)

        print("\n[1] Firebase")
        print("Boia ID: BOIA001")
        print(f"Firebase ID: {firebase_id}")

        # =====================================================
        # 2. NORMALIZAÇÃO
        # =====================================================

        buoy = normalize_buoy(
            firebase_id=firebase_id,
            buoy_id="BOIA001",
            data=firebase_data,
        )

        self.assertIsInstance(buoy, Buoy)

        print("\n[2] Normalização")
        print("Objeto Buoy:")
        print(buoy)

        # =====================================================
        # 3. TIMESCALEDB
        # =====================================================

        db = DatabaseConnection()
        repository = BuoyRepository(db)

        repository.insert(buoy)

        print("\n[3] TimescaleDB")
        print("Boia enviada para o banco.")

        # =====================================================
        # 4. VERIFICAÇÃO
        # =====================================================

        connection = db.connect()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    firebase_id,
                    buoy_id,
                    timestamp,
                    adc,
                    ph,
                    sensor_uv_v,
                    tensao_v,
                    turbidez_v
                FROM buoy_data
                WHERE firebase_id = %s
                  AND timestamp = %s;
                """,
                (
                    buoy.firebase_id,
                    buoy.timestamp,
                )
            )

            registro = cursor.fetchone()

        db.close()

        self.assertIsNotNone(registro)

        print("\n[4] Verificação no banco")
        print(f"Registro encontrado: {registro}")

        print("\n" + "=" * 70)
        print("ETL BOIA CONCLUÍDO COM SUCESSO")
        print("=" * 70)

