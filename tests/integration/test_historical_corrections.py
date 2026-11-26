"""Correção com transação SQL real e Firebase simulado; nenhum dado permanente."""

from pathlib import Path
from unittest.mock import Mock, patch

from app.reprocess_history import correct
from app.worker.etl_worker import ETLWorker
from tests.integration.gate import integration_test
from tests.integration.temporary_database import TemporaryDatabaseTestCase
from tests.unit.test_pagination import key
from tests.pagination_scenarios import record


@integration_test
class TestHistoricalCorrections(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        # Mesma definição da migração, mas confinada ao schema TEMP.
        ddl = Path("app/sql/migrations/005_historical_corrections.sql").read_text()
        ddl = ddl[ddl.index("CREATE TABLE"):ddl.index("REVOKE ALL")]
        ddl = ddl.replace("CREATE TABLE IF NOT EXISTS etl_private.", "CREATE TEMP TABLE ")
        with self.database.connect().cursor() as cursor:
            cursor.execute(ddl)
        self.database.commit()
        with patch("app.worker.etl_worker.DatabaseConnection", return_value=self.database), \
                patch("app.worker.etl_worker.FirebaseClient"):
            self.worker = ETLWorker()
        self.worker.logger = Mock()
        from app.transformer.normalize import normalize_sensor
        self.worker.sensor_repository.insert(normalize_sensor(
            firebase_id=key(1), sensor_id="EST", data=record(25),
        ))
        self.worker.checkpoints.set("sensores", "EST", key(9))
        self.worker.firebase.sensor_data.return_value.child.return_value.get.return_value = record(30)

    def state(self):
        with self.database.connect().cursor() as cursor:
            cursor.execute("SELECT temperatura FROM pg_temp.sensor_data")
            temperature = cursor.fetchone()[0]
            cursor.execute("SELECT before_row, after_row FROM pg_temp.etl_corrections")
            return temperature, cursor.fetchall()

    def preview(self):
        return correct(self.worker, "sensores", "EST", key(1), "correção controlada")

    def apply(self, preview):
        return correct(self.worker, "sensores", "EST", key(1), "correção controlada",
                       preview["before_sha256"], True, preview["after_sha256"])

    def test_preview_is_read_only_then_apply_has_atomic_audit_and_preserves_cursor(self):
        preview = self.preview()
        self.assertTrue(preview["changed"])
        self.assertFalse(preview["applied"])
        self.assertEqual(self.state(), (25, []))
        self.assertTrue(self.apply(preview)["applied"])
        temperature, audit = self.state()
        self.assertEqual(temperature, 30)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0][0]["temperatura"], 25)
        self.assertEqual(audit[0][1]["temperatura"], 30)
        self.assertEqual(self.worker.checkpoints.get("sensores", "EST"), key(9))

    def test_stale_database_hash_refuses_repeated_apply(self):
        preview = self.preview()
        self.apply(preview)
        with self.assertRaisesRegex(ValueError, "anterior"):
            self.apply(preview)
        self.assertEqual(len(self.state()[1]), 1)

    def test_changed_source_since_preview_requires_review_again(self):
        preview = self.preview()
        self.worker.firebase.sensor_data.return_value.child.return_value.get.return_value = record(35)
        with self.assertRaisesRegex(ValueError, "origem"):
            self.apply(preview)
        self.assertEqual(self.state(), (25, []))

    def test_audit_failure_rolls_back_measurement_update(self):
        preview = self.preview()
        with self.database.connect().cursor() as cursor:
            cursor.execute("ALTER TABLE pg_temp.etl_corrections ADD CHECK (false)")
        self.database.commit()
        with self.assertRaises(Exception):
            self.apply(preview)
        self.assertEqual(self.state(), (25, []))

    def test_no_change_is_noop_and_missing_source_or_reason_are_refused(self):
        self.worker.firebase.sensor_data.return_value.child.return_value.get.return_value = record(25)
        preview = self.preview()
        self.assertFalse(preview["changed"])
        self.assertFalse(self.apply(preview)["applied"])
        self.assertEqual(self.state(), (25, []))
        self.worker.firebase.sensor_data.return_value.child.return_value.get.return_value = None
        with self.assertRaises(ValueError):
            self.preview()
        with self.assertRaises(ValueError):
            correct(self.worker, "sensores", "EST", key(1), "  ")
