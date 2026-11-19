"""Conversão do histórico em tabelas TEMP, sem depender do fuso da sessão."""

from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from tests.integration.gate import integration_test
from tests.integration.temporary_database import TemporaryDatabaseTestCase


@integration_test
class TestTimestampMigration(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.database.connect()
        with self.connection.cursor() as cursor:
            for table in ("sensor_data", "buoy_data"):
                cursor.execute(f"""
                    ALTER TABLE pg_temp.{table} ALTER COLUMN timestamp
                    TYPE TIMESTAMP USING timestamp AT TIME ZONE 'America/Sao_Paulo'
                """)
        self.connection.commit()
        path = Path(__file__).resolve().parents[2] / (
            "app/sql/migrations/004_measurement_timestamptz.sql"
        )
        self.migration = path.read_text().replace("etl_private.", "pg_temp.")

    def test_conversion_preserves_instant_in_any_session_timezone_and_on_reapply(self):
        with self.connection.cursor() as cursor:
            for table, device in (("sensor_data", "sensor_id"), ("buoy_data", "buoy_id")):
                cursor.execute(f"""
                    INSERT INTO pg_temp.{table} ({device}, firebase_id, timestamp)
                    VALUES ('DEVICE', 'summer', '2018-01-15 12:00:00'),
                           ('DEVICE', 'current', '2026-04-23 14:48:35')
                """)
        self.connection.commit()
        for session_zone in ("Asia/Tokyo", "UTC", "America/Sao_Paulo"):
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT set_config('TimeZone', %s, false)", (session_zone,))
            self.connection.commit()
            with self.connection.cursor() as cursor:
                cursor.execute(self.migration)
            for table in ("sensor_data", "buoy_data"):
                with self.connection.cursor() as cursor:
                    cursor.execute(f"SELECT firebase_id, timestamp FROM pg_temp.{table} ORDER BY firebase_id")
                    self.assertEqual(cursor.fetchall(), [
                        ("current", datetime(2026, 4, 23, 17, 48, 35, tzinfo=timezone.utc)),
                        ("summer", datetime(2018, 1, 15, 14, tzinfo=timezone.utc)),
                    ])

    def test_dst_invalid_times_abort_both_table_changes(self):
        for table, device in (("sensor_data", "sensor_id"), ("buoy_data", "buoy_id")):
            for value in ("2018-11-04 00:30:00", "2018-02-17 23:30:00"):
                with self.subTest(table=table, value=value):
                    with self.connection.cursor() as cursor:
                        cursor.execute(
                            f"INSERT INTO pg_temp.{table} ({device}, firebase_id, timestamp) VALUES ('DEVICE', 'invalid', %s)",
                            (value,),
                        )
                    self.connection.commit()
                    with self.assertRaisesRegex(psycopg2.Error, "Revisão manual"):
                        with self.connection.cursor() as cursor:
                            cursor.execute(self.migration)
                    self.connection.rollback()
                    with self.connection.cursor() as cursor:
                        for target in ("sensor_data", "buoy_data"):
                            cursor.execute("""
                                SELECT atttypid::regtype::text FROM pg_attribute
                                WHERE attrelid = %s::regclass AND attname = 'timestamp'
                            """, (f"pg_temp.{target}",))
                            self.assertEqual(cursor.fetchone()[0], "timestamp without time zone")
                        cursor.execute(f"SELECT timestamp FROM pg_temp.{table}")
                        self.assertEqual(cursor.fetchone()[0], datetime.fromisoformat(value))
                        cursor.execute(f"DELETE FROM pg_temp.{table}")
                    self.connection.commit()
