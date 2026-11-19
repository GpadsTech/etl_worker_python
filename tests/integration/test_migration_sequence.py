"""Sequência versionada completa, isolada em tabelas temporárias por sessão."""

from pathlib import Path
import unittest

from app.config.config import config
from app.database.connection import DatabaseConnection
from tests.integration.gate import integration_test


@integration_test
class TestMigrationSequence(unittest.TestCase):
    def setUp(self):
        self.database = DatabaseConnection()
        self.addCleanup(self.database.close)
        self.connection = self.database.connect()
        with self.connection.cursor() as cursor:
            cursor.execute("SET search_path TO pg_temp, pg_catalog")
        self.connection.commit()
        self.migrations = sorted(
            # Permissões/schema reais têm suíte separada com autorização adicional.
            (Path(__file__).resolve().parents[2] / "app/sql/migrations").glob("00[0-2]_*.sql")
        )

    def apply_migrations(self):
        for path in self.migrations:
            # Mesmo DDL, mas sem criar ou consultar tabelas permanentes.
            sql = path.read_text().replace(
                "CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE IF NOT EXISTS",
            ).replace("public.sensor_data", "pg_temp.sensor_data").replace(
                "public.buoy_data", "pg_temp.buoy_data",
            )
            with self.connection.cursor() as cursor:
                cursor.execute(sql)
            self.connection.commit()

    def test_empty_database_and_repeated_application(self):
        self.apply_migrations()
        self.apply_migrations()
        with self.connection.cursor() as cursor:
            for table in ("sensor_data", "buoy_data", "etl_checkpoint", "etl_rejections"):
                cursor.execute("SELECT relpersistence FROM pg_class WHERE oid = %s::regclass",
                               (f"pg_temp.{table}",))
                self.assertEqual(cursor.fetchone()[0], "t")
            for table, device in (("sensor_data", "sensor_id"), ("buoy_data", "buoy_id")):
                cursor.execute("""
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = %s::regclass AND contype = 'p'
                """, (f"pg_temp.{table}",))
                self.assertEqual(cursor.fetchone()[0], f"PRIMARY KEY ({device}, firebase_id)")

    def test_existing_old_keys_and_data_are_preserved(self):
        self.apply_migrations()
        with self.connection.cursor() as cursor:
            for table, device in (("sensor_data", "sensor_id"), ("buoy_data", "buoy_id")):
                cursor.execute(f"""
                    ALTER TABLE pg_temp.{table} DROP CONSTRAINT {table}_pkey;
                    ALTER TABLE pg_temp.{table} ADD PRIMARY KEY (firebase_id, timestamp);
                    INSERT INTO pg_temp.{table} ({device}, firebase_id, timestamp)
                    VALUES ('DEVICE', '-001', '2026-08-20');
                """)
            cursor.execute("""
                INSERT INTO pg_temp.etl_checkpoint (source, device_id, last_key)
                VALUES ('sensores', 'DEVICE', '-001');
                INSERT INTO pg_temp.etl_rejections
                    (source, device_id, firebase_id, payload, reason)
                VALUES ('boias', 'DEVICE', '-002', '{}', 'invalid');
            """)
        self.connection.commit()
        self.apply_migrations()
        with self.connection.cursor() as cursor:
            for table in ("sensor_data", "buoy_data", "etl_checkpoint", "etl_rejections"):
                cursor.execute(f"SELECT count(*) FROM pg_temp.{table}")
                self.assertEqual(cursor.fetchone()[0], 1)
            for table, device in (("sensor_data", "sensor_id"), ("buoy_data", "buoy_id")):
                cursor.execute(f"""
                    INSERT INTO pg_temp.{table} ({device}, firebase_id, timestamp)
                    VALUES ('DEVICE', '-001', '2026-08-21')
                    ON CONFLICT ({device}, firebase_id) DO NOTHING
                """)
                self.assertEqual(cursor.rowcount, 0)

    def test_connection_applies_environment_timeouts(self):
        with self.connection.cursor() as cursor:
            for setting, expected in (
                ("statement_timeout", config.POSTGRES_STATEMENT_TIMEOUT_MS),
                ("lock_timeout", config.POSTGRES_LOCK_TIMEOUT_MS),
            ):
                cursor.execute(
                    "SELECT setting::integer FROM pg_settings WHERE name = %s", (setting,),
                )
                self.assertEqual(cursor.fetchone()[0], expected)
