"""Valida a migração 002 em tabelas TEMP com as chaves antigas."""

from pathlib import Path

import psycopg2

from tests.integration.gate import integration_test
from tests.integration.temporary_database import TemporaryDatabaseTestCase


@integration_test
class TestIdentityMigration(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.database.connect()
        with self.connection.cursor() as cursor:
            for table in ("sensor_data", "buoy_data"):
                cursor.execute(f"""
                    ALTER TABLE pg_temp.{table} DROP CONSTRAINT {table}_pkey;
                    ALTER TABLE pg_temp.{table} ADD PRIMARY KEY (firebase_id, timestamp);
                """)
        self.connection.commit()
        path = Path(__file__).resolve().parents[2] / (
            "app/sql/migrations/002_device_reading_identity.sql"
        )
        # Executar exatamente o SQL versionado, apenas redirecionando as tabelas.
        self.migration = path.read_text().replace("public.sensor_data", "pg_temp.sensor_data")
        self.migration = self.migration.replace("public.buoy_data", "pg_temp.buoy_data")

    def test_migration_preserves_rows_and_can_be_reapplied(self):
        with self.connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO pg_temp.sensor_data (sensor_id, firebase_id, timestamp)
                VALUES ('EST001', '-001', '2026-08-20');
                INSERT INTO pg_temp.buoy_data (buoy_id, firebase_id, timestamp)
                VALUES ('BOIA001', '-001', '2026-08-20');
            """)
        self.connection.commit()
        for _ in range(2):
            with self.connection.cursor() as cursor:
                cursor.execute(self.migration)
        with self.connection.cursor() as cursor:
            for table, device_column in (
                ("sensor_data", "sensor_id"), ("buoy_data", "buoy_id"),
            ):
                cursor.execute(f"SELECT count(*) FROM pg_temp.{table}")
                self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(f"""
                    INSERT INTO pg_temp.{table} ({device_column}, firebase_id, timestamp)
                    VALUES ('OUTRO', '-001', '2026-08-20')
                    ON CONFLICT ({device_column}, firebase_id) DO NOTHING;
                """)
                self.assertEqual(cursor.rowcount, 1)

    def test_inherited_tables_are_rejected_without_extension_catalogs(self):
        with self.connection.cursor() as cursor:
            cursor.execute("""
                CREATE TEMP TABLE sensor_child ()
                INHERITS (pg_temp.sensor_data);
            """)
        self.connection.commit()
        with self.assertRaisesRegex(psycopg2.Error, "sem particionamento ou herança"):
            with self.connection.cursor() as cursor:
                cursor.execute(self.migration)
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'pg_temp.sensor_data'::regclass AND contype = 'p'
            """)
            self.assertEqual(
                cursor.fetchone()[0], 'PRIMARY KEY (firebase_id, "timestamp")',
            )

    def test_duplicates_abort_without_removing_rows_or_changing_keys(self):
        for table, device_column in (
            ("sensor_data", "sensor_id"), ("buoy_data", "buoy_id"),
        ):
            with self.subTest(table=table):
                with self.connection.cursor() as cursor:
                    cursor.execute(f"""
                        INSERT INTO pg_temp.{table} ({device_column}, firebase_id, timestamp)
                        VALUES ('DEVICE', '-001', '2026-08-20'),
                               ('DEVICE', '-001', '2026-08-21');
                    """)
                self.connection.commit()
                with self.assertRaisesRegex(psycopg2.Error, "Revisão manual"):
                    with self.connection.cursor() as cursor:
                        cursor.execute(self.migration)
                self.connection.rollback()
                with self.connection.cursor() as cursor:
                    cursor.execute(f"SELECT count(*) FROM pg_temp.{table}")
                    self.assertEqual(cursor.fetchone()[0], 2)
                    for current in ("sensor_data", "buoy_data"):
                        cursor.execute("""
                            SELECT pg_get_constraintdef(oid)
                            FROM pg_constraint
                            WHERE conrelid = %s::regclass AND contype = 'p'
                        """, (f"pg_temp.{current}",))
                        self.assertEqual(
                            cursor.fetchone()[0], "PRIMARY KEY (firebase_id, \"timestamp\")",
                        )
                    cursor.execute(f"DELETE FROM pg_temp.{table}")
                self.connection.commit()
