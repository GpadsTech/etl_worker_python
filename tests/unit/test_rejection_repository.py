"""Persistência de rejeições com driver simulado, sem serviços reais."""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from app.models.rejection import Rejection
from app.repository.base import BATCH_SIZE
from app.repository.rejection_repository import RejectionRepository


class TestRejectionRepository(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.cursor = (
            self.database.connect.return_value.cursor.return_value.__enter__.return_value
        )
        self.repository = RejectionRepository(self.database)
        self.execute_patch = patch("app.repository.rejection_repository.execute_values")
        self.execute = self.execute_patch.start()
        self.addCleanup(self.execute_patch.stop)

    @staticmethod
    def rejection():
        return Rejection("sensores", "EST_TEST", "-001", {"temperatura": "x"}, "erro")

    def test_empty_batch_does_not_connect(self):
        self.repository.save_many([])
        self.database.connect.assert_not_called()

    def test_json_payloads_use_adapter_not_string_interpolation(self):
        for payload in ({"valor": "'; DROP TABLE x"}, ["x"], "x", 5, True, None):
            with self.subTest(payload=payload):
                rejected = self.rejection()
                rejected.payload = payload
                self.repository.save_many([rejected])
                sql = self.execute.call_args.args[1]
                values = self.execute.call_args.args[2][0]
                self.assertIn("ON CONFLICT (source, device_id, firebase_id)", sql)
                self.assertNotIn("DROP TABLE", sql)
                self.assertEqual(values[:3], ("sensores", "EST_TEST", "-001"))
                self.assertEqual(values[3].adapted, payload)
                self.assertEqual(values[4], "erro")

    def test_multiple_pages_commit_once(self):
        self.repository.save_many([self.rejection()] * (BATCH_SIZE + 1))
        self.assertEqual(self.execute.call_count, 2)
        self.assertEqual(self.execute.call_args_list[0].kwargs["page_size"], BATCH_SIZE)
        self.assertEqual(self.execute.call_args_list[1].kwargs["page_size"], 1)
        self.database.commit.assert_called_once()
        self.database.rollback.assert_not_called()

    def test_page_failure_rolls_back(self):
        self.execute.side_effect = [None, RuntimeError("segunda página")]
        with self.assertRaisesRegex(RuntimeError, "segunda página"):
            self.repository.save_many([self.rejection()] * (BATCH_SIZE + 1))
        self.database.rollback.assert_called_once()
        self.database.commit.assert_not_called()

    def test_commit_failure_rolls_back(self):
        self.database.commit.side_effect = RuntimeError("commit")
        with self.assertRaisesRegex(RuntimeError, "commit"):
            self.repository.save_many([self.rejection()])
        self.database.rollback.assert_called_once()

    def test_pending_is_filtered_limited_and_maps_rows(self):
        rejected = self.rejection()
        self.cursor.fetchall.return_value = [
            ("sensores", "EST_TEST", "-001", rejected.payload, "erro"),
        ]
        self.assertEqual(
            self.repository.pending(10, "sensores", "EST_TEST"), [rejected],
        )
        sql, params = self.cursor.execute.call_args.args
        self.assertIn("WHERE resolved_at IS NULL", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertEqual(params, ("sensores", "sensores", "EST_TEST", "EST_TEST", 10))

    def test_invalid_pending_arguments_do_not_connect(self):
        for kwargs in ({"limit": 0}, {"limit": -1}, {"source": "outra"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.repository.pending(**kwargs)
        self.database.connect.assert_not_called()

    def test_read_failure_rolls_back(self):
        self.cursor.execute.side_effect = RuntimeError("read")
        with self.assertRaisesRegex(RuntimeError, "read"):
            self.repository.pending()
        self.database.rollback.assert_called_once()

    def test_resolve_uses_identity_and_keeps_original_payload(self):
        self.repository.mark_resolved(self.rejection())
        sql, params = self.cursor.execute.call_args.args
        self.assertEqual(params, (None, None, "sensores", "EST_TEST", "-001"))
        self.assertIn("attempts = attempts + 1", sql)
        self.assertNotIn("payload =", sql)
        self.database.commit.assert_called_once()

    def test_failed_attempt_keeps_pending_and_reason(self):
        self.repository.mark_failed(self.rejection(), "novo erro")
        self.assertEqual(
            self.cursor.execute.call_args.args[1],
            ("novo erro", "novo erro", "sensores", "EST_TEST", "-001"),
        )
        self.database.commit.assert_called_once()

    def test_resolution_failure_rolls_back(self):
        self.cursor.execute.side_effect = RuntimeError("update")
        with self.assertRaisesRegex(RuntimeError, "update"):
            self.repository.mark_resolved(self.rejection())
        self.database.rollback.assert_called_once()
        self.database.commit.assert_not_called()

    def test_schema_reuses_rejections_migration_without_duplicate_ddl(self):
        root = Path(__file__).resolve().parents[2]
        schema = (root / "app/sql/schema.sql").read_text()
        migration = (root / "app/sql/migrations/001_etl_rejections.sql").read_text()
        table = "CREATE TABLE IF NOT EXISTS etl_rejections"
        self.assertIn(r"\ir migrations/001_etl_rejections.sql", schema)
        self.assertIn(table, migration)
        self.assertNotIn(table, schema)
