"""Permissões reais: executar SOMENTE em banco/cluster descartável dedicado.

Exige RUN_INTEGRATION=1, RUN_PERMISSION_INTEGRATION=1 e
PERMISSION_TEST_DATABASE igual ao POSTGRES_DB configurado.
Cria roles e tabelas permanentes exclusivamente nesse ambiente autorizado.
"""

import os
from pathlib import Path
import unittest

import psycopg2

from app.config.config import config
from app.database.connection import DatabaseConnection
from app.models.sensor import Sensor
from app.models.rejection import Rejection
from app.repository.sensor_repository import SensorRepository
from app.repository.checkpoint_repository import CheckpointRepository
from app.repository.rejection_repository import RejectionRepository
from datetime import datetime
from tests.integration.gate import integration_test


@integration_test
@unittest.skipUnless(
    os.environ.get("RUN_PERMISSION_INTEGRATION") == "1",
    "Permissões exigem cluster descartável e RUN_PERMISSION_INTEGRATION=1.",
)
class TestPrivateAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("PERMISSION_TEST_DATABASE"):
            raise RuntimeError("Defina PERMISSION_TEST_DATABASE para autorizar o banco descartável.")
        if config.POSTGRES_DB != os.environ["PERMISSION_TEST_DATABASE"]:
            raise RuntimeError("O banco configurado não corresponde a PERMISSION_TEST_DATABASE.")
        cls.database = DatabaseConnection()
        cls.addClassCleanup(cls.database.close)
        cls.connection = cls.database.connect()
        root = Path(__file__).resolve().parents[2] / "app/sql/migrations"
        cls.migration = (root / "003_private_access.sql").read_text()
        with cls.connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('etl_private.sensor_data'), to_regclass('public.sensor_data')")
            if any(cursor.fetchone()):
                raise RuntimeError("O banco de permissões deve começar vazio.")
            cursor.execute("SET search_path TO public, pg_catalog")
        cls.connection.commit()
        for path in sorted(root.glob("00[0-2]_*.sql")):
            with cls.connection.cursor() as cursor:
                cursor.execute(path.read_text())
            cls.connection.commit()
        with cls.connection.cursor() as cursor:
            # Simula grants automáticos da Data API em tabelas originalmente públicas.
            for role in ("anon", "authenticated", "service_role"):
                cursor.execute(f"CREATE ROLE {role} NOLOGIN")
                cursor.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}")
            cursor.execute("""
                INSERT INTO public.sensor_data (sensor_id, firebase_id, timestamp)
                VALUES ('EST', 'preserved', '2026-08-20');
                INSERT INTO public.buoy_data (buoy_id, firebase_id, timestamp)
                VALUES ('BOIA', 'preserved', '2026-08-20');
            """)
        cls.connection.commit()
        with cls.connection.cursor() as cursor:
            cursor.execute(cls.migration)
            cursor.execute((root / "004_measurement_timestamptz.sql").read_text())
        cls.connection.commit()

    def setUp(self):
        with self.connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute("SET search_path TO etl_private, pg_catalog")
        self.connection.commit()

    def tearDown(self):
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        self.connection.commit()

    def as_role(self, role):
        with self.connection.cursor() as cursor:
            cursor.execute(f"SET ROLE {role}")
        self.connection.commit()

    def denied(self, sql):
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            with self.connection.cursor() as cursor:
                cursor.execute(sql)
        self.connection.rollback()

    def test_roles_have_no_login_or_elevated_attributes(self):
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                       rolreplication, rolbypassrls
                FROM pg_roles WHERE rolname IN ('etl_writer', 'ai_reader')
                ORDER BY rolname
            """)
            self.assertEqual(cursor.fetchall(), [
                ("ai_reader", False, False, False, False, False, False),
                ("etl_writer", False, False, False, False, False, False),
            ])

    def test_moving_tables_preserves_data_indexes_and_removes_public_objects(self):
        with self.connection.cursor() as cursor:
            for table in ("sensor_data", "buoy_data", "etl_checkpoint", "etl_rejections"):
                cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                self.assertIsNone(cursor.fetchone()[0])
                cursor.execute("SELECT to_regclass(%s)", (f"etl_private.{table}",))
                self.assertIsNotNone(cursor.fetchone()[0])
            for table in ("sensor_data", "buoy_data"):
                cursor.execute(f"SELECT count(*) FROM etl_private.{table} WHERE firebase_id = 'preserved'")
                self.assertEqual(cursor.fetchone()[0], 1)
            for index in ("idx_sensor_sensor_time", "idx_buoy_time"):
                cursor.execute("SELECT to_regclass(%s)", (f"etl_private.{index}",))
                self.assertIsNotNone(cursor.fetchone()[0])

    def test_etl_runs_real_repositories_but_cannot_delete_or_change_structure(self):
        self.as_role("etl_writer")
        sensor = Sensor("writer-test", "EST", datetime(2026, 8, 20))
        repository = SensorRepository(self.database)
        self.assertTrue(repository.insert(sensor))
        self.assertFalse(repository.insert(sensor))
        checkpoint = CheckpointRepository(self.database)
        checkpoint.set("sensores", "EST", "one")
        checkpoint.set("sensores", "EST", "two")
        self.assertEqual(checkpoint.get("sensores", "EST"), "two")
        rejections = RejectionRepository(self.database)
        rejection = Rejection("sensores", "EST", "rejected-test", {}, "invalid")
        rejections.save_many([rejection])
        rejections.save_many([rejection])
        self.assertIn(rejection, rejections.pending())
        rejections.mark_resolved(rejection)
        with self.database.exclusive():
            pass
        for sql in (
            "UPDATE sensor_data SET temperatura = 1",
            "DELETE FROM sensor_data", "TRUNCATE buoy_data",
            "DELETE FROM etl_checkpoint", "DELETE FROM etl_rejections",
            "DROP TABLE sensor_data",
            "ALTER TABLE sensor_data ADD COLUMN forbidden integer",
            "CREATE TABLE etl_private.forbidden (id integer)",
        ):
            with self.subTest(sql=sql):
                self.denied(sql)

    def test_ai_reads_only_measurements(self):
        self.as_role("ai_reader")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM sensor_data")
            cursor.execute("SELECT * FROM buoy_data")
        self.connection.commit()
        for sql in (
            "SELECT * FROM etl_checkpoint", "SELECT * FROM etl_rejections",
            "INSERT INTO sensor_data (sensor_id, firebase_id, timestamp) VALUES ('X', 'X', now())",
            "UPDATE buoy_data SET ph = 7", "DELETE FROM sensor_data",
            "TRUNCATE buoy_data", "DROP TABLE sensor_data",
            "CREATE TABLE etl_private.forbidden (id integer)",
        ):
            with self.subTest(sql=sql):
                self.denied(sql)

    def test_data_api_roles_have_no_schema_or_table_access(self):
        for role in ("anon", "authenticated", "service_role"):
            self.as_role(role)
            for table in ("sensor_data", "buoy_data", "etl_checkpoint", "etl_rejections"):
                with self.subTest(role=role, table=table):
                    self.denied(f"SELECT * FROM etl_private.{table}")
            with self.connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
            self.connection.commit()

    def test_reapplying_migration_does_not_duplicate_or_lose_tables(self):
        with self.connection.cursor() as cursor:
            cursor.execute(self.migration)
            cursor.execute("SELECT count(*) FROM etl_private.sensor_data WHERE firebase_id = 'preserved'")
            self.assertEqual(cursor.fetchone()[0], 1)
        self.connection.commit()

    def test_conflicting_public_copy_aborts_without_deleting_data(self):
        with self.connection.cursor() as cursor:
            cursor.execute("CREATE TABLE public.sensor_data (marker text)")
            cursor.execute("INSERT INTO public.sensor_data VALUES ('keep')")
        self.connection.commit()
        try:
            with self.assertRaisesRegex(psycopg2.Error, "existe em public e etl_private"):
                with self.connection.cursor() as cursor:
                    cursor.execute(self.migration)
            self.connection.rollback()
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT marker FROM public.sensor_data")
                self.assertEqual(cursor.fetchall(), [("keep",)])
                cursor.execute("SELECT count(*) FROM etl_private.sensor_data WHERE firebase_id = 'preserved'")
                self.assertEqual(cursor.fetchone()[0], 1)
        finally:
            # Limpa apenas a tabela criada por este teste no cluster descartável.
            self.connection.rollback()
            with self.connection.cursor() as cursor:
                cursor.execute("DROP TABLE public.sensor_data")
            self.connection.commit()

    def test_existing_login_role_is_not_silently_reused(self):
        with self.connection.cursor() as cursor:
            cursor.execute("ALTER ROLE ai_reader LOGIN")
        try:
            with self.assertRaisesRegex(psycopg2.Error, "atributos ou heranças incompatíveis"):
                with self.connection.cursor() as cursor:
                    cursor.execute(self.migration)
        finally:
            self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'ai_reader'")
            self.assertFalse(cursor.fetchone()[0])
