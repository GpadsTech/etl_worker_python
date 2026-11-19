"""Impede a reintrodução de dependências de extensões no fluxo SQL."""

from pathlib import Path
import re
import unittest


SQL_ROOT = Path(__file__).resolve().parents[2] / "app/sql"


class TestPostgreSQLSchema(unittest.TestCase):
    def test_sql_scripts_do_not_depend_on_timescaledb(self):
        for path in SQL_ROOT.rglob("*.sql"):
            with self.subTest(script=path.name):
                sql = path.read_text().lower()
                self.assertNotIn("timescaledb", sql)
                self.assertNotIn("create_hypertable", sql)
                self.assertIsNone(re.search(r"\bcreate\s+extension\b", sql))

    def test_bootstrap_preserves_measurement_identity_and_time_indexes(self):
        sql = (SQL_ROOT / "migrations/000_initial_schema.sql").read_text()
        for device in ("sensor_id", "buoy_id"):
            with self.subTest(device=device):
                self.assertIn(f"PRIMARY KEY ({device}, firebase_id)", sql)
                self.assertIn(f"({device}, timestamp DESC)", sql)
        # Base histórica imutável: a conversão explícita ocorre na migração 004.
        self.assertEqual(sql.count("timestamp TIMESTAMP NOT NULL"), 2)

    def test_timezone_conversion_is_explicit_and_versioned(self):
        sql = (SQL_ROOT / "migrations/004_measurement_timestamptz.sql").read_text()
        self.assertIn("TYPE TIMESTAMPTZ USING timestamp AT TIME ZONE ''America/Sao_Paulo''", sql)
        self.assertIn("timestamp with time zone", sql)

    def test_psql_entrypoint_only_includes_versioned_migrations_in_order(self):
        sql = (SQL_ROOT / "schema.sql").read_text()
        includes = re.findall(r"^\\ir (.+)$", sql, re.MULTILINE)
        self.assertEqual(includes, [
            f"migrations/{path.name}"
            for path in sorted((SQL_ROOT / "migrations").glob("*.sql"))
        ])
        self.assertIn(r"\set ON_ERROR_STOP on", sql)
        self.assertNotIn("CREATE TABLE", sql)
