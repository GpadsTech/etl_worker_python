"""Verifica idempotência e rollback SQL em tabela TEMP, nunca em dados reais."""

from datetime import datetime
import unittest

from app.database.connection import DatabaseConnection
from app.models.sensor import Sensor
from app.repository.base import BATCH_SIZE
from app.repository.sensor_repository import SensorRepository
from tests.integration.gate import integration_test


@integration_test
class TestBatchTransaction(unittest.TestCase):
    def setUp(self):
        self.database = DatabaseConnection()
        self.addCleanup(self.database.close)
        connection = self.database.connect()
        # A tabela temporária oculta public.sensor_data só nesta conexão.
        # Commit inicial garante que o rollback do teste não apague a tabela.
        with connection.cursor() as cursor:
            columns = ", ".join(
                f"{name} DOUBLE PRECISION"
                for name in SensorRepository.columns[3:]
            )
            cursor.execute(f"""
                CREATE TEMP TABLE sensor_data (
                    firebase_id TEXT NOT NULL,
                    sensor_id TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    {columns},
                    PRIMARY KEY (firebase_id, timestamp)
                );
            """)
        self.database.commit()
        self.repository = SensorRepository(self.database)

    def count(self):
        with self.database.connect().cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pg_temp.sensor_data")
            return cursor.fetchone()[0]

    def test_replay_is_idempotent_and_keeps_same_timestamp_ids(self):
        objects = [
            Sensor("-001", "EST_TEST", datetime(2026, 8, 20)),
            Sensor("-002", "EST_TEST", datetime(2026, 8, 20)),
        ]
        self.assertEqual(self.repository.insert_many(objects), 2)
        self.assertEqual(self.repository.insert_many(objects), 0)
        self.assertEqual(self.count(), 2)

    def test_failed_second_page_leaves_no_first_page_rows(self):
        objects = [
            Sensor(str(i), "EST_TEST", datetime(2026, 8, 20))
            for i in range(BATCH_SIZE)
        ]
        # NULL na PK força erro na segunda página, depois de a primeira rodar.
        objects.append(Sensor(None, "EST_TEST", datetime(2026, 8, 20)))
        from psycopg2.errors import NotNullViolation

        with self.assertRaises(NotNullViolation):
            self.repository.insert_many(objects)
        self.assertEqual(self.count(), 0)
