
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
PostgreSQL
"""

import unittest

from app.firebase.client import FirebaseClient
from app.transformer.normalize import normalize_buoy
from app.models.buoy import Buoy
from app.repository.buoy_repository import BuoyRepository
from tests.integration.temporary_database import TemporaryDatabaseTestCase


from tests.integration.gate import integration_test
from tests.integration.firebase_samples import buscar_leitura_real


@integration_test
class TestETLBuoy(TemporaryDatabaseTestCase):

    def test_firebase_to_postgresql(self):

        # =====================================================
        # 1. FIREBASE
        # =====================================================

        client = FirebaseClient()
        buoy_id, firebase_id, firebase_data = buscar_leitura_real(client, "boias")

        print("\n" + "=" * 70)
        print("TESTE DE INTEGRAÇÃO - ETL BOIA")
        print("=" * 70)

        print("\n[1] Firebase")
        print(f"Boia ID: {buoy_id}")
        print(f"Firebase ID: {firebase_id}")

        # =====================================================
        # 2. NORMALIZAÇÃO
        # =====================================================

        buoy = normalize_buoy(
            firebase_id=firebase_id,
            buoy_id=buoy_id,
            data=firebase_data,
        )

        self.assertIsInstance(buoy, Buoy)

        print("\n[2] Normalização")
        print("Objeto Buoy:")
        print(buoy)

        # =====================================================
        # 3. POSTGRESQL
        # =====================================================

        db = self.database
        repository = BuoyRepository(db)

        repository.insert(buoy)

        print("\n[3] PostgreSQL")
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
